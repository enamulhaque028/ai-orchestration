"""Human approval decision files for dual desk/remote control."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Decision = Literal["approve", "reject"]


@dataclass
class ApprovalDecision:
    decision: Decision
    reason: str = ""
    source: str = "cli"  # cli | telegram | terminal

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ApprovalDecision:
        return cls(
            decision=data["decision"],  # type: ignore[arg-type]
            reason=str(data.get("reason") or ""),
            source=str(data.get("source") or "cli"),
        )


def approvals_dir(state_root: Path, run_id: str) -> Path:
    return Path(state_root) / "approvals" / run_id


def decision_path(state_root: Path, run_id: str, task_id: str) -> Path:
    return approvals_dir(state_root, run_id) / f"{task_id}.json"


def write_decision(
    state_root: Path,
    run_id: str,
    task_id: str,
    decision: Decision,
    *,
    reason: str = "",
    source: str = "cli",
) -> Path:
    path = decision_path(state_root, run_id, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = ApprovalDecision(
        decision=decision, reason=reason, source=source
    ).to_dict()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_decision(
    state_root: Path, run_id: str, task_id: str
) -> ApprovalDecision | None:
    path = decision_path(state_root, run_id, task_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("decision") not in ("approve", "reject"):
        return None
    return ApprovalDecision.from_dict(data)


def clear_decision(state_root: Path, run_id: str, task_id: str) -> None:
    path = decision_path(state_root, run_id, task_id)
    if path.is_file():
        path.unlink()
