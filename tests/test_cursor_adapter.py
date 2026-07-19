"""Tests for Cursor Agent CLI adapter helpers."""

from pathlib import Path

from em.adapters.cursor import _resolve_agent_binary


def test_resolve_agent_binary_finds_local_bin(monkeypatch, tmp_path: Path):
    fake = tmp_path / "agent"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)

    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("EM_CURSOR_BIN", raising=False)

    found = _resolve_agent_binary()
    assert found == str(fake)


def test_resolve_agent_binary_respects_explicit(tmp_path: Path):
    fake = tmp_path / "custom-agent"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    assert _resolve_agent_binary(str(fake)) == str(fake)
