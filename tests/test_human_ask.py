"""Tests for agent-raised EM_ASK parsing and human resume."""

import asyncio

import pytest

from em.adapters.mock import MockAdapter
from em.models import AgentResult, RunStatus, TaskStatus
from em.notify.asks import parse_em_ask
from em.notify.asks import write_reply
from em.config import EmConfig
from em.notify import Notifier
from em.scheduler import Scheduler
from em.state import StateStore
from em.workflow import parse_workflow


def test_parse_em_ask_confirm():
    text = 'Done looking.\nEM_ASK:{"type":"confirm","question":"Deploy now?"}\n'
    ask = parse_em_ask(text)
    assert ask is not None
    assert ask.type == "confirm"
    assert ask.question == "Deploy now?"


def test_parse_em_ask_choice():
    text = (
        'EM_ASK:{"type":"choice","question":"Which API?","options":["REST","GraphQL"]}'
    )
    ask = parse_em_ask(text)
    assert ask is not None
    assert ask.type == "choice"
    assert ask.options == ["REST", "GraphQL"]


def test_parse_em_ask_missing_returns_none():
    assert parse_em_ask("all good, no questions") is None


@pytest.mark.asyncio
async def test_agent_ask_then_answer_resumes(tmp_path):
    class AskingThenOk(MockAdapter):
        def __init__(self) -> None:
            super().__init__(delay=0.01)
            self.n = 0
            self.prompts: list[str] = []

        async def run(self, spec):
            self.n += 1
            self.prompts.append(spec.prompt)
            self.calls.append(spec.task.id)
            if self.n == 1:
                return AgentResult(
                    status=TaskStatus.SUCCEEDED,
                    summary='Need a pick.\nEM_ASK:{"type":"choice","question":"Color?","options":["red","blue"]}',
                    raw_output="asked",
                )
            return AgentResult(
                status=TaskStatus.SUCCEEDED,
                summary=f"mock success using answer",
                raw_output="done",
            )

    wf = parse_workflow(
        {
            "name": "ask",
            "agents": {"d": {"provider": "mock"}},
            "tasks": [{"id": "t1", "agent": "d", "prompt": "build it"}],
        }
    )
    wf.source_path = str(tmp_path / "w.yaml")
    store = StateStore(tmp_path / ".em")
    state = store.create_run(wf, str(tmp_path))
    run_id = state.run_id
    mock = AskingThenOk()

    async def answer_soon():
        await asyncio.sleep(0.25)
        write_reply(store.root, run_id, "t1", "answer", answer="blue", source="test")

    sched = Scheduler(
        wf, store, adapter_overrides={"mock": mock}, notifier=Notifier(EmConfig())
    )
    waiter = asyncio.create_task(answer_soon())
    final = await sched.run(state)
    await waiter

    assert final.status == RunStatus.SUCCEEDED
    assert final.tasks["t1"].status == TaskStatus.SUCCEEDED
    assert mock.n == 2
    assert any("blue" in p for p in mock.prompts)
