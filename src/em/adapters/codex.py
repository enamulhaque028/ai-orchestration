"""OpenAI Codex CLI adapter."""

from __future__ import annotations

import os
import shutil

from em.adapters.base import run_subprocess
from em.models import AgentResult, TaskRunSpec, TaskStatus


class CodexAdapter:
    async def run(self, spec: TaskRunSpec) -> AgentResult:
        binary = spec.agent.extra.get("binary") or os.environ.get(
            "EM_CODEX_BIN", "codex"
        )
        if not shutil.which(binary):
            return AgentResult(
                status=TaskStatus.FAILED,
                summary="codex CLI not found on PATH. Install Codex or set EM_CODEX_BIN.",
                exit_code=127,
            )

        # Prefer non-interactive exec; fall back to -p style if configured
        mode = str(spec.agent.extra.get("mode", "exec"))
        if mode == "exec":
            cmd = [binary, "exec", "--full-auto", spec.prompt]
        else:
            cmd = [binary, "--print", spec.prompt]

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
