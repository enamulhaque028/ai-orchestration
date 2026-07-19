"""Notification facade — Telegram when configured, otherwise no-op."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from em.config import EmConfig, load_config
from em.notify import telegram as tg
from em.notify.approvals import ApprovalDecision, write_decision

if TYPE_CHECKING:
    from pathlib import Path

    from em.models import RunState, TaskState

logger = logging.getLogger(__name__)

_STATUS_ICON = {
    "succeeded": "✅",
    "failed": "❌",
    "skipped": "⏭️",
    "cancelled": "🚫",
    "waiting_approval": "⏸️",
    "running": "▶️",
}


def _clean_summary(text: str, limit: int = 600) -> str:
    """Flatten agent markdown (tables, bold, headings) into readable plain text."""
    text = (text or "").strip()
    if not text:
        return ""
    lines_out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        # Strip emphasis / inline code markers early so table cells are clean too
        line = line.replace("**", "").replace("`", "")
        # Drop markdown table separator rows like |----|----|
        if re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", line) and "-" in line:
            continue
        # Table row → " • cell — cell"
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            cells = [c for c in cells if c]
            if cells:
                lines_out.append("• " + " — ".join(cells))
                continue
        # Headings ### foo → foo
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        lines_out.append(line)
    cleaned = "\n".join(lines_out)
    # Collapse 3+ blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


class Notifier:
    def __init__(self, cfg: EmConfig | None = None) -> None:
        self.cfg = cfg or load_config()

    @property
    def telegram_ready(self) -> bool:
        return self.cfg.telegram.is_configured()

    def _send(self, text: str, *, reply_markup: dict | None = None) -> None:
        if not self.telegram_ready:
            return
        try:
            tg.send_message(
                self.cfg.telegram.bot_token,
                self.cfg.telegram.chat_id,
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except Exception as exc:  # noqa: BLE001 — never break the run for notify
            logger.warning("Telegram notify failed: %s", exc)

    def task_completed(self, state: "RunState", task: "TaskState") -> None:
        if not self.cfg.notify.on_task_complete:
            return
        esc = tg.html_escape
        icon = _STATUS_ICON.get(task.status.value, "•")
        summary = _clean_summary(task.summary or task.error or "")
        parts = [
            f"{icon} <b>{esc(task.id)}</b> — {esc(task.status.value)}",
            f"<i>run {esc(state.run_id)}</i>",
        ]
        if summary:
            parts.append("")
            parts.append(esc(summary))
        self._send("\n".join(parts))

    def run_completed(self, state: "RunState") -> None:
        if not self.cfg.notify.on_run_complete:
            return
        esc = tg.html_escape
        counts: dict[str, int] = {}
        for t in state.tasks.values():
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        run_icon = _STATUS_ICON.get(state.status.value, "•")
        rollup = "  ".join(
            f"{_STATUS_ICON.get(k, '•')} {v} {k}" for k, v in sorted(counts.items())
        )
        self._send(
            f"{run_icon} <b>Run {esc(state.status.value)}</b>\n"
            f"<i>{esc(state.workflow_name)} · {esc(state.run_id)}</i>\n"
            f"{rollup}"
        )

    def needs_approval(self, state: "RunState", task_id: str) -> None:
        esc = tg.html_escape
        text = (
            f"⏸️ <b>Approval needed</b>\n"
            f"task: <b>{esc(task_id)}</b>\n"
            f"<i>{esc(state.workflow_name)} · {esc(state.run_id)}</i>\n\n"
            f"Tap a button below, reply <b>approve</b>/<b>reject</b>,\n"
            f"or at your desk: <code>em approve {esc(state.run_id)} {esc(task_id)}</code>"
        )
        markup = None
        if self.telegram_ready:
            markup = tg.approval_keyboard(state.run_id, task_id)
        self._send(text, reply_markup=markup)

    def poll_telegram_decision(
        self,
        *,
        state_root: "Path",
        run_id: str,
        task_id: str,
        offset: int | None = None,
    ) -> tuple[ApprovalDecision | None, int | None]:
        """Poll getUpdates once; write decision file if found. Returns (decision, next_offset)."""
        if not self.telegram_ready:
            return None, offset
        try:
            updates = tg.get_updates(
                self.cfg.telegram.bot_token, offset=offset, timeout=2
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram poll failed: %s", exc)
            return None, offset

        next_offset = offset
        allow = self.cfg.telegram.allowlist()
        for upd in updates:
            upd_id = upd.get("update_id")
            if isinstance(upd_id, int):
                next_offset = upd_id + 1
            parsed = tg.parse_approval_from_update(
                upd, run_id=run_id, task_id=task_id, allowlist=allow
            )
            cb = upd.get("callback_query")
            if cb and self.telegram_ready:
                try:
                    tg.answer_callback_query(
                        self.cfg.telegram.bot_token,
                        str(cb.get("id")),
                        text="Recorded" if parsed else "Ignored",
                    )
                except Exception:  # noqa: BLE001
                    pass
            if not parsed:
                continue
            decision, source = parsed
            write_decision(
                state_root,
                run_id,
                task_id,
                decision,  # type: ignore[arg-type]
                source=source,
            )
            from em.notify.approvals import read_decision

            return read_decision(state_root, run_id, task_id), next_offset
        return None, next_offset
