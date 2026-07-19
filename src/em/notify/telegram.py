"""Telegram Bot API helpers (stdlib urllib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class TelegramError(RuntimeError):
    pass


def _api(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise TelegramError(f"Telegram HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise TelegramError(f"Telegram network error: {e}") from e
    if not body.get("ok"):
        raise TelegramError(f"Telegram API error: {body}")
    return body


def get_me(token: str) -> dict[str, Any]:
    return _api(token, "getMe")["result"]


def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _api(token, "sendMessage", payload)["result"]


def html_escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def answer_callback_query(token: str, callback_query_id: str, text: str = "") -> None:
    _api(
        token,
        "answerCallbackQuery",
        {"callback_query_id": callback_query_id, "text": text[:200]},
    )


def approval_keyboard(run_id: str, task_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "Approve",
                    "callback_data": f"em:approve:{run_id}:{task_id}"[:64],
                },
                {
                    "text": "Reject",
                    "callback_data": f"em:reject:{run_id}:{task_id}"[:64],
                },
            ]
        ]
    }


def get_updates(
    token: str,
    *,
    offset: int | None = None,
    timeout: int = 25,
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        payload["offset"] = offset
    # Long poll — use urllib with longer timeout
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise TelegramError(f"Telegram HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise TelegramError(f"Telegram network error: {e}") from e
    if not body.get("ok"):
        raise TelegramError(f"Telegram API error: {body}")
    return list(body.get("result") or [])


def chat_id_from_update(update: dict[str, Any]) -> str | None:
    """Extract a private-chat id from a getUpdates item."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    chat = msg.get("chat") or {}
    if chat.get("type") and chat.get("type") != "private":
        return None
    chat_id = chat.get("id")
    return str(chat_id) if chat_id is not None else None


def discover_chat_id(
    token: str,
    *,
    wait_seconds: int = 90,
    poll_timeout: int = 5,
) -> str | None:
    """Wait for the user to message the bot; return their chat id."""
    import time

    deadline = time.monotonic() + max(1, wait_seconds)
    offset: int | None = None
    latest: str | None = None

    def _ingest(updates: list[dict[str, Any]]) -> str | None:
        nonlocal offset, latest
        fresh: str | None = None
        for upd in updates:
            upd_id = upd.get("update_id")
            if isinstance(upd_id, int):
                offset = upd_id + 1
            found = chat_id_from_update(upd)
            if found:
                latest = found
                fresh = found
        return fresh

    try:
        _ingest(get_updates(token, offset=None, timeout=0))
    except TelegramError:
        pass

    while time.monotonic() < deadline:
        try:
            updates = get_updates(token, offset=offset, timeout=poll_timeout)
        except TelegramError:
            time.sleep(1)
            continue
        fresh = _ingest(updates)
        if fresh:
            return fresh

    return latest


def parse_approval_from_update(
    update: dict[str, Any],
    *,
    run_id: str,
    task_id: str,
    allowlist: set[str],
) -> tuple[str, str] | None:
    """Return (decision, source_detail) if this update is an approval for the task."""
    cb = update.get("callback_query")
    if cb:
        from_user = cb.get("from") or {}
        chat = (cb.get("message") or {}).get("chat") or {}
        chat_id = str(chat.get("id") or from_user.get("id") or "")
        if allowlist and chat_id not in allowlist:
            return None
        data = str(cb.get("data") or "")
        # em:approve:run_xxx:task_id  (run_id may contain underscores)
        parts = data.split(":")
        if len(parts) >= 4 and parts[0] == "em" and parts[1] in ("approve", "reject"):
            # callback_data is limited to 64 bytes — we use em:approve:{run_id}:{task_id}
            dec = parts[1]
            # Remaining joined may be run_id:task_id
            rest = data[len(f"em:{dec}:") :]
            if rest == f"{run_id}:{task_id}" or (
                rest.endswith(f":{task_id}") and rest.startswith(run_id)
            ):
                return dec, f"telegram:callback:{chat_id}"
        return None

    msg = update.get("message")
    if msg:
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        if allowlist and chat_id not in allowlist:
            return None
        text = str(msg.get("text") or "").strip().lower()
        if text in ("approve", "yes", "/approve"):
            return "approve", f"telegram:text:{chat_id}"
        if text in ("reject", "no", "/reject"):
            return "reject", f"telegram:text:{chat_id}"
    return None
