"""Provider → adapter registry."""

from __future__ import annotations

from typing import Any

from em.adapters.claude import ClaudeAdapter
from em.adapters.codex import CodexAdapter
from em.adapters.cursor import CursorAdapter
from em.adapters.gemini import GeminiAdapter
from em.adapters.mock import MockAdapter
from em.adapters.shell import ShellAdapter

_REGISTRY: dict[str, Any] = {}
_DEFAULTS_REGISTERED = False


def _ensure_defaults() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    register_adapter("claude", ClaudeAdapter())
    register_adapter("cursor", CursorAdapter())
    register_adapter("codex", CodexAdapter())
    register_adapter("gemini", GeminiAdapter())
    register_adapter("shell", ShellAdapter())
    register_adapter("mock", MockAdapter())
    _DEFAULTS_REGISTERED = True


def register_adapter(provider: str, adapter: Any) -> None:
    _REGISTRY[provider.lower()] = adapter


def get_adapter(provider: str) -> Any:
    _ensure_defaults()
    key = provider.lower()
    if key not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"Unknown provider '{provider}'. Known: {known}")
    return _REGISTRY[key]
