"""OpenAI Codex CLI adapter."""

from __future__ import annotations

import os

from em.adapters.base import run_subprocess
from em.models import AgentResult, TaskRunSpec, TaskStatus
from em.platform_paths import which_command


class CodexAdapter:
    async def run(self, spec: TaskRunSpec) -> AgentResult:
        binary = str(
            spec.agent.extra.get("binary") or os.environ.get("EM_CODEX_BIN") or "codex"
        )
        resolved = binary if os.path.isfile(binary) else which_command(binary)
        if not resolved:
            return AgentResult(
                status=TaskStatus.FAILED,
                summary="codex CLI not found on PATH. Install Codex or set EM_CODEX_BIN.",
                exit_code=127,
            )

        mode = str(spec.agent.extra.get("mode", "exec"))
        if mode == "exec":
            cmd = [resolved, "exec", "--full-auto", spec.prompt]
        else:
            cmd = [resolved, "--print", spec.prompt]

        model = spec.agent.model or spec.agent.extra.get("model")
        if model:
            cmd.extend(["--model", str(model)])

        return await run_subprocess(
            cmd,
            cwd=spec.cwd,
            env=spec.env or None,
            log_path=spec.log_path,
            timeout_seconds=spec.task.timeout_seconds
            or spec.agent.extra.get("timeout_seconds"),
        )
