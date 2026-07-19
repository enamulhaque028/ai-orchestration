"""Tests for run state persistence."""

from em.models import RunStatus, TaskStatus
from em.state import StateStore
from em.workflow import parse_workflow


def _wf():
    return parse_workflow(
        {
            "name": "demo",
            "agents": {"dev": {"provider": "mock"}},
            "tasks": [
                {"id": "a", "agent": "dev", "prompt": "x"},
                {"id": "b", "agent": "dev", "prompt": "y", "depends_on": ["a"]},
            ],
        }
    )


def test_create_save_load(tmp_path):
    store = StateStore(tmp_path / ".em")
    wf = _wf()
    wf.source_path = "/tmp/w.yaml"
    state = store.create_run(wf, str(tmp_path))
    assert state.run_id.startswith("run_")
    assert store.latest_run_id() == state.run_id

    state.tasks["a"].status = TaskStatus.SUCCEEDED
    store.save(state)

    loaded = store.load(state.run_id)
    assert loaded.tasks["a"].status == TaskStatus.SUCCEEDED
    assert loaded.workflow_name == "demo"


def test_prepare_for_resume(tmp_path):
    store = StateStore(tmp_path / ".em")
    state = store.create_run(_wf(), str(tmp_path))
    state.status = RunStatus.RUNNING
    state.tasks["a"].status = TaskStatus.RUNNING
    state.tasks["b"].status = TaskStatus.READY
    store.save(state)

    resumed = store.prepare_for_resume(state)
    assert resumed.tasks["a"].status == TaskStatus.PENDING
    assert resumed.tasks["b"].status == TaskStatus.PENDING
    assert resumed.status == RunStatus.PENDING


def test_mark_cancelled(tmp_path):
    store = StateStore(tmp_path / ".em")
    state = store.create_run(_wf(), str(tmp_path))
    state.tasks["a"].status = TaskStatus.RUNNING
    store.mark_cancelled(state)
    assert state.status == RunStatus.CANCELLED
    assert state.tasks["a"].status == TaskStatus.CANCELLED
    assert state.tasks["b"].status == TaskStatus.CANCELLED
