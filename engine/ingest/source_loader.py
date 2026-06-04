from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import itertools
import json
import re
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .streaming_json import iter_json_array_objects

SUPPORTED_SOURCE_EXTENSIONS = {".json", ".jsonl", ".txt", ".md"}
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".next",
    "coverage",
    "subagents",
}

_ROLE_LINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^\s*(?:[>●•\-*]\s*)?(user|human|me|client|interviewer)\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE),
        "user",
    ),
    (
        re.compile(
            r"^\s*(?:[>●•\-*]\s*)?(assistant|ai|bot|claude|gpt|chatgpt|dex|lyra|agent)\s*[:\-]\s*(.+?)\s*$",
            re.IGNORECASE,
        ),
        "assistant",
    ),
]
_JOURNAL_HINTS = ("dear diary", "journal", "today i", "i feel", "i think", "my mood")


def _utc_from_timestamp(raw_value: Any) -> Optional[datetime]:
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
        for _ in range(3):
            if value > 1e11:
                value /= 1000.0
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(raw_value).strip()
    if not text:
        return None
    if text.isdigit():
        return _utc_from_timestamp(float(text))
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _file_timestamp(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError):
        return datetime.now(timezone.utc)


def _clean_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return str(value or "").strip()


def _normalize_role(raw_role: Any, *, default_role: str = "user") -> str:
    role = _clean_text(raw_role).lower()
    if role in {"user", "human", "me", "client", "interviewer"}:
        return "user"
    if role in {"assistant", "model", "chatgpt", "claude", "ai", "bot", "agent"}:
        return "assistant"
    if role in {"developer", "system", "tool"}:
        return role
    return default_role


def _extract_text_from_content_item(item: Any) -> list[str]:
    out: list[str] = []
    if isinstance(item, str):
        text = _clean_text(item)
        if text:
            out.append(text)
        return out
    if not isinstance(item, dict):
        return out

    kind = _clean_text(item.get("type") or item.get("kind")).lower()
    if kind in {"", "text"}:
        text = _clean_text(item.get("text") or item.get("content"))
        if text:
            out.append(text)
        return out
    if kind == "image":
        return ["[image]"]
    if kind == "tool_result":
        return []
    if kind == "tool_use":
        return []
    text = _clean_text(item.get("text") or item.get("content"))
    if text:
        out.append(text)
    return out


def _extract_text_from_payload(payload: Any) -> str:
    out: list[str] = []
    if isinstance(payload, str):
        text = _clean_text(payload)
        if text:
            out.append(text)
    elif isinstance(payload, list):
        for item in payload:
            out.extend(_extract_text_from_content_item(item))
    elif isinstance(payload, dict):
        parts = payload.get("parts")
        if isinstance(parts, list):
            for part in parts:
                out.extend(_extract_text_from_content_item(part))
        else:
            out.extend(_extract_text_from_content_item(payload))
    return "\n\n".join([item for item in out if item.strip()]).strip()


def _message_from_pair(index: int, role: str, text: str, *, timestamp: Optional[datetime] = None) -> dict[str, Any]:
    message: dict[str, Any] = {
        "id": f"m{index}",
        "role": role,
        "text": text,
    }
    if timestamp is not None:
        message["time"] = timestamp.isoformat()
    return message


def _looks_like_conversation_obj(obj: Any) -> bool:
    return isinstance(obj, dict) and (
        isinstance(obj.get("mapping"), dict)
        or isinstance(obj.get("messages"), list)
        or isinstance(obj.get("conversations"), list)
    )


def _looks_like_message_obj(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if "message" in obj and isinstance(obj.get("message"), dict):
        return True
    role_keys = ("role", "author", "speaker")
    text_keys = ("content", "text", "message", "prompt", "completion", "response")
    return any(key in obj for key in role_keys) and any(key in obj for key in text_keys)


def _conversation_from_message_sequence(messages: list[dict[str, Any]], *, source_id: str, path: Path) -> Optional[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = _normalize_role(message.get("role") or message.get("author") or message.get("speaker"), default_role="user")
        text = ""
        for key in ("text", "content", "message", "prompt", "completion", "response"):
            if key in message:
                text = _extract_text_from_payload(message.get(key))
                if text:
                    break
        if not text:
            continue
        timestamp = _utc_from_timestamp(
            message.get("time_iso")
            or message.get("time")
            or message.get("timestamp")
            or message.get("create_time")
            or message.get("create_time_iso")
        )
        normalized.append(_message_from_pair(index, role, text, timestamp=timestamp))
    if not normalized:
        return None
    file_time = _file_timestamp(path)
    return {
        "id": source_id,
        "source_file": str(path),
        "create_time": file_time.isoformat(),
        "update_time": file_time.isoformat(),
        "messages": normalized,
    }


def _coerce_json_value_to_conversations(value: Any, *, path: Path) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        conversations = value.get("conversations")
        if isinstance(conversations, list):
            return [row for row in conversations if isinstance(row, dict)]
        if _looks_like_conversation_obj(value):
            return [value]
        messages = value.get("messages")
        if isinstance(messages, list):
            convo = _conversation_from_message_sequence(
                messages,
                source_id=str(value.get("id") or value.get("conversation_id") or path.stem),
                path=path,
            )
            return [convo] if convo is not None else []
        if _looks_like_message_obj(value):
            convo = _conversation_from_message_sequence([value], source_id=path.stem, path=path)
            return [convo] if convo is not None else []
        return []
    if isinstance(value, list):
        if value and all(_looks_like_message_obj(item) for item in value if isinstance(item, dict)):
            convo = _conversation_from_message_sequence(value, source_id=path.stem, path=path)
            return [convo] if convo is not None else []
        out: list[dict[str, Any]] = []
        for item in value:
            out.extend(_coerce_json_value_to_conversations(item, path=path))
        return out
    return []


def _iter_json_file_conversations(path: Path) -> Iterator[dict[str, Any]]:
    try:
        stream = iter_json_array_objects(path)
        peeked: list[dict[str, Any]] = []
        for _ in range(3):
            try:
                peeked.append(next(stream))
            except StopIteration:
                break
        if peeked and not all(_looks_like_message_obj(obj) for obj in peeked):
            for obj in itertools.chain(peeked, stream):
                yield from _coerce_json_value_to_conversations(obj, path=path)
            return
    except ValueError as exc:
        if "JSON root must be an array" not in str(exc):
            raise

    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    yield from _coerce_json_value_to_conversations(payload, path=path)


def _extract_jsonl_pairs(row: dict[str, Any]) -> list[tuple[str, str, Optional[datetime]]]:
    out: list[tuple[str, str, Optional[datetime]]] = []
    etype = _clean_text(row.get("type")).lower()
    message = row.get("message")
    if etype in {"user", "human", "assistant"} and isinstance(message, dict):
        role = _normalize_role(message.get("role") or etype, default_role="user")
        text = _extract_text_from_payload(message.get("content"))
        if text:
            timestamp = _utc_from_timestamp(row.get("timestamp") or message.get("create_time") or message.get("time"))
            out.append((role, text, timestamp))
        return out
    if _looks_like_message_obj(row):
        role = _normalize_role(row.get("role") or row.get("author") or row.get("speaker"), default_role="user")
        text = ""
        for key in ("content", "text", "message", "prompt", "completion", "response"):
            if key in row:
                text = _extract_text_from_payload(row.get(key))
                if text:
                    break
        if text:
            timestamp = _utc_from_timestamp(row.get("timestamp") or row.get("time") or row.get("create_time"))
            out.append((role, text, timestamp))
    return out


def _iter_jsonl_file_conversations(path: Path) -> Iterator[dict[str, Any]]:
    grouped: dict[str, list[tuple[str, str, Optional[datetime]]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            session_id = _clean_text(
                row.get("sessionId") or row.get("session_id") or row.get("conversation_id") or row.get("chat_id")
            )
            if not session_id:
                session_id = path.stem
            grouped[session_id].extend(_extract_jsonl_pairs(row))
    file_time = _file_timestamp(path)
    for session_id, pairs in grouped.items():
        messages: list[dict[str, Any]] = []
        for index, (role, text, timestamp) in enumerate(pairs):
            if not text:
                continue
            messages.append(_message_from_pair(index, role, text, timestamp=timestamp))
        if not messages:
            continue
        yield {
            "id": f"jsonl:{session_id}",
            "source_file": str(path),
            "create_time": (pairs[0][2] or file_time).isoformat() if pairs else file_time.isoformat(),
            "update_time": (pairs[-1][2] or file_time).isoformat() if pairs else file_time.isoformat(),
            "messages": messages,
        }


def _parse_symbol_transcript(text: str) -> list[dict[str, Any]]:
    role_map = {">": "user", "❯": "user", "●": "assistant"}
    messages: list[dict[str, Any]] = []
    current_role: Optional[str] = None
    current_buf: list[str] = []

    def flush() -> None:
        nonlocal current_role, current_buf
        if current_role and current_buf:
            body = "\n".join(current_buf).strip()
            if body:
                messages.append({"role": current_role, "text": body})
        current_role = None
        current_buf = []

    for line in text.splitlines():
        stripped = line.lstrip()
        leading_spaces = len(line) - len(stripped)
        if stripped and stripped[0] in role_map and not (stripped[0] == ">" and leading_spaces > 0):
            flush()
            current_role = role_map[stripped[0]]
            head = stripped[1:].strip()
            current_buf = [head] if head else []
            continue
        if current_role:
            chunk = line.strip()
            if chunk:
                current_buf.append(chunk)
    flush()
    return messages


def _parse_role_prefix_transcript(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    current_role: Optional[str] = None
    current_buf: list[str] = []

    def flush() -> None:
        nonlocal current_role, current_buf
        if current_role and current_buf:
            body = "\n".join(current_buf).strip()
            if body:
                messages.append({"role": current_role, "text": body})
        current_role = None
        current_buf = []

    for line in text.splitlines():
        matched = False
        for pattern, role in _ROLE_LINE_PATTERNS:
            hit = pattern.match(line)
            if hit:
                flush()
                current_role = role
                current_buf = [_clean_text(hit.group(2))]
                matched = True
                break
        if matched:
            continue
        if current_role:
            chunk = line.strip()
            if chunk:
                current_buf.append(chunk)
    flush()
    return messages


def _looks_like_journal(text: str) -> bool:
    lower = text[:2000].lower()
    return any(hint in lower for hint in _JOURNAL_HINTS)


def _conversation_from_text_file(path: Path) -> Optional[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None
    messages = _parse_role_prefix_transcript(text)
    if len(messages) < 2:
        messages = _parse_symbol_transcript(text)
    file_time = _file_timestamp(path)
    if messages:
        return {
            "id": f"text:{path.stem}",
            "source_file": str(path),
            "create_time": file_time.isoformat(),
            "update_time": file_time.isoformat(),
            "messages": [_message_from_pair(index, row["role"], row["text"]) for index, row in enumerate(messages)],
        }
    role = "user"
    if _looks_like_journal(text):
        role = "user"
    return {
        "id": f"doc:{path.stem}",
        "source_file": str(path),
        "create_time": file_time.isoformat(),
        "update_time": file_time.isoformat(),
        "messages": [_message_from_pair(0, role, text)],
    }


def _iter_supported_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS:
            yield root
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part.lower() in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_SOURCE_EXTENSIONS:
            continue
        yield path


def iter_source_conversations(path: str | Path) -> Iterator[dict[str, Any]]:
    source_path = Path(path).expanduser().resolve()
    if not source_path.exists():
        raise ValueError(f"Path not found: {source_path}")
    for file_path in _iter_supported_files(source_path):
        ext = file_path.suffix.lower()
        if ext == ".json":
            yield from _iter_json_file_conversations(file_path)
            continue
        if ext == ".jsonl":
            yield from _iter_jsonl_file_conversations(file_path)
            continue
        if ext in {".txt", ".md"}:
            convo = _conversation_from_text_file(file_path)
            if convo is not None:
                yield convo


@dataclass(slots=True)
class SourceInputSummary:
    path: str
    kind: str
    is_valid: bool
    status: str
    issues: list[str]
    source_file_count: int = 0
    conversation_count: int = 0
    message_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "is_valid": self.is_valid,
            "status": self.status,
            "issues": list(self.issues),
            "source_file_count": self.source_file_count,
            "conversation_count": self.conversation_count,
            "message_count": self.message_count,
            "source": "archive",
        }


def summarize_source_input(path: str | Path) -> SourceInputSummary:
    source_path = Path(path).expanduser().resolve()
    if not source_path.exists():
        return SourceInputSummary(
            path=str(source_path),
            kind="invalid_corrupted",
            is_valid=False,
            status="blocked",
            issues=["path not found"],
        )
    if source_path.is_file() and source_path.suffix.lower() not in SUPPORTED_SOURCE_EXTENSIONS:
        return SourceInputSummary(
            path=str(source_path),
            kind="unsupported_input",
            is_valid=False,
            status="blocked",
            issues=[f"unsupported file extension: {source_path.suffix or '(none)'}"],
        )

    source_files = list(_iter_supported_files(source_path))
    if not source_files:
        issue = "no supported source files found"
        if source_path.is_file():
            issue = "unsupported file extension"
        return SourceInputSummary(
            path=str(source_path),
            kind="unsupported_input",
            is_valid=False,
            status="blocked",
            issues=[issue],
        )

    try:
        conversations = list(iter_source_conversations(source_path))
    except Exception as exc:
        return SourceInputSummary(
            path=str(source_path),
            kind="invalid_corrupted",
            is_valid=False,
            status="blocked",
            issues=[str(exc)],
            source_file_count=len(source_files),
        )

    message_count = 0
    for convo in conversations:
        messages = convo.get("messages") if isinstance(convo, dict) else []
        if isinstance(messages, list):
            message_count += sum(1 for row in messages if isinstance(row, dict))

    if source_path.is_dir():
        kind = "mixed_source_dir"
    elif source_path.suffix.lower() == ".jsonl":
        kind = "conversation_jsonl"
    elif source_path.suffix.lower() in {".txt", ".md"}:
        kind = "transcript_text"
    else:
        first_payload = None
        try:
            first_payload = json.loads(source_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            first_payload = None
        if isinstance(first_payload, dict) and isinstance(first_payload.get("conversations"), list):
            kind = "conversation_wrapper_json"
        else:
            kind = "conversation_export_json"

    issues: list[str] = []
    if not conversations:
        issues.append("no conversations found")
    if message_count == 0:
        issues.append("no messages found")

    return SourceInputSummary(
        path=str(source_path),
        kind=kind,
        is_valid=not issues,
        status="safe" if not issues else "blocked",
        issues=issues,
        source_file_count=len(source_files),
        conversation_count=len(conversations),
        message_count=message_count,
    )
