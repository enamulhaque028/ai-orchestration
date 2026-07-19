"""User-global Engineering Manager config (~/.em/config.yaml)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def default_config_path() -> Path:
    return Path.home() / ".em" / "config.yaml"


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    allowed_chat_ids: list[str] = field(default_factory=list)

    def is_configured(self) -> bool:
        return bool(self.bot_token.strip() and self.chat_id.strip())

    def allowlist(self) -> set[str]:
        ids = {str(x).strip() for x in self.allowed_chat_ids if str(x).strip()}
        if self.chat_id.strip():
            ids.add(self.chat_id.strip())
        return ids


@dataclass
class NotifyConfig:
    on_task_complete: bool = True
    on_run_complete: bool = True


@dataclass
class EmConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "telegram": {
                "bot_token": self.telegram.bot_token,
                "chat_id": self.telegram.chat_id,
                "allowed_chat_ids": list(self.telegram.allowed_chat_ids),
            },
            "notify": {
                "on_task_complete": self.notify.on_task_complete,
                "on_run_complete": self.notify.on_run_complete,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EmConfig:
        data = data or {}
        tg = data.get("telegram") or {}
        nt = data.get("notify") or {}
        allowed = tg.get("allowed_chat_ids") or []
        if not isinstance(allowed, list):
            allowed = [allowed]
        return cls(
            telegram=TelegramConfig(
                bot_token=str(tg.get("bot_token") or ""),
                chat_id=str(tg.get("chat_id") or ""),
                allowed_chat_ids=[str(x) for x in allowed],
            ),
            notify=NotifyConfig(
                on_task_complete=bool(nt.get("on_task_complete", True)),
                on_run_complete=bool(nt.get("on_run_complete", True)),
            ),
        )


def load_config(path: Path | None = None) -> EmConfig:
    cfg_path = path or default_config_path()
    cfg = EmConfig()
    if cfg_path.is_file():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raw = {}
        cfg = EmConfig.from_dict(raw)

    # Env overrides (never written back unless save is called with them)
    token = os.environ.get("EM_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("EM_TELEGRAM_CHAT_ID", "").strip()
    if token:
        cfg.telegram.bot_token = token
    if chat_id:
        cfg.telegram.chat_id = chat_id
        if chat_id not in cfg.telegram.allowed_chat_ids:
            cfg.telegram.allowed_chat_ids.append(chat_id)
    return cfg


def save_config(cfg: EmConfig, path: Path | None = None) -> Path:
    cfg_path = path or default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer file values without ephemeral env-only secrets if empty — save what we have
    text = yaml.safe_dump(cfg.to_dict(), default_flow_style=False, sort_keys=False)
    cfg_path.write_text(text, encoding="utf-8")
    try:
        cfg_path.chmod(0o600)
    except OSError:
        pass
    return cfg_path


def redact_token(token: str) -> str:
    t = token.strip()
    if len(t) <= 8:
        return "***" if t else "(not set)"
    return f"{t[:4]}…{t[-4:]}"


def clear_telegram(cfg: EmConfig) -> EmConfig:
    cfg.telegram = TelegramConfig()
    return cfg
