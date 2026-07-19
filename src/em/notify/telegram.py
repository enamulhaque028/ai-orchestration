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


def choice_keyboard(run_id: str, task_id: str, options: list[str]) -> dict[str, Any]:
    """Buttons use option index (callback_data max 64 bytes)."""
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for i, opt in enumerate(options[:8]):
        label = opt if len(opt) <= 40 else opt[:37] + "…"
        row.append(
            {
                "text": label,
                "callback_data": f"em:pick:{run_id}:{task_id}:{i}"[:64],
            }
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


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


def parse_human_reply_from_update(
    update: dict[str, Any],
    *,
    run_id: str,
    task_id: str,
    allowlist: set[str],
    ask_type: str = "confirm",
    options: list[str] | None = None,
) -> tuple[str, str, str] | None:
    """Return (kind, answer, source) if this update answers the pending ask."""
    options = options or []
    cb = update.get("callback_query")
    if cb:
        from_user = cb.get("from") or {}
        chat = (cb.get("message") or {}).get("chat") or {}
        chat_id = str(chat.get("id") or from_user.get("id") or "")
        if allowlist and chat_id not in allowlist:
            return None
        data = str(cb.get("data") or "")
        parts = data.split(":")
        if len(parts) >= 4 and parts[0] == "em":
            action = parts[1]
            rest = data[len(f"em:{action}:") :]
            if action in ("approve", "reject"):
                if rest == f"{run_id}:{task_id}" or (
                    rest.endswith(f":{task_id}") and rest.startswith(run_id)
                ):
                    return action, action, f"telegram:callback:{chat_id}"
            if action == "pick" and run_id in data and task_id in data:
                try:
                    idx = int(parts[-1])
                except ValueError:
                    return None
                if 0 <= idx < len(options):
                    return "answer", options[idx], f"telegram:callback:{chat_id}"
        return None

    msg = update.get("message")
    if msg:
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        if allowlist and chat_id not in allowlist:
            return None
        text = str(msg.get("text") or "").strip()
        low = text.lower()
        if ask_type == "confirm":
            if low in ("approve", "yes", "/approve", "y"):
                return "approve", "approve", f"telegram:text:{chat_id}"
            if low in ("reject", "no", "/reject", "n"):
                return "reject", "reject", f"telegram:text:{chat_id}"
            return None
        if ask_type == "choice":
            if low.isdigit():
                idx = int(low) - 1
                if 0 <= idx < len(options):
                    return "answer", options[idx], f"telegram:text:{chat_id}"
            for opt in options:
                if text == opt or low == opt.lower():
                    return "answer", opt, f"telegram:text:{chat_id}"
            return None
        if ask_type == "text" and text:
            return "answer", text, f"telegram:text:{chat_id}"
    return None


def parse_approval_from_update(
    update: dict[str, Any],
    *,
    run_id: str,
    task_id: str,
    allowlist: set[str],
) -> tuple[str, str] | None:
    """Back-compat wrapper → (approve|reject, source)."""
    parsed = parse_human_reply_from_update(
        update,
        run_id=run_id,
        task_id=task_id,
        allowlist=allowlist,
        ask_type="confirm",
    )
    if parsed and parsed[0] in ("approve", "reject"):
        return parsed[0], parsed[2]
    return None
