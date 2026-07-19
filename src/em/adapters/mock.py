"""Mock adapter for tests and dry-runs."""

from __future__ import annotations

import asyncio
from pathlib import Path

from em.models import AgentResult, TaskRunSpec, TaskStatus


class MockAdapter:
    """Deterministic adapter controlled via agent.extra or task prompt markers.

    Agent extra:
      mock_delay: float seconds
      mock_fail: bool
      mock_fail_ids: list of task ids that should fail
    """

    def __init__(
        self,
        *,
        fail_ids: set[str] | None = None,
        delay: float = 0.01,
    ) -> None:
        self.fail_ids = fail_ids or set()
        self.delay = delay
        self.calls: list[str] = []

    async def run(self, spec: TaskRunSpec) -> AgentResult:
        self.calls.append(spec.task.id)
        delay = float(spec.agent.extra.get("mock_delay", self.delay))
        await asyncio.sleep(delay)

        should_fail = (
            bool(spec.agent.extra.get("mock_fail", False))
            or spec.task.id in self.fail_ids
            or spec.task.id in set(spec.agent.extra.get("mock_fail_ids") or [])
            or "{{FAIL}}" in spec.prompt
        )

        text = f"[mock:{spec.agent.provider}] completed {spec.task.id}\n{spec.prompt[:200]}"
        if spec.log_path:
            Path(spec.log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(spec.log_path).write_text(text, encoding="utf-8")

        if should_fail:
            return AgentResult(
                status=TaskStatus.FAILED,
                summary=f"mock failure for {spec.task.id}",
                raw_output=text,
                exit_code=1,
            )
        return AgentResult(
            status=TaskStatus.SUCCEEDED,
            summary=f"mock success for {spec.task.id}",
            raw_output=text,
            exit_code=0,
        )
