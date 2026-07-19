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
from em.doctor import print_doctor
from em.config import (
    clear_telegram,
    load_config,
    redact_token,
    save_config,
)
from em.notify import telegram as tg
from em.notify.approvals import write_decision
from em.notify.telegram import TelegramError

app = typer.Typer(
    name="em",
    help="Engineering Manager — orchestrate multi-agent coding workflows.",
    no_args_is_help=True,
)
config_app = typer.Typer(
    name="config",
    help="Manage local em config (~/.em/config.yaml).",
    no_args_is_help=True,
)
notify_app = typer.Typer(
    name="notify",
    help="Test notification channels.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(notify_app, name="notify")
console = Console()


@app.command("doctor")
def doctor_cmd() -> None:
    """Check Python, PATH, em, and optional agent CLIs."""
    code = print_doctor(console)
    raise typer.Exit(code)


@config_app.command("show")
def config_show_cmd() -> None:
    """Show local config (tokens redacted)."""
    cfg = load_config()
    console.print(f"Config file: [cyan]{Path.home() / '.em' / 'config.yaml'}[/cyan]")
    console.print(
        f"Telegram bot: [cyan]{redact_token(cfg.telegram.bot_token)}[/cyan]"
    )
    console.print(
        f"Telegram chat_id: [cyan]{cfg.telegram.chat_id or '(not set)'}[/cyan]"
    )
    console.print(
        f"Allowed chat ids: [cyan]{cfg.telegram.allowed_chat_ids or '(none)'}[/cyan]"
    )
    console.print(
        f"Notify on task complete: {cfg.notify.on_task_complete}"
    )
    console.print(f"Notify on run complete: {cfg.notify.on_run_complete}")
    if cfg.telegram.is_configured():
        console.print("[green]Telegram: configured[/green]")
    else:
        console.print(
            "[yellow]Telegram: not configured[/yellow] — run [cyan]em config telegram[/cyan]"
        )


@config_app.command("telegram")
def config_telegram_cmd(
    token: Optional[str] = typer.Option(
        None, "--token", help="Bot token from @BotFather"
    ),
    chat_id: Optional[str] = typer.Option(
        None,
        "--chat-id",
        help="Optional. If omitted, em detects it after you message the bot.",
    ),
) -> None:
    """Save your personal Telegram bot. em detects chat id when possible."""
    import sys

    cfg = load_config()
    if not token:
        if not sys.stdin.isatty():
            console.print("[red]Token is required (--token)[/red]")
            raise typer.Exit(1)
        console.print(
            "1. Open Telegram → @BotFather → /newbot\n"
            "2. Copy the bot token it gives you."
        )
        token = typer.prompt("Bot token", hide_input=True)
    token = (token or "").strip()
    if not token:
        console.print("[red]Token is required[/red]")
        raise typer.Exit(1)

    try:
        me = tg.get_me(token)
        username = me.get("username") or "bot"
        console.print(f"[green]Bot ok[/green]: @{username}")
    except TelegramError as e:
        console.print(f"[red]Invalid token:[/red] {e}")
        raise typer.Exit(1) from e

    if chat_id is None:
        chat_id = ""
    chat_id = (chat_id or "").strip()

    if not chat_id:
        console.print(
            f"Open Telegram, message [cyan]@{username}[/cyan] (any text, e.g. hi),\n"
            "then wait here — em will detect your chat id automatically…"
        )
        if sys.stdin.isatty():
            discovered = tg.discover_chat_id(token, wait_seconds=90)
        else:
            discovered = tg.discover_chat_id(token, wait_seconds=5)
        if not discovered:
            console.print(
                "[red]Could not detect chat id.[/red] Message the bot, then run again:\n"
                "  [cyan]em config telegram --token …[/cyan]\n"
                "Or pass it explicitly: [cyan]--chat-id YOUR_ID[/cyan]"
            )
            raise typer.Exit(1)
        chat_id = discovered
        console.print(f"[green]Detected chat id[/green]: {chat_id}")

    cfg.telegram.bot_token = token
    cfg.telegram.chat_id = chat_id
    if chat_id not in cfg.telegram.allowed_chat_ids:
        cfg.telegram.allowed_chat_ids.append(chat_id)

    path = save_config(cfg)
    console.print(f"[green]Saved[/green] {path}")

    try:
        tg.send_message(
            token,
            chat_id,
            "✅ <b>em setup complete</b>\nYou'll get task summaries and approval requests here.",
            parse_mode="HTML",
        )
        console.print("[green]Sent[/green] setup message to Telegram. You're done.")
    except TelegramError as e:
        console.print(f"[yellow]Saved, but test message failed:[/yellow] {e}")


@config_app.command("clear")
def config_clear_cmd(
    channel: str = typer.Argument(..., help="Channel to clear (telegram)"),
) -> None:
    """Remove a notification channel from local config."""
    if channel != "telegram":
        console.print("[red]Only 'telegram' is supported for clear[/red]")
        raise typer.Exit(1)
    cfg = clear_telegram(load_config())
    path = save_config(cfg)
    console.print(f"[green]Cleared telegram settings in[/green] {path}")


@notify_app.command("test")
def notify_test_cmd() -> None:
    """Send a test Telegram message using local config."""
    cfg = load_config()
    if not cfg.telegram.is_configured():
        console.print(
            "[red]Telegram not configured.[/red] Run [cyan]em config telegram[/cyan]"
        )
        raise typer.Exit(1)
    try:
        tg.send_message(
            cfg.telegram.bot_token,
            cfg.telegram.chat_id,
            "✅ <b>em notify test</b>\nRemote control is set up.",
            parse_mode="HTML",
        )
    except TelegramError as e:
        console.print(f"[red]Send failed:[/red] {e}")
        raise typer.Exit(1) from e
    console.print("[green]Sent[/green] test message to your Telegram chat.")


@app.command("approve")
def approve_cmd(
    run_id: str = typer.Argument(..., help="Run id"),
    task_id: str = typer.Argument(..., help="Task id waiting for approval"),
    state_dir: Optional[str] = typer.Option(None, "--state-dir"),
) -> None:
    """Approve a task that is waiting (desk control)."""
    store = _store_from_option(state_dir)
    path = write_decision(
        store.root, run_id, task_id, "approve", source="cli"
    )
    console.print(f"[green]Approved[/green] {run_id} / {task_id}")
    console.print(f"Wrote {path}")


@app.command("reject")
def reject_cmd(
    run_id: str = typer.Argument(..., help="Run id"),
    task_id: str = typer.Argument(..., help="Task id waiting for approval"),
    reason: str = typer.Option("", "--reason", "-r", help="Optional reason"),
    state_dir: Optional[str] = typer.Option(None, "--state-dir"),
) -> None:
    """Reject a task that is waiting (desk control)."""
    store = _store_from_option(state_dir)
    path = write_decision(
        store.root, run_id, task_id, "reject", reason=reason, source="cli"
    )
    console.print(f"[yellow]Rejected[/yellow] {run_id} / {task_id}")
    console.print(f"Wrote {path}")


STARTER_WORKFLOW = """# Starter workflow for `em`. Edit prompts, then: em run workflow.yaml
# Providers: cursor / claude / codex / gemini / shell
#   Claude Code: `claude` on PATH
#   Cursor: `agent` / `cursor-agent` on PATH + `agent login` (no API key)
# Optional: requires_approval: true on a task → pause for desk/Telegram confirm
# Telegram: em config telegram   then   em notify test
name: add-checkout-flow-real
cwd: .
max_parallel: 2
defaults:
  on_failure: retry
  max_retries: 1

agents:
  ui:
    provider: claude
    model: sonnet
  api:
    provider: cursor
    model: composer-2.5
  qa:
    provider: claude
    model: sonnet
  fixer:
    provider: claude
    model: opus

tasks:
  - id: implement-ui
    agent: ui
    prompt: |
      Implement the checkout UI. Keep changes minimal and focused.

  - id: implement-api
    agent: api
    prompt: |
      Implement the checkout API endpoint matching the UI contracts.

  - id: write-tests
    agent: qa
    depends_on: [implement-ui, implement-api]
    prompt: |
      Add tests for checkout. Run them and report results.
      Upstream:
      {{upstream.summary}}

  - id: fix-failures
    agent: fixer
    depends_on: [write-tests]
    when: on_upstream_failure
    prompt: |
      Fix the failures from QA:
      {{upstream.summary}}
"""


@app.command("init")
def init_cmd(
    path: Path = typer.Argument(
        Path("workflow.yaml"), help="Where to write the workflow file"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite if the file already exists"
    ),
) -> None:
    """Create a starter workflow.yaml in the current project."""
    if path.exists() and not force:
        console.print(f"[red]{path} already exists[/red] (use --force to overwrite)")
        raise typer.Exit(1)
    path.write_text(STARTER_WORKFLOW, encoding="utf-8")
    console.print(f"[green]Created[/green] {path}")
    console.print("Edit the prompts, then run: [cyan]em run " f"{path.name}[/cyan]")


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
    workflow: Path = typer.Argument(..., help="Path to workflow YAML"),
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
    if not workflow.is_file():
        console.print(f"[red]Workflow not found:[/red] {workflow}")
        raise typer.Exit(1)

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

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows / unsupported event-loop signal APIs
            try:
                signal.signal(sig, lambda *_: _sig_handler())
            except (ValueError, OSError):
                pass

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
