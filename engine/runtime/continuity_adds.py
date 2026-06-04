from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


CONTINUITY_ADDS_STATE_SCHEMA = "numquamoblita.runtime.continuity_adds.v1"
RETRIEVAL_FEEDBACK_ALLOWED = {"useful", "irrelevant", "outdated", "wrong"}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _clip_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1].rstrip() + "…"


def default_continuity_adds_state() -> dict[str, Any]:
    return {
        "schema": CONTINUITY_ADDS_STATE_SCHEMA,
        "updated_at": _utc_iso(),
        "exploration_preferences": {},
        "retrieval_feedback": [],
        "action_log": [],
    }


def load_continuity_adds_state(
    path: Path,
    *,
    max_feedback_entries: int = 2000,
    max_action_entries: int = 1000,
) -> dict[str, Any]:
    if not path.exists():
        return default_continuity_adds_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_continuity_adds_state()
    if not isinstance(raw, Mapping):
        return default_continuity_adds_state()
    state = default_continuity_adds_state()
    state["schema"] = str(raw.get("schema") or CONTINUITY_ADDS_STATE_SCHEMA)
    state["updated_at"] = str(raw.get("updated_at") or _utc_iso())
    preferences = raw.get("exploration_preferences")
    if isinstance(preferences, Mapping):
        state["exploration_preferences"] = {
            str(key): dict(value)
            for key, value in preferences.items()
            if isinstance(key, str) and isinstance(value, Mapping)
        }
    feedback = [dict(item) for item in list(raw.get("retrieval_feedback") or []) if isinstance(item, Mapping)]
    action_log = [dict(item) for item in list(raw.get("action_log") or []) if isinstance(item, Mapping)]
    state["retrieval_feedback"] = feedback[-max(1, int(max_feedback_entries)) :]
    state["action_log"] = action_log[-max(1, int(max_action_entries)) :]
    return state


def persist_continuity_adds_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state or {})
    payload["schema"] = CONTINUITY_ADDS_STATE_SCHEMA
    payload["updated_at"] = _utc_iso()
    blob = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(blob + "\n", encoding="utf-8")
    tmp.replace(path)


def record_retrieval_feedback(
    state: dict[str, Any],
    *,
    item_id: str,
    item_kind: str,
    feedback: str,
    session_id: str,
    query_text: str,
    metadata: Mapping[str, Any] | None,
    max_entries: int,
    max_query_chars: int,
) -> dict[str, Any]:
    normalized_feedback = str(feedback or "").strip().lower()
    if normalized_feedback not in RETRIEVAL_FEEDBACK_ALLOWED:
        raise ValueError("feedback must be one of: useful, irrelevant, outdated, wrong")
    row = {
        "feedback_id": _new_id("rfb"),
        "item_id": str(item_id or "").strip(),
        "item_kind": str(item_kind or "").strip().lower() or "unknown",
        "feedback": normalized_feedback,
        "session_id": str(session_id or "").strip(),
        "query_text": _clip_text(query_text, max_chars=max(1, int(max_query_chars))),
        "metadata": dict(metadata or {}),
        "created_at": _utc_iso(),
    }
    rows = [dict(item) for item in list(state.get("retrieval_feedback") or []) if isinstance(item, Mapping)]
    rows.append(row)
    state["retrieval_feedback"] = rows[-max(1, int(max_entries)) :]
    state["updated_at"] = _utc_iso()
    return row


def append_action_log(
    state: dict[str, Any],
    *,
    action_type: str,
    summary: str,
    session_id: str,
    metadata: Mapping[str, Any] | None,
    max_entries: int,
) -> dict[str, Any]:
    row = {
        "action_id": _new_id("act"),
        "action_type": str(action_type or "").strip() or "unknown",
        "summary": _clip_text(summary, max_chars=220),
        "session_id": str(session_id or "").strip(),
        "metadata": dict(metadata or {}),
        "created_at": _utc_iso(),
    }
    rows = [dict(item) for item in list(state.get("action_log") or []) if isinstance(item, Mapping)]
    rows.append(row)
    state["action_log"] = rows[-max(1, int(max_entries)) :]
    state["updated_at"] = _utc_iso()
    return row
