"""Human approval / reply decision files (back-compat wrappers)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from em.notify.asks import (
    clear_ask_files,
    read_reply,
    reply_path,
    write_reply,
)

Decision = Literal["approve", "reject"]


@dataclass
class ApprovalDecision:
    decision: Decision
    reason: str = ""
    source: str = "cli"

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "source": self.source,
            "kind": self.decision,
            "answer": "approve" if self.decision == "approve" else self.reason,
        }


def approvals_dir(state_root: Path, run_id: str) -> Path:
    return Path(state_root) / "approvals" / run_id


def decision_path(state_root: Path, run_id: str, task_id: str) -> Path:
    return reply_path(state_root, run_id, task_id)


def write_decision(
    state_root: Path,
    run_id: str,
    task_id: str,
    decision: Decision,
    *,
    reason: str = "",
    source: str = "cli",
) -> Path:
    return write_reply(
        state_root,
        run_id,
        task_id,
        decision,
        answer="approve" if decision == "approve" else reason,
        source=source,
    )


def read_decision(
    state_root: Path, run_id: str, task_id: str
) -> ApprovalDecision | None:
    reply = read_reply(state_root, run_id, task_id)
    if reply is None:
        return None
    if reply.kind == "approve":
        return ApprovalDecision(decision="approve", source=reply.source)
    if reply.kind == "reject":
        return ApprovalDecision(
            decision="reject", reason=reply.answer, source=reply.source
        )
    # Typed answers are not approve/reject decisions
    return None


def clear_decision(state_root: Path, run_id: str, task_id: str) -> None:
    clear_ask_files(state_root, run_id, task_id)
