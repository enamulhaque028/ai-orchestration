"""Claude Code CLI adapter (headless --print mode)."""

from __future__ import annotations

import json
import os
import shutil

from em.adapters.base import run_subprocess
from em.models import AgentResult, TaskRunSpec, TaskStatus


class ClaudeAdapter:
    async def run(self, spec: TaskRunSpec) -> AgentResult:
        binary = spec.agent.extra.get("binary") or os.environ.get(
            "EM_CLAUDE_BIN", "claude"
        )
        if not shutil.which(binary) and binary == "claude":
            return AgentResult(
                status=TaskStatus.FAILED,
                summary="claude CLI not found on PATH. Install Claude Code or set EM_CLAUDE_BIN.",
                exit_code=127,
            )

        cmd = [binary, "--print", "--output-format", "json"]

        model = spec.agent.model or spec.agent.extra.get("model")
        if model:
            cmd.extend(["--model", str(model)])

        if spec.agent.extra.get("dangerously_skip_permissions", True):
            cmd.append("--dangerously-skip-permissions")

        allowed = spec.agent.extra.get("allowed_tools")
        if allowed:
            if isinstance(allowed, list):
                cmd.extend(["--allowedTools", ",".join(str(a) for a in allowed)])
            else:
                cmd.extend(["--allowedTools", str(allowed)])

        system_prompt = spec.agent.extra.get("system_prompt")
        if system_prompt:
            cmd.extend(["--system-prompt", str(system_prompt)])

        cmd.append(spec.prompt)

        result = await run_subprocess(
            cmd,
            cwd=spec.cwd,
            env=spec.env or None,
            log_path=spec.log_path,
            timeout_seconds=spec.task.timeout_seconds
            or spec.agent.extra.get("timeout_seconds"),
        )

        if result.raw_output:
            summary = _extract_claude_summary(result.raw_output)
            if summary:
                result.summary = summary
        return result


def _extract_claude_summary(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # stream-json or mixed: try last JSON object line
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            return None

    if not isinstance(data, dict):
        return None

    for key in ("result", "text", "content", "message"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[-2000:]
        if isinstance(val, dict):
            inner = val.get("text") or val.get("content")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()[-2000:]
    return None
