"""Tests for DAG scheduling, parallelism, retries, and recovery."""

import asyncio

import pytest

from em.adapters.mock import MockAdapter
from em.models import RunStatus, TaskStatus
from em.scheduler import Scheduler
from em.state import StateStore
from em.workflow import parse_workflow


@pytest.mark.asyncio
async def test_parallel_independent_tasks(tmp_path):
    wf = parse_workflow(
        {
            "name": "par",
            "max_parallel": 2,
            "agents": {
                "a": {"provider": "mock", "mock_delay": 0.05},
                "b": {"provider": "mock", "mock_delay": 0.05},
            },
            "tasks": [
                {"id": "t1", "agent": "a", "prompt": "one"},
                {"id": "t2", "agent": "b", "prompt": "two"},
            ],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    mock = MockAdapter(delay=0.05)
    sched = Scheduler(
        wf, store, adapter_overrides={"mock": mock}
    )
    final = await sched.run(state)
    assert final.status == RunStatus.SUCCEEDED
    assert final.tasks["t1"].status == TaskStatus.SUCCEEDED
    assert final.tasks["t2"].status == TaskStatus.SUCCEEDED
    assert set(mock.calls) == {"t1", "t2"}


@pytest.mark.asyncio
async def test_dependency_order(tmp_path):
    order: list[str] = []

    class OrderMock(MockAdapter):
        async def run(self, spec):
            order.append(spec.task.id)
            return await super().run(spec)

    wf = parse_workflow(
        {
            "name": "dep",
            "agents": {"d": {"provider": "mock"}},
            "tasks": [
                {"id": "first", "agent": "d", "prompt": "a"},
                {
                    "id": "second",
                    "agent": "d",
                    "prompt": "b",
                    "depends_on": ["first"],
                },
            ],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    mock = OrderMock(delay=0.01)
    final = await Scheduler(
        wf, store, adapter_overrides={"mock": mock}
    ).run(state)
    assert final.status == RunStatus.SUCCEEDED
    assert order == ["first", "second"]


@pytest.mark.asyncio
async def test_retry_then_succeed(tmp_path):
    class Flaky(MockAdapter):
        async def run(self, spec):
            self.calls.append(spec.task.id)
            if self.calls.count(spec.task.id) == 1:
                from em.models import AgentResult

                return AgentResult(
                    status=TaskStatus.FAILED,
                    summary="first fail",
                    exit_code=1,
                )
            return await super().run(spec)

    wf = parse_workflow(
        {
            "name": "retry",
            "defaults": {"on_failure": "retry", "max_retries": 1},
            "agents": {"d": {"provider": "mock"}},
            "tasks": [{"id": "t", "agent": "d", "prompt": "x"}],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    final = await Scheduler(
        wf, store, adapter_overrides={"mock": Flaky()}
    ).run(state)
    assert final.status == RunStatus.SUCCEEDED
    assert final.tasks["t"].attempts == 2


@pytest.mark.asyncio
async def test_on_upstream_failure_recovery(tmp_path):
    wf = parse_workflow(
        {
            "name": "recover",
            "defaults": {"on_failure": "fail", "max_retries": 0},
            "agents": {
                "qa": {"provider": "mock", "mock_fail_ids": ["qa"]},
                "fix": {"provider": "mock"},
            },
            "tasks": [
                {"id": "qa", "agent": "qa", "prompt": "test"},
                {
                    "id": "fix",
                    "agent": "fix",
                    "prompt": "fix {{upstream.summary}}",
                    "depends_on": ["qa"],
                    "when": "on_upstream_failure",
                },
            ],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    final = await Scheduler(
        wf, store, adapter_overrides={"mock": MockAdapter()}
    ).run(state)
    assert final.tasks["qa"].status == TaskStatus.FAILED
    assert final.tasks["fix"].status == TaskStatus.SUCCEEDED
    # Overall still failed because qa failed
    assert final.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_skip_recovery_when_upstream_ok(tmp_path):
    wf = parse_workflow(
        {
            "name": "skip-fix",
            "agents": {"d": {"provider": "mock"}},
            "tasks": [
                {"id": "qa", "agent": "d", "prompt": "ok"},
                {
                    "id": "fix",
                    "agent": "d",
                    "prompt": "fix",
                    "depends_on": ["qa"],
                    "when": "on_upstream_failure",
                },
            ],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    final = await Scheduler(
        wf, store, adapter_overrides={"mock": MockAdapter()}
    ).run(state)
    assert final.status == RunStatus.SUCCEEDED
    assert final.tasks["qa"].status == TaskStatus.SUCCEEDED
    assert final.tasks["fix"].status == TaskStatus.SKIPPED


@pytest.mark.asyncio
async def test_resume_after_interrupt(tmp_path):
    wf = parse_workflow(
        {
            "name": "resume",
            "agents": {"d": {"provider": "mock"}},
            "tasks": [
                {"id": "a", "agent": "d", "prompt": "a"},
                {"id": "b", "agent": "d", "prompt": "b", "depends_on": ["a"]},
            ],
        }
    )
    path = tmp_path / "w.yaml"
    path.write_text("name: resume\n", encoding="utf-8")
    wf.source_path = str(path)

    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    state.tasks["a"].status = TaskStatus.SUCCEEDED
    state.tasks["a"].summary = "done"
    state.tasks["b"].status = TaskStatus.RUNNING
    state.status = RunStatus.RUNNING
    store.save(state)

    state = store.prepare_for_resume(state)
    final = await Scheduler(
        wf, store, adapter_overrides={"mock": MockAdapter()}
    ).run(state)
    assert final.status == RunStatus.SUCCEEDED
    assert final.tasks["b"].status == TaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_shell_adapter(tmp_path):
    from em.adapters.shell import ShellAdapter
    from em.models import AgentDef, TaskDef, TaskRunSpec

    adapter = ShellAdapter()
    result = await adapter.run(
        TaskRunSpec(
            task=TaskDef(id="echo", agent="s", prompt="hi", command="echo hello-em"),
            agent=AgentDef(name="s", provider="shell"),
            prompt="hi",
            cwd=str(tmp_path),
        )
    )
    assert result.status == TaskStatus.SUCCEEDED
    assert "hello-em" in result.raw_output


@pytest.mark.asyncio
async def test_requires_approval_then_approve(tmp_path):
    from em.config import EmConfig
    from em.notify import Notifier
    from em.notify.approvals import write_decision

    wf = parse_workflow(
        {
            "name": "gate",
            "agents": {"d": {"provider": "mock"}},
            "tasks": [
                {
                    "id": "gated",
                    "agent": "d",
                    "prompt": "go",
                    "requires_approval": True,
                }
            ],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    run_id = state.run_id

    async def approve_soon():
        await asyncio.sleep(0.2)
        write_decision(store.root, run_id, "gated", "approve", source="test")

    notifier = Notifier(EmConfig())  # no telegram
    mock = MockAdapter(delay=0.01)
    sched = Scheduler(
        wf, store, adapter_overrides={"mock": mock}, notifier=notifier
    )
    approve_task = asyncio.create_task(approve_soon())
    final = await sched.run(state)
    await approve_task
    assert final.status == RunStatus.SUCCEEDED
    assert final.tasks["gated"].status == TaskStatus.SUCCEEDED
    assert mock.calls == ["gated"]


@pytest.mark.asyncio
async def test_task_complete_notifier_called(tmp_path):
    from em.config import EmConfig, NotifyConfig
    from em.notify import Notifier

    class RecordingNotifier(Notifier):
        def __init__(self):
            super().__init__(EmConfig(notify=NotifyConfig(on_task_complete=True)))
            self.tasks: list[str] = []
            self.runs: list[str] = []

        def task_completed(self, state, task):
            self.tasks.append(task.id)

        def run_completed(self, state):
            self.runs.append(state.run_id)

    wf = parse_workflow(
        {
            "name": "n",
            "agents": {"d": {"provider": "mock"}},
            "tasks": [{"id": "t1", "agent": "d", "prompt": "x"}],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    rec = RecordingNotifier()
    final = await Scheduler(
        wf, store, adapter_overrides={"mock": MockAdapter(delay=0.01)}, notifier=rec
    ).run(state)
    assert final.status == RunStatus.SUCCEEDED
    assert rec.tasks == ["t1"]
    assert rec.runs == [final.run_id]
