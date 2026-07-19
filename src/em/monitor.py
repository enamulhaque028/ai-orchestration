"""Rich terminal status board for live runs."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from em.models import RunState, TaskStatus

STATUS_STYLE = {
    TaskStatus.PENDING: "dim",
    TaskStatus.READY: "cyan",
    TaskStatus.WAITING_APPROVAL: "bright_yellow",
    TaskStatus.WAITING_HUMAN: "bright_magenta",
    TaskStatus.RUNNING: "yellow",
    TaskStatus.SUCCEEDED: "green",
    TaskStatus.FAILED: "red",
    TaskStatus.SKIPPED: "magenta",
    TaskStatus.CANCELLED: "red",
}


def format_duration(started_at: str | None, finished_at: str | None = None) -> str:
    if not started_at:
        return "-"
    try:
        start = datetime.fromisoformat(started_at)
        end = (
            datetime.fromisoformat(finished_at)
            if finished_at
            else datetime.now(timezone.utc)
        )
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        secs = max(0, int((end - start).total_seconds()))
    except ValueError:
        return "-"
    if secs < 60:
        return f"{secs}s"
    mins, secs = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m{secs:02d}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h{mins:02d}m"


def render_board(state: RunState, providers: dict[str, str] | None = None) -> Table:
    providers = providers or {}
    table = Table(
        title=f"[{state.workflow_name}] {state.run_id}  ({state.status.value})",
        show_header=True,
        header_style="bold",
        expand=True,
    )
    table.add_column("Task", style="bold")
    table.add_column("Provider")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Summary")

    for task_id, ts in state.tasks.items():
        style = STATUS_STYLE.get(ts.status, "")
        status_text = Text(ts.status.value, style=style)
        summary = (ts.summary or ts.error or "").replace("\n", " ")
        if len(summary) > 80:
            summary = summary[:77] + "..."
        table.add_row(
            task_id,
            providers.get(task_id, "-"),
            status_text,
            format_duration(ts.started_at, ts.finished_at),
            summary,
        )
    return table


class LiveMonitor:
    def __init__(
        self,
        *,
        console: Console | None = None,
        providers: dict[str, str] | None = None,
    ) -> None:
        self.console = console or Console()
        self.providers = providers or {}
        self._live: Live | None = None

    def __enter__(self) -> LiveMonitor:
        self._live = Live(
            Text("Starting…"),
            console=self.console,
            refresh_per_second=4,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        if self._live:
            self._live.__exit__(*args)
            self._live = None

    def update(self, state: RunState) -> None:
        board = render_board(state, self.providers)
        if self._live:
            self._live.update(Group(board))
        else:
            self.console.print(board)


def print_status(state: RunState, providers: dict[str, str] | None = None) -> None:
    console = Console()
    console.print(render_board(state, providers))
    if state.error:
        console.print(f"[red]Error:[/red] {state.error}")
