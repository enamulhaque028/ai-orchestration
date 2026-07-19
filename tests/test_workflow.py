"""Tests for workflow loading and DAG validation."""

from pathlib import Path

import pytest
import yaml

from em.models import TaskWhen
from em.workflow import WorkflowError, load_workflow, parse_workflow, render_prompt


def test_parse_minimal_workflow():
    wf = parse_workflow(
        {
            "name": "demo",
            "agents": {"dev": {"provider": "mock"}},
            "tasks": [{"id": "a", "agent": "dev", "prompt": "do it"}],
        }
    )
    assert wf.name == "demo"
    assert wf.tasks[0].id == "a"
    assert wf.max_parallel == 2


def test_unknown_agent():
    with pytest.raises(WorkflowError, match="unknown agent"):
        parse_workflow(
            {
                "name": "demo",
                "agents": {"dev": {"provider": "mock"}},
                "tasks": [{"id": "a", "agent": "missing", "prompt": "x"}],
            }
        )


def test_unknown_dependency():
    with pytest.raises(WorkflowError, match="unknown task"):
        parse_workflow(
            {
                "name": "demo",
                "agents": {"dev": {"provider": "mock"}},
                "tasks": [
                    {
                        "id": "a",
                        "agent": "dev",
                        "prompt": "x",
                        "depends_on": ["nope"],
                    }
                ],
            }
        )


def test_cycle_detection():
    with pytest.raises(WorkflowError, match="Cycle"):
        parse_workflow(
            {
                "name": "demo",
                "agents": {"dev": {"provider": "mock"}},
                "tasks": [
                    {
                        "id": "a",
                        "agent": "dev",
                        "prompt": "x",
                        "depends_on": ["b"],
                    },
                    {
                        "id": "b",
                        "agent": "dev",
                        "prompt": "x",
                        "depends_on": ["a"],
                    },
                ],
            }
        )


def test_duplicate_task_id():
    with pytest.raises(WorkflowError, match="Duplicate"):
        parse_workflow(
            {
                "name": "demo",
                "agents": {"dev": {"provider": "mock"}},
                "tasks": [
                    {"id": "a", "agent": "dev", "prompt": "1"},
                    {"id": "a", "agent": "dev", "prompt": "2"},
                ],
            }
        )


def test_when_and_failure_policy():
    wf = parse_workflow(
        {
            "name": "demo",
            "agents": {"dev": {"provider": "mock"}},
            "tasks": [
                {
                    "id": "a",
                    "agent": "dev",
                    "prompt": "x",
                    "when": "on_upstream_failure",
                    "on_failure": "skip",
                    "max_retries": 0,
                }
            ],
        }
    )
    assert wf.tasks[0].when == TaskWhen.ON_UPSTREAM_FAILURE
    assert wf.tasks[0].on_failure.value == "skip"
    assert wf.tasks[0].max_retries == 0


def test_load_starter_workflow(tmp_path: Path):
    from em.cli import STARTER_WORKFLOW

    path = tmp_path / "workflow.yaml"
    path.write_text(STARTER_WORKFLOW, encoding="utf-8")
    wf = load_workflow(path)
    assert wf.name == "add-checkout-flow-real"
    assert len(wf.tasks) == 4
    fix = wf.task_by_id("fix-failures")
    assert fix.when == TaskWhen.ON_UPSTREAM_FAILURE
    assert fix.depends_on == ["write-tests"]


def test_render_prompt():
    text = render_prompt(
        "cwd={{cwd}} wf={{workflow.name}} up={{upstream.summary}} out={{task.a.output}}",
        cwd="/repo",
        workflow_name="demo",
        task_outputs={"a": "done"},
        task_summaries={"a": "ok"},
        upstream_ids=["a"],
    )
    assert "/repo" in text
    assert "demo" in text
    assert "ok" in text
    assert "done" in text


def test_load_missing_file(tmp_path: Path):
    with pytest.raises(WorkflowError, match="not found"):
        load_workflow(tmp_path / "missing.yaml")


def test_yaml_roundtrip(tmp_path: Path):
    data = {
        "name": "rt",
        "agents": {"s": {"provider": "shell", "command": "echo hi"}},
        "tasks": [{"id": "t", "agent": "s", "prompt": "p", "command": "echo hi"}],
    }
    path = tmp_path / "w.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    wf = load_workflow(path)
    assert wf.agents["s"].provider == "shell"
    assert wf.tasks[0].command == "echo hi"
