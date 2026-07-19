"""Tests for local config and approval decision files."""

from pathlib import Path

from em.config import EmConfig, load_config, redact_token, save_config
from em.notify.approvals import read_decision, write_decision
from em.notify.telegram import parse_approval_from_update


def test_save_load_config(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.yaml"
    cfg = EmConfig()
    cfg.telegram.bot_token = "123:ABC"
    cfg.telegram.chat_id = "99"
    cfg.telegram.allowed_chat_ids = ["99"]
    cfg.notify.on_task_complete = False
    save_config(cfg, path)

    monkeypatch.delenv("EM_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("EM_TELEGRAM_CHAT_ID", raising=False)
    loaded = load_config(path)
    assert loaded.telegram.bot_token == "123:ABC"
    assert loaded.telegram.chat_id == "99"
    assert loaded.notify.on_task_complete is False
    assert loaded.telegram.is_configured()


def test_env_overrides_config(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.yaml"
    save_config(EmConfig(), path)
    monkeypatch.setenv("EM_TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("EM_TELEGRAM_CHAT_ID", "42")
    loaded = load_config(path)
    assert loaded.telegram.bot_token == "env-token"
    assert loaded.telegram.chat_id == "42"
    assert "42" in loaded.telegram.allowlist()


def test_redact_token():
    assert redact_token("") == "(not set)"
    assert "…" in redact_token("1234567890abcdef")


def test_write_read_decision(tmp_path: Path):
    write_decision(tmp_path, "run_abc", "task1", "approve", source="cli")
    d = read_decision(tmp_path, "run_abc", "task1")
    assert d is not None
    assert d.decision == "approve"
    assert d.source == "cli"


def test_parse_callback_allowlist():
    update = {
        "callback_query": {
            "id": "1",
            "from": {"id": 7},
            "message": {"chat": {"id": 7}},
            "data": "em:approve:run_abc:gate",
        }
    }
    assert parse_approval_from_update(
        update, run_id="run_abc", task_id="gate", allowlist={"7"}
    ) == ("approve", "telegram:callback:7")
    assert (
        parse_approval_from_update(
            update, run_id="run_abc", task_id="gate", allowlist={"9"}
        )
        is None
    )


def test_parse_text_approve():
    update = {"message": {"chat": {"id": 5}, "text": "approve"}}
    result = parse_approval_from_update(
        update, run_id="r", task_id="t", allowlist={"5"}
    )
    assert result is not None
    assert result[0] == "approve"


def test_chat_id_from_update():
    from em.notify.telegram import chat_id_from_update

    assert (
        chat_id_from_update(
            {"message": {"chat": {"id": 42, "type": "private"}, "text": "hi"}}
        )
        == "42"
    )
    assert (
        chat_id_from_update(
            {"message": {"chat": {"id": -100, "type": "group"}, "text": "hi"}}
        )
        is None
    )


def test_clean_summary_flattens_markdown():
    from em.notify import _clean_summary

    raw = (
        "### Test run\n"
        "| Area | Status |\n"
        "|------|--------|\n"
        "| Fake Store API | **PASS** |\n"
        "| Tests (7/7) | **PASS** |\n"
    )
    out = _clean_summary(raw)
    assert "**" not in out
    assert "|---" not in out
    assert "Fake Store API — PASS" in out
    assert out.startswith("Test run")
