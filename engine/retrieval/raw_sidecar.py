from __future__ import annotations

from typing import Iterable

from ..memory.store import RawContextTurn

_PROVENANCE_PHRASES = (
    "show original context",
    "show the original context",
    "show source context",
    "open source slice",
    "original wording",
    "original context",
    "source slice",
    "what exactly did you say",
    "what exactly did i say",
    "what exactly did the assistant say",
    "what exactly did the user say",
    "quote it",
    "quote that",
    "verbatim",
)


def is_raw_context_query(query_text: str, *, profile_used: str = "") -> bool:
    lowered = str(query_text or "").strip().lower()
    if not lowered:
        return False
    if str(profile_used or "").strip() == "verbatim_session_recall":
        return True
    return any(phrase in lowered for phrase in _PROVENANCE_PHRASES)


def format_raw_context_slice(turns: Iterable[RawContextTurn], *, max_chars: int) -> tuple[str, int]:
    lines: list[str] = []
    count = 0
    for turn in list(turns or []):
        role = str(getattr(turn, "role", "") or "").strip().lower()
        label = {
            "user": "User",
            "assistant": "Assistant",
            "developer": "Developer",
            "system": "System",
            "tool": "Tool",
        }.get(role, "Memory")
        text = str(getattr(turn, "quote_text", "") or "")
        if not text:
            continue
        lines.append(f"{label}: {text}")
        count += 1
    payload = "\n".join(lines).strip()
    if len(payload) > max(1, int(max_chars)):
        payload = payload[: max(1, int(max_chars)) - 1].rstrip() + "…"
    return payload, count
