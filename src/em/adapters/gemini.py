"""Google Gemini CLI adapter."""

from __future__ import annotations

import os
import shutil

from em.adapters.base import run_subprocess
from em.models import AgentResult, TaskRunSpec, TaskStatus


class GeminiAdapter:
    async def run(self, spec: TaskRunSpec) -> AgentResult:
        binary = spec.agent.extra.get("binary") or os.environ.get(
            "EM_GEMINI_BIN", "gemini"
        )
        if not shutil.which(binary):
            return AgentResult(
                status=TaskStatus.FAILED,
                summary="gemini CLI not found on PATH. Install Gemini CLI or set EM_GEMINI_BIN.",
                exit_code=127,
            )

        cmd = [binary, "-p", spec.prompt, "--yolo"]

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
