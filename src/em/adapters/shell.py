"""Shell / arbitrary command adapter."""

from __future__ import annotations

import shlex

from em.adapters.base import run_subprocess
from em.models import AgentResult, TaskRunSpec, TaskStatus


class ShellAdapter:
    async def run(self, spec: TaskRunSpec) -> AgentResult:
        command = spec.task.command or spec.agent.extra.get("command")
        if not command:
            return AgentResult(
                status=TaskStatus.FAILED,
                summary="Shell agent requires task.command or agent.command",
                exit_code=1,
            )

        # Allow {{prompt}} substitution for wrapping custom CLIs
        rendered = str(command).replace("{{prompt}}", spec.prompt)
        cmd = shlex.split(rendered) if isinstance(rendered, str) else list(rendered)

        return await run_subprocess(
            cmd,
            cwd=spec.cwd,
            env=spec.env or None,
            log_path=spec.log_path,
            timeout_seconds=spec.task.timeout_seconds
            or spec.agent.extra.get("timeout_seconds"),
        )
