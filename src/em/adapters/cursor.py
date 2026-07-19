"""Cursor Agent CLI adapter (login via `agent login`; no API key required)."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from em.adapters.base import run_subprocess
from em.models import AgentResult, TaskRunSpec, TaskStatus


def _resolve_agent_binary(explicit: str | None = None) -> str | None:
    """Find `agent` / `cursor-agent`, including ~/.local/bin."""
    search_dirs: list[Path] = []
    path_env = os.environ.get("PATH", "")
    search_dirs.extend(Path(p) for p in path_env.split(os.pathsep) if p)
    search_dirs.append(Path.home() / ".local" / "bin")

    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    env_bin = os.environ.get("EM_CURSOR_BIN")
    if env_bin:
        candidates.append(env_bin)
    candidates.extend(["agent", "cursor-agent"])

    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        # Absolute path
        p = Path(name)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        which = shutil.which(name)
        if which:
            return which
        for d in search_dirs:
            candidate = d / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


class CursorAdapter:
    """Run tasks with Cursor Agent CLI (`agent -p`), using CLI login auth."""

    async def run(self, spec: TaskRunSpec) -> AgentResult:
        # Default: CLI. Opt into SDK with agent.extra.use_sdk: true
        use_sdk = bool(spec.agent.extra.get("use_sdk", False))
        if use_sdk:
            sdk_result = await self._run_sdk(spec)
            if sdk_result is not None:
                return sdk_result
        return await self._run_cli(spec)

    async def _run_sdk(self, spec: TaskRunSpec) -> AgentResult | None:
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions  # type: ignore
        except ImportError:
            try:
                from cursor_sdk import Agent  # type: ignore
            except ImportError:
                return None

        api_key = spec.agent.extra.get("api_key") or os.environ.get("CURSOR_API_KEY")
        model = spec.agent.model or "composer-2.5"

        def _prompt() -> AgentResult:
            try:
                options = AgentOptions(
                    api_key=api_key,
                    model=model,
                    local=LocalAgentOptions(cwd=spec.cwd),
                )
                result = Agent.prompt(spec.prompt, options)
            except Exception:
                try:
                    result = Agent.prompt(  # type: ignore[call-arg]
                        spec.prompt,
                        api_key=api_key,
                        model=model,
                        local={"cwd": spec.cwd},
                    )
                except Exception as exc:  # noqa: BLE001
                    return AgentResult(
                        status=TaskStatus.FAILED,
                        summary=f"cursor-sdk error: {exc}",
                        raw_output=str(exc),
                        exit_code=1,
                    )

            status_val = getattr(result, "status", None)
            text = (
                getattr(result, "result", None)
                or getattr(result, "text", None)
                or str(result)
            )
            raw = str(text)
            if spec.log_path:
                Path(spec.log_path).parent.mkdir(parents=True, exist_ok=True)
                Path(spec.log_path).write_text(raw, encoding="utf-8")

            ok = status_val in (None, "finished", "completed", "success", "ok")
            if hasattr(status_val, "value"):
                ok = status_val.value in ("finished", "completed", "success")
            if status_val == "error":
                ok = False

            return AgentResult(
                status=TaskStatus.SUCCEEDED if ok else TaskStatus.FAILED,
                summary=raw.strip()[-2000:] if raw.strip() else f"status={status_val}",
                raw_output=raw,
                exit_code=0 if ok else 1,
                agent_id=getattr(result, "agent_id", None)
                or getattr(result, "agentId", None),
                run_id=getattr(result, "id", None) or getattr(result, "run_id", None),
            )

        return await asyncio.to_thread(_prompt)

    async def _run_cli(self, spec: TaskRunSpec) -> AgentResult:
        binary = _resolve_agent_binary(spec.agent.extra.get("binary"))
        if not binary:
            return AgentResult(
                status=TaskStatus.FAILED,
                summary=(
                    "Cursor Agent CLI not found. Install it and ensure "
                    "`agent` or `cursor-agent` is on PATH (often ~/.local/bin), "
                    "then run: agent login"
                ),
                exit_code=127,
            )

        # Headless: print mode + trust workspace + force tool approvals (yolo).
        # Auth comes from `agent login`, not CURSOR_API_KEY.
        force = spec.agent.extra.get("force", True)
        trust = spec.agent.extra.get("trust", True)
        output_format = str(spec.agent.extra.get("output_format", "text"))
        sandbox = spec.agent.extra.get("sandbox")  # enabled | disabled | None

        cmd: list[str] = [
            binary,
            "--print",
            "--output-format",
            output_format,
            "--workspace",
            spec.cwd,
        ]
        if trust:
            cmd.append("--trust")
        if force:
            cmd.append("--force")
        if sandbox in ("enabled", "disabled"):
            cmd.extend(["--sandbox", str(sandbox)])

        model = spec.agent.model or spec.agent.extra.get("model")
        if model:
            cmd.extend(["--model", str(model)])

        cmd.append(spec.prompt)

        return await run_subprocess(
            cmd,
            cwd=spec.cwd,
            env=spec.env or None,
            log_path=spec.log_path,
            timeout_seconds=spec.task.timeout_seconds
            or spec.agent.extra.get("timeout_seconds"),
        )
