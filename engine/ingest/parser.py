from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .streaming_json import iter_json_array_objects
from ..contracts import NormalizedTurn

DEFAULT_DROP_PATTERNS: tuple[str, ...] = (
    "Make sure to include `【message_idx†source】` markers to provide citations based on this file",
    "The user uploaded the following files:",
    "Use this to inform your answer",
)


def normalize_role(raw_role: Any) -> Optional[str]:
    role = str(raw_role or "").strip().lower()
    if role in {"user", "human"}:
        return "user"
    if role in {"assistant", "model", "chatgpt"}:
        return "assistant"
    if role in {"developer", "system", "tool"}:
        return role
    return None


def normalize_timestamp(raw_value: Any) -> Optional[datetime]:
    """Normalize mixed timestamp formats to UTC datetime.

    Returns ``None`` when the value is missing or malformed.
    """

    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
        if value > 1e12:
            value /= 1000.0
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(raw_value).strip()
    if not text:
        return None
    if text.isdigit():
        return normalize_timestamp(float(text))
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
        if isinstance(parts, list):
            chunks = [str(part).strip() for part in parts if str(part).strip()]
            if chunks:
                return "\n".join(chunks)
        text = content.get("text")
        if text:
            return str(text).strip()
    if isinstance(content, str):
        return content.strip()
    text = message.get("text")
    return str(text or "").strip()


def _first_valid_timestamp(*values: Any) -> Optional[datetime]:
    """Return the first parseable timestamp from candidate values."""

    for value in values:
        parsed = normalize_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def noise_reason(text: str, *, role: str, drop_patterns: Iterable[str] = DEFAULT_DROP_PATTERNS) -> Optional[str]:
    lower_text = text.lower()
    for pattern in drop_patterns:
        if pattern.lower() in lower_text:
            return "preface_blob"
    if role in {"tool", "system"} and not text.strip():
        return "empty_tool_or_system"
    if role == "tool" and (lower_text.startswith("{") or lower_text.startswith("[")):
        return "tool_payload"
    return None


@dataclass(slots=True)
class IngestStats:
    total_messages: int = 0
    emitted_turns: int = 0
    skipped_by_reason: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class IngestResult:
    turns: list[NormalizedTurn]
    stats: IngestStats


class ConversationIngestor:
    def __init__(self, *, drop_patterns: Iterable[str] = DEFAULT_DROP_PATTERNS) -> None:
        self.drop_patterns = tuple(drop_patterns)

    def iter_turns_from_conversation(self, convo: dict[str, Any]) -> Iterator[tuple[Optional[NormalizedTurn], Optional[str]]]:
        conversation_id = str(convo.get("id") or convo.get("conversation_id") or "") or None
        convo_timestamp = _first_valid_timestamp(
            convo.get("create_time_iso"),
            convo.get("source_create_time_iso"),
            convo.get("create_time"),
            convo.get("source_create_time"),
            convo.get("update_time_iso"),
            convo.get("update_time"),
        )

        mapping = convo.get("mapping")
        if isinstance(mapping, dict) and mapping:
            def _create_time(node: dict[str, Any]) -> float:
                message = node.get("message")
                if not isinstance(message, dict):
                    return 0.0
                parsed = _first_valid_timestamp(
                    message.get("create_time"),
                    message.get("create_time_iso"),
                    message.get("time_iso"),
                    message.get("time"),
                    message.get("timestamp"),
                    convo_timestamp,
                )
                return parsed.timestamp() if parsed is not None else 0.0

            nodes = sorted(
                (node for node in mapping.values() if isinstance(node, dict)),
                key=_create_time,
            )
            for node in nodes:
                message = node.get("message")
                if not isinstance(message, dict):
                    continue
                role = normalize_role(((message.get("author") or {}).get("role")))
                if role is None:
                    yield None, "unsupported_role"
                    continue
                text = _message_text(message)
                reason = noise_reason(text, role=role, drop_patterns=self.drop_patterns)
                if reason:
                    yield None, reason
                    continue
                if not text:
                    yield None, "empty_text"
                    continue
                turn = NormalizedTurn(
                    source_id=conversation_id or "conversation",
                    conversation_id=conversation_id,
                    message_id=str(message.get("id") or node.get("id") or "") or None,
                    role=role,
                    text=text,
                    timestamp=_first_valid_timestamp(
                        message.get("create_time"),
                        message.get("create_time_iso"),
                        message.get("time_iso"),
                        message.get("time"),
                        message.get("timestamp"),
                        convo_timestamp,
                    ),
                )
                yield turn, None
            return

        messages = convo.get("messages")
        if isinstance(messages, list):
            for index, message in enumerate(messages):
                if not isinstance(message, dict):
                    continue
                role = normalize_role(message.get("role"))
                if role is None:
                    yield None, "unsupported_role"
                    continue
                text = _message_text(message)
                reason = noise_reason(text, role=role, drop_patterns=self.drop_patterns)
                if reason:
                    yield None, reason
                    continue
                if not text:
                    yield None, "empty_text"
                    continue
                turn = NormalizedTurn(
                    source_id=conversation_id or "conversation",
                    conversation_id=conversation_id,
                    message_id=str(message.get("id") or index),
                    role=role,
                    text=text,
                    timestamp=_first_valid_timestamp(
                        message.get("time_iso"),
                        message.get("time"),
                        message.get("timestamp"),
                        message.get("create_time"),
                        message.get("create_time_iso"),
                        convo_timestamp,
                    ),
                )
                yield turn, None
            return

    def ingest_export(self, path: str | Path) -> IngestResult:
        turns: list[NormalizedTurn] = []
        stats = IngestStats()
        for convo in self.iter_export_conversations(path):
            for maybe_turn, maybe_reason in self.iter_turns_from_conversation(convo):
                stats.total_messages += 1
                if maybe_turn is not None:
                    turns.append(maybe_turn)
                    stats.emitted_turns += 1
                elif maybe_reason:
                    stats.skipped_by_reason[maybe_reason] += 1
        return IngestResult(turns=turns, stats=stats)

    def iter_export_conversations(self, path: str | Path) -> Iterator[dict[str, Any]]:
        src = Path(path)
        try:
            yield from iter_json_array_objects(src)
            return
        except ValueError as exc:
            if "JSON root must be an array" not in str(exc):
                raise

        with src.open("r", encoding="utf-8", errors="replace") as fp:
            payload = json.load(fp)
        if isinstance(payload, dict):
            conversations = payload.get("conversations")
            if isinstance(conversations, list):
                for convo in conversations:
                    if isinstance(convo, dict):
                        yield convo
                return
        raise ValueError("JSON root must be an array or an object with conversations[]")
