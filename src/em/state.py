"""Persist and load Engineering Manager run state."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from em.models import RunState, RunStatus, TaskState, TaskStatus, Workflow


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state_dir(cwd: str | Path | None = None) -> Path:
    base = Path(cwd) if cwd else Path.cwd()
    return base / ".em"


class StateStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else default_state_dir()
        self.runs_dir = self.root / "runs"
        self.logs_dir = self.root / "logs"
        self.latest_path = self.root / "latest"

    def ensure(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def new_run_id(self) -> str:
        return f"run_{uuid.uuid4().hex[:12]}"

    def run_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def log_path(self, run_id: str, task_id: str) -> Path:
        return self.logs_dir / run_id / f"{task_id}.log"

    def create_run(self, workflow: Workflow, cwd: str) -> RunState:
        self.ensure()
        now = utc_now()
        run_id = self.new_run_id()
        tasks = {t.id: TaskState(id=t.id, status=TaskStatus.PENDING) for t in workflow.tasks}
        state = RunState(
            run_id=run_id,
            workflow_name=workflow.name,
            workflow_path=workflow.source_path or "",
            cwd=cwd,
            status=RunStatus.PENDING,
            max_parallel=workflow.max_parallel,
            tasks=tasks,
            created_at=now,
            updated_at=now,
        )
        self.save(state)
        self._set_latest(run_id)
        return state

    def save(self, state: RunState) -> None:
        self.ensure()
        state.updated_at = utc_now()
        path = self.run_path(state.run_id)
        path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        self._set_latest(state.run_id)

    def load(self, run_id: str) -> RunState:
        path = self.run_path(run_id)
        if not path.is_file():
            raise FileNotFoundError(f"Run not found: {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunState.from_dict(data)

    def latest_run_id(self) -> str | None:
        if not self.latest_path.is_file():
            return None
        return self.latest_path.read_text(encoding="utf-8").strip() or None

    def load_latest(self) -> RunState | None:
        run_id = self.latest_run_id()
        if not run_id:
            return None
        return self.load(run_id)

    def prepare_for_resume(self, state: RunState) -> RunState:
        """Reset interrupted running tasks so they can be retried."""
        for task in state.tasks.values():
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PENDING
                task.error = "Interrupted; will retry on resume"
                task.finished_at = None
            elif task.status == TaskStatus.READY:
                task.status = TaskStatus.PENDING
            elif task.status == TaskStatus.WAITING_APPROVAL:
                # Re-enter approval wait on resume
                task.status = TaskStatus.PENDING
                task.finished_at = None
            elif task.status == TaskStatus.WAITING_HUMAN:
                task.status = TaskStatus.PENDING
                task.finished_at = None
        if state.status in (RunStatus.RUNNING, RunStatus.CANCELLED):
            state.status = RunStatus.PENDING
            state.error = None
        self.save(state)
        return state

    def mark_cancelled(self, state: RunState) -> RunState:
        for task in state.tasks.values():
            if task.status in (
                TaskStatus.PENDING,
                TaskStatus.READY,
                TaskStatus.WAITING_APPROVAL,
                TaskStatus.WAITING_HUMAN,
                TaskStatus.RUNNING,
            ):
                task.status = TaskStatus.CANCELLED
                task.finished_at = utc_now()
        state.status = RunStatus.CANCELLED
        state.error = "Cancelled by user"
        self.save(state)
        return state

    def _set_latest(self, run_id: str) -> None:
        self.ensure()
        self.latest_path.write_text(run_id, encoding="utf-8")
