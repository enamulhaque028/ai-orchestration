"""Load and validate workflow YAML definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from em.models import (
    AgentDef,
    FailurePolicy,
    TaskDef,
    TaskWhen,
    Workflow,
    WorkflowDefaults,
)


class WorkflowError(ValueError):
    """Invalid workflow definition."""


def load_workflow(path: str | Path) -> Workflow:
    path = Path(path).resolve()
    if not path.is_file():
        raise WorkflowError(f"Workflow file not found: {path}")

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise WorkflowError("Workflow root must be a mapping")

    return parse_workflow(data, source_path=str(path))


def parse_workflow(data: dict[str, Any], source_path: str | None = None) -> Workflow:
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise WorkflowError("Workflow requires a string 'name'")

    defaults_raw = data.get("defaults") or {}
    defaults = WorkflowDefaults(
        on_failure=_parse_failure_policy(
            defaults_raw.get("on_failure", FailurePolicy.RETRY.value)
        ),
        max_retries=int(defaults_raw.get("max_retries", 1)),
    )

    agents_raw = data.get("agents") or {}
    if not isinstance(agents_raw, dict) or not agents_raw:
        raise WorkflowError("Workflow requires a non-empty 'agents' mapping")

    agents: dict[str, AgentDef] = {}
    for agent_name, agent_data in agents_raw.items():
        if not isinstance(agent_data, dict):
            raise WorkflowError(f"Agent '{agent_name}' must be a mapping")
        provider = agent_data.get("provider")
        if not provider:
            raise WorkflowError(f"Agent '{agent_name}' requires 'provider'")
        known = {"provider", "model"}
        extra = {k: v for k, v in agent_data.items() if k not in known}
        agents[agent_name] = AgentDef(
            name=agent_name,
            provider=str(provider).lower(),
            model=agent_data.get("model"),
            extra=extra,
        )

    tasks_raw = data.get("tasks") or []
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise WorkflowError("Workflow requires a non-empty 'tasks' list")

    tasks: list[TaskDef] = []
    seen_ids: set[str] = set()
    for i, task_data in enumerate(tasks_raw):
        if not isinstance(task_data, dict):
            raise WorkflowError(f"Task at index {i} must be a mapping")
        task_id = task_data.get("id")
        if not task_id or not isinstance(task_id, str):
            raise WorkflowError(f"Task at index {i} requires string 'id'")
        if task_id in seen_ids:
            raise WorkflowError(f"Duplicate task id: {task_id}")
        seen_ids.add(task_id)

        agent_name = task_data.get("agent")
        if not agent_name:
            raise WorkflowError(f"Task '{task_id}' requires 'agent'")
        if agent_name not in agents:
            raise WorkflowError(
                f"Task '{task_id}' references unknown agent '{agent_name}'"
            )

        prompt = task_data.get("prompt", "")
        if prompt is None:
            prompt = ""
        prompt = str(prompt)

        depends_on = task_data.get("depends_on") or []
        if not isinstance(depends_on, list):
            raise WorkflowError(f"Task '{task_id}' depends_on must be a list")
        depends_on = [str(d) for d in depends_on]

        when = _parse_when(task_data.get("when", TaskWhen.ALWAYS.value))
        on_failure = None
        if "on_failure" in task_data and task_data["on_failure"] is not None:
            on_failure = _parse_failure_policy(task_data["on_failure"])
        max_retries = None
        if "max_retries" in task_data and task_data["max_retries"] is not None:
            max_retries = int(task_data["max_retries"])

        tasks.append(
            TaskDef(
                id=task_id,
                agent=str(agent_name),
                prompt=prompt,
                depends_on=depends_on,
                when=when,
                on_failure=on_failure,
                max_retries=max_retries,
                on_failure_task=task_data.get("on_failure_task"),
                command=task_data.get("command"),
                timeout_seconds=(
                    int(task_data["timeout_seconds"])
                    if task_data.get("timeout_seconds") is not None
                    else None
                ),
            )
        )

    _validate_dag(tasks)

    max_parallel = int(data.get("max_parallel", 2))
    if max_parallel < 1:
        raise WorkflowError("max_parallel must be >= 1")

    cwd = data.get("cwd")
    if cwd is not None:
        cwd = str(cwd)

    return Workflow(
        name=name,
        agents=agents,
        tasks=tasks,
        cwd=cwd,
        max_parallel=max_parallel,
        defaults=defaults,
        source_path=source_path,
    )


def _parse_failure_policy(value: Any) -> FailurePolicy:
    try:
        return FailurePolicy(str(value).lower())
    except ValueError as e:
        raise WorkflowError(
            f"Invalid on_failure '{value}'. Expected: retry, fail, skip"
        ) from e


def _parse_when(value: Any) -> TaskWhen:
    try:
        return TaskWhen(str(value).lower())
    except ValueError as e:
        raise WorkflowError(
            f"Invalid when '{value}'. Expected: always, on_upstream_failure, "
            "on_upstream_success"
        ) from e


def _validate_dag(tasks: list[TaskDef]) -> None:
    ids = {t.id for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            if dep not in ids:
                raise WorkflowError(
                    f"Task '{task.id}' depends on unknown task '{dep}'"
                )
        if task.on_failure_task and task.on_failure_task not in ids:
            raise WorkflowError(
                f"Task '{task.id}' on_failure_task references unknown "
                f"task '{task.on_failure_task}'"
            )

    # Cycle detection via DFS
    adj: dict[str, list[str]] = {t.id: list(t.depends_on) for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in ids}

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GRAY
        stack.append(node)
        for dep in adj[node]:
            if color[dep] == GRAY:
                cycle_start = stack.index(dep)
                cycle = " -> ".join(stack[cycle_start:] + [dep])
                raise WorkflowError(f"Cycle detected in task dependencies: {cycle}")
            if color[dep] == WHITE:
                visit(dep, stack)
        stack.pop()
        color[node] = BLACK

    for tid in ids:
        if color[tid] == WHITE:
            visit(tid, [])


def render_prompt(
    template: str,
    *,
    cwd: str,
    workflow_name: str,
    task_outputs: dict[str, str],
    task_summaries: dict[str, str],
    upstream_ids: list[str],
) -> str:
    """Expand {{cwd}}, {{workflow.name}}, {{upstream.summary}}, {{task.<id>.output}}."""
    upstream_summaries = [
        task_summaries[uid]
        for uid in upstream_ids
        if uid in task_summaries and task_summaries[uid]
    ]
    upstream_summary = "\n\n".join(upstream_summaries)

    result = template.replace("{{cwd}}", cwd)
    result = result.replace("{{workflow.name}}", workflow_name)
    result = result.replace("{{upstream.summary}}", upstream_summary)

    for tid, output in task_outputs.items():
        result = result.replace(f"{{{{task.{tid}.output}}}}", output)
        result = result.replace(
            f"{{{{task.{tid}.summary}}}}", task_summaries.get(tid, "")
        )

    return result
