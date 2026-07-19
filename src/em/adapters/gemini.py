"""Google Gemini CLI adapter."""

from __future__ import annotations

import os

from em.adapters.base import run_subprocess
from em.models import AgentResult, TaskRunSpec, TaskStatus
from em.platform_paths import which_command


class GeminiAdapter:
    async def run(self, spec: TaskRunSpec) -> AgentResult:
        binary = str(
            spec.agent.extra.get("binary")
            or os.environ.get("EM_GEMINI_BIN")
            or "gemini"
        )
        resolved = binary if os.path.isfile(binary) else which_command(binary)
        if not resolved:
            return AgentResult(
                status=TaskStatus.FAILED,
                summary="gemini CLI not found on PATH. Install Gemini CLI or set EM_GEMINI_BIN.",
                exit_code=127,
            )

        cmd = [resolved, "-p", spec.prompt, "--yolo"]

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
