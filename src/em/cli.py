"""CLI entry points for the Engineering Manager."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from em.monitor import LiveMonitor, print_status
from em.scheduler import Scheduler
from em.state import StateStore, default_state_dir
from em.workflow import WorkflowError, load_workflow

app = typer.Typer(
    name="em",
    help="Engineering Manager — orchestrate multi-agent coding workflows.",
    no_args_is_help=True,
)
console = Console()


def _resolve_cwd(workflow_cwd: str | None, override: str | None) -> str:
    if override:
        return str(Path(override).resolve())
    if workflow_cwd:
        return str(Path(workflow_cwd).expanduser().resolve())
    return str(Path.cwd().resolve())


def _providers_map(workflow) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for task in workflow.tasks:
        agent = workflow.agents[task.agent]
        mapping[task.id] = agent.provider
    return mapping


@app.command("run")
def run_cmd(
    workflow: Path = typer.Argument(..., exists=True, help="Path to workflow YAML"),
    cwd: Optional[str] = typer.Option(
        None, "--cwd", help="Working directory for agents (overrides workflow.cwd)"
    ),
    state_dir: Optional[str] = typer.Option(
        None, "--state-dir", help="Directory for .em run state (default: <cwd>/.em)"
    ),
    no_live: bool = typer.Option(
        False, "--no-live", help="Disable live status board; print updates sparsely"
    ),
) -> None:
    """Start a new workflow run."""
    try:
        wf = load_workflow(workflow)
    except WorkflowError as e:
        console.print(f"[red]Invalid workflow:[/red] {e}")
        raise typer.Exit(1) from e

    work_cwd = _resolve_cwd(wf.cwd, cwd)
    store = StateStore(state_dir or default_state_dir(work_cwd))
    state = store.create_run(wf, work_cwd)
    providers = _providers_map(wf)

    console.print(
        f"[bold]Started[/bold] {wf.name}  run_id=[cyan]{state.run_id}[/cyan]  cwd={work_cwd}"
    )

    exit_code = asyncio.run(
        _execute(wf, store, state, providers=providers, live=not no_live)
    )
    raise typer.Exit(exit_code)


@app.command("resume")
def resume_cmd(
    run_id: Optional[str] = typer.Argument(
        None, help="Run id to resume (default: latest)"
    ),
    state_dir: Optional[str] = typer.Option(
        None, "--state-dir", help="State directory (default: ./.em or <cwd>/.em)"
    ),
    no_live: bool = typer.Option(False, "--no-live"),
) -> None:
    """Resume an interrupted or failed-in-progress run."""
    store = _store_from_option(state_dir)
    try:
        state = store.load(run_id) if run_id else store.load_latest()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if state is None:
        console.print("[red]No runs found.[/red]")
        raise typer.Exit(1)

    if not state.workflow_path:
        console.print("[red]Run is missing workflow_path; cannot resume.[/red]")
        raise typer.Exit(1)

    try:
        wf = load_workflow(state.workflow_path)
    except WorkflowError as e:
        console.print(f"[red]Invalid workflow:[/red] {e}")
        raise typer.Exit(1) from e

    state = store.prepare_for_resume(state)
    providers = _providers_map(wf)
    console.print(f"[bold]Resuming[/bold] [cyan]{state.run_id}[/cyan]")

    exit_code = asyncio.run(
        _execute(wf, store, state, providers=providers, live=not no_live)
    )
    raise typer.Exit(exit_code)


@app.command("status")
def status_cmd(
    run_id: Optional[str] = typer.Argument(
        None, help="Run id (default: latest)"
    ),
    state_dir: Optional[str] = typer.Option(None, "--state-dir"),
) -> None:
    """Show status of a run."""
    store = _store_from_option(state_dir)
    try:
        state = store.load(run_id) if run_id else store.load_latest()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if state is None:
        console.print("[red]No runs found.[/red]")
        raise typer.Exit(1)

    providers: dict[str, str] = {}
    if state.workflow_path and Path(state.workflow_path).is_file():
        try:
            wf = load_workflow(state.workflow_path)
            providers = _providers_map(wf)
        except WorkflowError:
            pass

    print_status(state, providers)
    console.print(f"State file: {store.run_path(state.run_id)}")
    console.print(f"Logs: {store.logs_dir / state.run_id}")


@app.command("cancel")
def cancel_cmd(
    run_id: Optional[str] = typer.Argument(
        None, help="Run id to cancel (default: latest)"
    ),
    state_dir: Optional[str] = typer.Option(None, "--state-dir"),
) -> None:
    """Mark a run as cancelled (stops resume from continuing pending work)."""
    store = _store_from_option(state_dir)
    try:
        state = store.load(run_id) if run_id else store.load_latest()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if state is None:
        console.print("[red]No runs found.[/red]")
        raise typer.Exit(1)

    store.mark_cancelled(state)
    console.print(f"[yellow]Cancelled[/yellow] {state.run_id}")
    print_status(state)


def _store_from_option(state_dir: str | None) -> StateStore:
    if state_dir:
        return StateStore(state_dir)
    # Prefer ./.em if present, else cwd/.em
    local = Path.cwd() / ".em"
    return StateStore(local if local.exists() else default_state_dir())


async def _execute(wf, store: StateStore, state, *, providers: dict[str, str], live: bool) -> int:
    scheduler = Scheduler(wf, store)
    loop = asyncio.get_running_loop()

    def _sig_handler() -> None:
        console.print("\n[yellow]Cancel requested…[/yellow]")
        scheduler.request_cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except NotImplementedError:
            # Windows
            signal.signal(sig, lambda *_: _sig_handler())

    if live:
        with LiveMonitor(console=console, providers=providers) as monitor:

            async def on_update(s) -> None:
                monitor.update(s)

            scheduler.on_update = on_update
            final = await scheduler.run(state)
            monitor.update(final)
    else:
        last_snapshot: dict[str, str] = {}

        async def on_update(s) -> None:
            snapshot = {tid: ts.status.value for tid, ts in s.tasks.items()}
            if snapshot != last_snapshot:
                last_snapshot.clear()
                last_snapshot.update(snapshot)
                print_status(s, providers)

        scheduler.on_update = on_update
        final = await scheduler.run(state)
        print_status(final, providers)

    if final.status.value == "succeeded":
        console.print("[green]Workflow succeeded.[/green]")
        return 0
    if final.status.value == "cancelled":
        console.print("[yellow]Workflow cancelled.[/yellow]")
        return 130
    console.print("[red]Workflow failed.[/red]")
    return 2


if __name__ == "__main__":
    app()
