"""Domain models for workflows, tasks, and agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class FailurePolicy(str, Enum):
    RETRY = "retry"
    FAIL = "fail"
    SKIP = "skip"


class TaskWhen(str, Enum):
    ALWAYS = "always"
    ON_UPSTREAM_FAILURE = "on_upstream_failure"
    ON_UPSTREAM_SUCCESS = "on_upstream_success"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentDef:
    name: str
    provider: str
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskDef:
    id: str
    agent: str
    prompt: str
    depends_on: list[str] = field(default_factory=list)
    when: TaskWhen = TaskWhen.ALWAYS
    on_failure: FailurePolicy | None = None
    max_retries: int | None = None
    on_failure_task: str | None = None
    command: str | None = None  # for shell provider
    timeout_seconds: int | None = None


@dataclass
class WorkflowDefaults:
    on_failure: FailurePolicy = FailurePolicy.RETRY
    max_retries: int = 1


@dataclass
class Workflow:
    name: str
    agents: dict[str, AgentDef]
    tasks: list[TaskDef]
    cwd: str | None = None
    max_parallel: int = 2
    defaults: WorkflowDefaults = field(default_factory=WorkflowDefaults)
    source_path: str | None = None

    def task_by_id(self, task_id: str) -> TaskDef:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(f"Unknown task: {task_id}")

    def agent_for(self, task: TaskDef) -> AgentDef:
        if task.agent not in self.agents:
            raise KeyError(f"Task {task.id} references unknown agent: {task.agent}")
        return self.agents[task.agent]


@dataclass
class AgentResult:
    status: TaskStatus
    summary: str
    raw_output: str = ""
    exit_code: int = 0
    agent_id: str | None = None
    run_id: str | None = None


@dataclass
class TaskRunSpec:
    task: TaskDef
    agent: AgentDef
    prompt: str
    cwd: str
    env: dict[str, str] = field(default_factory=dict)
    log_path: str | None = None


@dataclass
class TaskState:
    id: str
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    summary: str = ""
    output: str = ""
    exit_code: int | None = None
    agent_id: str | None = None
    provider_run_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "attempts": self.attempts,
            "summary": self.summary,
            "output": self.output,
            "exit_code": self.exit_code,
            "agent_id": self.agent_id,
            "provider_run_id": self.provider_run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        return cls(
            id=data["id"],
            status=TaskStatus(data["status"]),
            attempts=data.get("attempts", 0),
            summary=data.get("summary", ""),
            output=data.get("output", ""),
            exit_code=data.get("exit_code"),
            agent_id=data.get("agent_id"),
            provider_run_id=data.get("provider_run_id"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            error=data.get("error"),
        )


@dataclass
class RunState:
    run_id: str
    workflow_name: str
    workflow_path: str
    cwd: str
    status: RunStatus = RunStatus.PENDING
    max_parallel: int = 2
    tasks: dict[str, TaskState] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "workflow_path": self.workflow_path,
            "cwd": self.cwd,
            "status": self.status.value,
            "max_parallel": self.max_parallel,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        tasks = {
            k: TaskState.from_dict(v) for k, v in data.get("tasks", {}).items()
        }
        return cls(
            run_id=data["run_id"],
            workflow_name=data["workflow_name"],
            workflow_path=data["workflow_path"],
            cwd=data["cwd"],
            status=RunStatus(data.get("status", "pending")),
            max_parallel=data.get("max_parallel", 2),
            tasks=tasks,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            error=data.get("error"),
        )
