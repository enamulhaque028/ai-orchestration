"""Adapter protocol and shared helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from em.models import AgentResult, TaskRunSpec, TaskStatus


class AgentAdapter(Protocol):
    async def run(self, spec: TaskRunSpec) -> AgentResult: ...


async def run_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
    log_path: str | None = None,
    timeout_seconds: int | None = None,
) -> AgentResult:
    """Run a CLI agent and capture output."""
    import os

    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=full_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        binary = cmd[0] if cmd else "command"
        return AgentResult(
            status=TaskStatus.FAILED,
            summary=f"Command not found: {binary}",
            raw_output="",
            exit_code=127,
        )

    try:
        if timeout_seconds:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        else:
            stdout, _ = await proc.communicate()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        msg = f"Timed out after {timeout_seconds}s"
        if log_path:
            Path(log_path).write_text(msg, encoding="utf-8")
        return AgentResult(
            status=TaskStatus.FAILED,
            summary=msg,
            raw_output=msg,
            exit_code=124,
        )

    raw = (stdout or b"").decode("utf-8", errors="replace")
    if log_path:
        Path(log_path).write_text(raw, encoding="utf-8")

    exit_code = proc.returncode if proc.returncode is not None else 1
    status = TaskStatus.SUCCEEDED if exit_code == 0 else TaskStatus.FAILED
    summary = _summarize(raw, exit_code)
    return AgentResult(
        status=status,
        summary=summary,
        raw_output=raw,
        exit_code=exit_code,
    )


def _summarize(raw: str, exit_code: int) -> str:
    text = raw.strip()
    if not text:
        return f"exit={exit_code} (no output)"
    # Prefer last non-empty lines for a short summary
    lines = [ln for ln in text.splitlines() if ln.strip()]
    tail = "\n".join(lines[-12:])
    if len(tail) > 2000:
        return tail[-2000:]
    return tail
