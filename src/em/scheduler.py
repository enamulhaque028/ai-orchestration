"""DAG scheduler: launch ready tasks, respect deps, retry, resume, approvals."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from em.adapters.registry import get_adapter
from em.models import (
    AgentResult,
    FailurePolicy,
    RunState,
    RunStatus,
    TaskDef,
    TaskRunSpec,
    TaskState,
    TaskStatus,
    TaskWhen,
    Workflow,
)
from em.notify import Notifier
from em.notify.asks import (
    EM_ASK_INSTRUCTIONS,
    HumanAsk,
    clear_ask_files,
    parse_em_ask,
    read_reply,
    write_ask,
)
from em.state import StateStore, utc_now
from em.workflow import render_prompt

StatusCallback = Callable[[RunState], Awaitable[None] | None]


class Scheduler:
    def __init__(
        self,
        workflow: Workflow,
        store: StateStore,
        *,
        on_update: StatusCallback | None = None,
        adapter_overrides: dict[str, Any] | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.workflow = workflow
        self.store = store
        self.on_update = on_update
        self.adapter_overrides = adapter_overrides or {}
        self.notifier = notifier if notifier is not None else Notifier()
        self._cancel = asyncio.Event()
        self._lock = asyncio.Lock()

    def request_cancel(self) -> None:
        self._cancel.set()

    async def run(self, state: RunState) -> RunState:
        state.status = RunStatus.RUNNING
        await self._persist(state)

        in_flight: dict[str, asyncio.Task[None]] = {}

        try:
            while True:
                if self._cancel.is_set():
                    self.store.mark_cancelled(state)
                    await self._notify(state)
                    self.notifier.run_completed(state)
                    return state

                async with self._lock:
                    self._evaluate_readiness(state)
                    ready = [
                        tid
                        for tid, ts in state.tasks.items()
                        if ts.status == TaskStatus.READY
                    ]
                    slots = self.workflow.max_parallel - len(in_flight)
                    to_start = ready[: max(0, slots)]

                    for tid in to_start:
                        task = self.workflow.task_by_id(tid)
                        if task.requires_approval:
                            state.tasks[tid].status = TaskStatus.WAITING_APPROVAL
                            state.tasks[tid].started_at = utc_now()
                            in_flight[tid] = asyncio.create_task(
                                self._await_approval_then_execute(state, tid),
                                name=f"approve:{tid}",
                            )
                        else:
                            state.tasks[tid].status = TaskStatus.RUNNING
                            state.tasks[tid].started_at = utc_now()
                            state.tasks[tid].attempts += 1
                            in_flight[tid] = asyncio.create_task(
                                self._execute_task(state, tid),
                                name=f"task:{tid}",
                            )

                    await self._persist(state)

                active = (
                    TaskStatus.PENDING,
                    TaskStatus.READY,
                    TaskStatus.WAITING_APPROVAL,
                    TaskStatus.WAITING_HUMAN,
                    TaskStatus.RUNNING,
                )
                if not in_flight and not any(
                    t.status in active for t in state.tasks.values()
                ):
                    break

                if not in_flight:
                    async with self._lock:
                        for tid, ts in state.tasks.items():
                            if ts.status == TaskStatus.PENDING:
                                ts.status = TaskStatus.SKIPPED
                                ts.summary = "Skipped: prerequisites not met"
                                ts.finished_at = utc_now()
                                self.notifier.task_completed(state, ts)
                        await self._persist(state)
                    break

                done, _ = await asyncio.wait(
                    in_flight.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=0.5,
                )
                for finished in done:
                    finished_ids = [
                        tid for tid, t in in_flight.items() if t is finished
                    ]
                    for tid in finished_ids:
                        del in_flight[tid]
                    exc = finished.exception()
                    if exc is not None:
                        async with self._lock:
                            state.error = str(exc)
                            await self._persist(state)

            async with self._lock:
                if self._cancel.is_set():
                    self.store.mark_cancelled(state)
                else:
                    failed = [
                        t
                        for t in state.tasks.values()
                        if t.status == TaskStatus.FAILED
                    ]
                    if failed:
                        state.status = RunStatus.FAILED
                        state.error = (
                            "Failed tasks: " + ", ".join(t.id for t in failed)
                        )
                    else:
                        state.status = RunStatus.SUCCEEDED
                        state.error = None
                await self._persist(state)
            self.notifier.run_completed(state)
            return state
        finally:
            for t in in_flight.values():
                if not t.done():
                    t.cancel()
            if in_flight:
                await asyncio.gather(*in_flight.values(), return_exceptions=True)

    def _evaluate_readiness(self, state: RunState) -> None:
        for task in self.workflow.tasks:
            ts = state.tasks[task.id]
            if ts.status != TaskStatus.PENDING:
                continue

            if not self._deps_settled(state, task):
                continue

            if not self._when_allows(state, task):
                ts.status = TaskStatus.SKIPPED
                ts.summary = f"Skipped: when={task.when.value}"
                ts.finished_at = utc_now()
                self.notifier.task_completed(state, ts)
                continue

            if not self._deps_ok_for_start(state, task):
                if self._any_dep_failed(state, task) and task.when == TaskWhen.ALWAYS:
                    ts.status = TaskStatus.SKIPPED
                    ts.summary = "Skipped: dependency failed"
                    ts.finished_at = utc_now()
                    self.notifier.task_completed(state, ts)
                continue

            ts.status = TaskStatus.READY

    def _deps_settled(self, state: RunState, task: TaskDef) -> bool:
        terminal = {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.SKIPPED,
            TaskStatus.CANCELLED,
        }
        for dep in task.depends_on:
            if state.tasks[dep].status not in terminal:
                return False
        return True

    def _deps_ok_for_start(self, state: RunState, task: TaskDef) -> bool:
        if task.when == TaskWhen.ON_UPSTREAM_FAILURE:
            return self._any_dep_failed(state, task)
        if task.when == TaskWhen.ON_UPSTREAM_SUCCESS:
            return (
                all(
                    state.tasks[d].status == TaskStatus.SUCCEEDED
                    for d in task.depends_on
                )
                if task.depends_on
                else True
            )
        for dep in task.depends_on:
            st = state.tasks[dep].status
            if st == TaskStatus.FAILED:
                return False
            if st not in (TaskStatus.SUCCEEDED, TaskStatus.SKIPPED):
                return False
        return True

    def _any_dep_failed(self, state: RunState, task: TaskDef) -> bool:
        return any(
            state.tasks[d].status == TaskStatus.FAILED for d in task.depends_on
        )

    def _when_allows(self, state: RunState, task: TaskDef) -> bool:
        if task.when == TaskWhen.ALWAYS:
            return True
        if task.when == TaskWhen.ON_UPSTREAM_FAILURE:
            return self._any_dep_failed(state, task)
        if task.when == TaskWhen.ON_UPSTREAM_SUCCESS:
            if not task.depends_on:
                return True
            return all(
                state.tasks[d].status == TaskStatus.SUCCEEDED for d in task.depends_on
            )
        return True

    async def _await_approval_then_execute(
        self, state: RunState, task_id: str
    ) -> None:
        clear_ask_files(self.store.root, state.run_id, task_id)
        ask = HumanAsk(
            type="confirm",
            question=f"Approve running task `{task_id}`?",
            source="yaml",
        )
        write_ask(self.store.root, state.run_id, task_id, ask)
        self.notifier.human_ask(state, task_id, ask)
        await self._persist(state)

        reply = await self._wait_for_human_reply(state, task_id, ask)
        if reply is None:
            return
        if reply.kind == "approve":
            async with self._lock:
                state.tasks[task_id].status = TaskStatus.RUNNING
                state.tasks[task_id].attempts += 1
                state.tasks[task_id].summary = f"Approved ({reply.source})"
                await self._persist(state)
            await self._execute_task(state, task_id)
            return
        async with self._lock:
            ts = state.tasks[task_id]
            ts.status = TaskStatus.FAILED
            ts.finished_at = utc_now()
            ts.summary = (
                f"Rejected by human ({reply.source})"
                + (f": {reply.answer}" if reply.answer else "")
            )
            ts.error = ts.summary
            await self._persist(state)
            self.notifier.task_completed(state, ts)

    async def _wait_for_human_reply(self, state: RunState, task_id: str, ask: HumanAsk):
        tg_offset: int | None = None
        while not self._cancel.is_set():
            reply = read_reply(self.store.root, state.run_id, task_id)
            if reply is None and self.notifier.telegram_ready:
                reply, tg_offset = await asyncio.to_thread(
                    self.notifier.poll_telegram_reply,
                    state_root=self.store.root,
                    run_id=state.run_id,
                    task_id=task_id,
                    ask=ask,
                    offset=tg_offset,
                )
            if reply is not None:
                return reply
            await asyncio.sleep(0.5)

        async with self._lock:
            ts = state.tasks[task_id]
            if ts.status in (
                TaskStatus.WAITING_APPROVAL,
                TaskStatus.WAITING_HUMAN,
            ):
                ts.status = TaskStatus.CANCELLED
                ts.finished_at = utc_now()
                ts.summary = "Cancelled while waiting for human"
                await self._persist(state)
                self.notifier.task_completed(state, ts)
        return None

    async def _await_human_ask_then_resume(
        self, state: RunState, task_id: str, ask: HumanAsk
    ) -> None:
        """Pause after agent raised EM_ASK; on answer, re-run the task with context."""
        clear_ask_files(self.store.root, state.run_id, task_id)
        write_ask(self.store.root, state.run_id, task_id, ask)
        async with self._lock:
            ts = state.tasks[task_id]
            ts.status = TaskStatus.WAITING_HUMAN
            ts.finished_at = None
            ts.summary = f"Waiting for human ({ask.type}): {ask.question}"
            await self._persist(state)
        self.notifier.human_ask(state, task_id, ask)

        reply = await self._wait_for_human_reply(state, task_id, ask)
        if reply is None:
            return
        if reply.kind == "reject":
            async with self._lock:
                ts = state.tasks[task_id]
                ts.status = TaskStatus.FAILED
                ts.finished_at = utc_now()
                ts.summary = f"Human rejected ask ({reply.source}): {ask.question}"
                ts.error = ts.summary
                await self._persist(state)
                self.notifier.task_completed(state, ts)
            return

        answer = reply.answer if reply.kind == "answer" else "approved"
        async with self._lock:
            ts = state.tasks[task_id]
            ts.human_answer = answer
            ts.status = TaskStatus.RUNNING
            ts.attempts += 1
            ts.summary = f"Resuming with human answer ({reply.source})"
            await self._persist(state)
        clear_ask_files(self.store.root, state.run_id, task_id)
        await self._execute_task(state, task_id)

    async def _execute_task(self, state: RunState, task_id: str) -> None:
        task = self.workflow.task_by_id(task_id)
        agent = self.workflow.agent_for(task)
        ts = state.tasks[task_id]

        outputs = {tid: t.output for tid, t in state.tasks.items()}
        summaries = {tid: t.summary for tid, t in state.tasks.items()}
        prompt = render_prompt(
            task.prompt,
            cwd=state.cwd,
            workflow_name=self.workflow.name,
            task_outputs=outputs,
            task_summaries=summaries,
            upstream_ids=task.depends_on,
        )
        if ts.human_answer:
            prompt += (
                "\n\n---\nHuman operator response to your previous question:\n"
                f"{ts.human_answer}\n"
                "Continue the task using this answer. Do not ask the same question again "
                "unless you still lack required information.\n"
            )
        # Teach agents how to raise asks (skip for pure shell commands with empty prompts)
        if task.prompt.strip() and agent.provider != "shell":
            prompt = f"{prompt.rstrip()}\n\n{EM_ASK_INSTRUCTIONS}\n"

        log_path = str(self.store.log_path(state.run_id, task_id))
        spec = TaskRunSpec(
            task=task,
            agent=agent,
            prompt=prompt,
            cwd=state.cwd,
            log_path=log_path,
        )

        adapter = self.adapter_overrides.get(agent.provider) or get_adapter(
            agent.provider
        )

        try:
            result: AgentResult = await adapter.run(spec)
        except Exception as exc:  # noqa: BLE001
            result = AgentResult(
                status=TaskStatus.FAILED,
                summary=str(exc),
                raw_output=str(exc),
                exit_code=1,
            )

        # Agent-raised human ask (even on "success")
        ask = parse_em_ask(f"{result.summary}\n{result.raw_output}")
        if ask is not None and result.status == TaskStatus.SUCCEEDED:
            async with self._lock:
                ts = state.tasks[task_id]
                ts.summary = result.summary
                ts.output = result.raw_output
                ts.exit_code = result.exit_code
                await self._persist(state)
            await self._await_human_ask_then_resume(state, task_id, ask)
            return

        async with self._lock:
            ts = state.tasks[task_id]
            ts.finished_at = utc_now()
            ts.summary = result.summary
            ts.output = result.raw_output
            ts.exit_code = result.exit_code
            ts.agent_id = result.agent_id
            ts.provider_run_id = result.run_id

            if result.status == TaskStatus.SUCCEEDED:
                ts.status = TaskStatus.SUCCEEDED
                ts.error = None
                ts.human_answer = None  # consumed
            else:
                await self._handle_failure(state, task, ts, result)

            if ts.status in (
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.SKIPPED,
                TaskStatus.CANCELLED,
            ):
                self.notifier.task_completed(state, ts)

            await self._persist(state)

    async def _handle_failure(
        self,
        state: RunState,
        task: TaskDef,
        ts: TaskState,
        result: AgentResult,
    ) -> None:
        policy = task.on_failure or self.workflow.defaults.on_failure
        max_retries = (
            task.max_retries
            if task.max_retries is not None
            else self.workflow.defaults.max_retries
        )
        ts.error = result.summary or f"exit={result.exit_code}"

        if policy == FailurePolicy.RETRY and ts.attempts <= max_retries:
            ts.status = TaskStatus.PENDING
            ts.finished_at = None
            ts.summary = (
                f"Retrying after failure (attempt {ts.attempts}/{max_retries})"
            )
            return

        if policy == FailurePolicy.SKIP:
            ts.status = TaskStatus.SKIPPED
            ts.summary = f"Skipped after failure: {ts.error}"
            return

        ts.status = TaskStatus.FAILED

        if task.on_failure_task:
            recovery = state.tasks.get(task.on_failure_task)
            if recovery and recovery.status == TaskStatus.SKIPPED:
                recovery.status = TaskStatus.PENDING
                recovery.finished_at = None

    async def _persist(self, state: RunState) -> None:
        self.store.save(state)
        await self._notify(state)

    async def _notify(self, state: RunState) -> None:
        if not self.on_update:
            return
        result = self.on_update(state)
        if asyncio.iscoroutine(result):
            await result
