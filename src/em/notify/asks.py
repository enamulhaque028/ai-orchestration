"""Typed human asks raised by agents (or YAML gates)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

AskType = Literal["confirm", "choice", "text"]
ReplyKind = Literal["approve", "reject", "answer"]

# Agents print one of these blocks when they need a human:
#   EM_ASK:{"type":"confirm","question":"..."}
#   EM_ASK:{"type":"choice","question":"...","options":["A","B"]}
#   EM_ASK:{"type":"text","question":"..."}
_EM_ASK_RE = re.compile(
    r"EM_ASK\s*:\s*(\{.*?\})(?:\s*$|\s*\n)",
    re.DOTALL | re.IGNORECASE,
)
_EM_ASK_JSON_RE = re.compile(
    r"\{\s*\"em_ask\"\s*:\s*(\{.*?\})\s*\}",
    re.DOTALL,
)


@dataclass
class HumanAsk:
    type: AskType
    question: str
    options: list[str] = field(default_factory=list)
    source: str = "agent"  # agent | yaml

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "question": self.question,
            "options": list(self.options),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HumanAsk:
        ask_type = str(data.get("type") or "confirm")
        if ask_type not in ("confirm", "choice", "text"):
            ask_type = "confirm"
        options = data.get("options") or []
        if not isinstance(options, list):
            options = [str(options)]
        return cls(
            type=ask_type,  # type: ignore[arg-type]
            question=str(data.get("question") or "").strip() or "Need your input",
            options=[str(o).strip() for o in options if str(o).strip()],
            source=str(data.get("source") or "agent"),
        )


@dataclass
class HumanReply:
    kind: ReplyKind
    answer: str = ""
    source: str = "cli"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HumanReply | None:
        # Back-compat with older approve/reject files
        if "decision" in data and "kind" not in data:
            dec = data.get("decision")
            if dec == "approve":
                return cls(kind="approve", answer="approve", source=str(data.get("source") or "cli"))
            if dec == "reject":
                return cls(
                    kind="reject",
                    answer=str(data.get("reason") or "rejected"),
                    source=str(data.get("source") or "cli"),
                )
            return None
        kind = data.get("kind")
        if kind not in ("approve", "reject", "answer"):
            return None
        return cls(
            kind=kind,  # type: ignore[arg-type]
            answer=str(data.get("answer") or ""),
            source=str(data.get("source") or "cli"),
        )


def parse_em_ask(text: str) -> HumanAsk | None:
    """Extract the last EM_ASK payload from agent output/summary."""
    if not text:
        return None
    matches = list(_EM_ASK_RE.finditer(text))
    payload: str | None = None
    if matches:
        payload = matches[-1].group(1)
    else:
        matches2 = list(_EM_ASK_JSON_RE.finditer(text))
        if matches2:
            payload = matches2[-1].group(1)
    if not payload:
        # Also accept a bare {"type":...,"question":...} on its own line after EM_ASK hint
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    ask = HumanAsk.from_dict(data)
    if ask.type == "choice" and len(ask.options) < 2:
        return None
    return ask


def ask_path(state_root: Path, run_id: str, task_id: str) -> Path:
    return Path(state_root) / "approvals" / run_id / f"{task_id}.ask.json"


def reply_path(state_root: Path, run_id: str, task_id: str) -> Path:
    return Path(state_root) / "approvals" / run_id / f"{task_id}.json"


def write_ask(state_root: Path, run_id: str, task_id: str, ask: HumanAsk) -> Path:
    path = ask_path(state_root, run_id, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ask.to_dict(), indent=2), encoding="utf-8")
    return path


def read_ask(state_root: Path, run_id: str, task_id: str) -> HumanAsk | None:
    path = ask_path(state_root, run_id, task_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return HumanAsk.from_dict(data)


def write_reply(
    state_root: Path,
    run_id: str,
    task_id: str,
    kind: ReplyKind,
    *,
    answer: str = "",
    source: str = "cli",
) -> Path:
    path = reply_path(state_root, run_id, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = HumanReply(kind=kind, answer=answer, source=source).to_dict()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_reply(state_root: Path, run_id: str, task_id: str) -> HumanReply | None:
    path = reply_path(state_root, run_id, task_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return HumanReply.from_dict(data)


def clear_ask_files(state_root: Path, run_id: str, task_id: str) -> None:
    for path in (ask_path(state_root, run_id, task_id), reply_path(state_root, run_id, task_id)):
        if path.is_file():
            path.unlink()


# Appended to every agent prompt so models know how to raise asks.
EM_ASK_INSTRUCTIONS = """
---
If you need help from the human operator (missing info, a decision, or confirmation),
do NOT guess. Finish your current message by printing exactly one line in this form:

EM_ASK:{"type":"confirm","question":"Short yes/no question"}
EM_ASK:{"type":"choice","question":"Pick one","options":["Option A","Option B"]}
EM_ASK:{"type":"text","question":"What value should I use for X?"}

Then stop. The Engineering Manager will pause, ask the human (Telegram/desk), and
re-run you with their answer. Do not invent EM_ASK unless you truly need input.
""".strip()
