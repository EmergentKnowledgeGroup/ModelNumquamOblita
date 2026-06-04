from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Optional

from ..contracts import SourceRef, contract_to_dict, source_ref_from_dict

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_SCHEMA_VERSION = 2


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _tokenize(value: str) -> list[str]:
    return _TOKEN_RE.findall(_normalize_text(value))


def _dedupe_key(*, kind: str, canonical_text: str, source_role: str) -> str:
    payload = "|".join([kind, _normalize_text(canonical_text), source_role.strip().lower()])
    return sha256(payload.encode("utf-8")).hexdigest()


def _record_id_for_candidate(
    *,
    kind: str,
    canonical_text: str,
    source_role: str,
    supersedes_record_id: str | None = None,
) -> str:
    payload = "|".join(
        [
            kind,
            _normalize_text(canonical_text),
            source_role.strip().lower(),
            supersedes_record_id or "",
        ]
    )
    return f"prov_{sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _event_id(
    *,
    event_type: str,
    record_id: str,
    reason: str,
    ordinal: int,
) -> str:
    payload = "|".join([event_type, record_id, reason.strip().lower(), str(int(ordinal))])
    return f"pevt_{sha256(payload.encode('utf-8')).hexdigest()[:16]}"


class ProvisionalMemoryKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    CORRECTION = "correction"
    PLAN = "plan"
    EVENT_NOTE = "event_note"
    SELF_CLAIM = "self_claim"


class ProvisionalMemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"


class ProvisionalMemoryEventType(str, Enum):
    ADD = "ADD"
    REINFORCE = "REINFORCE"
    SUPERSEDE = "SUPERSEDE"
    CONFLICT = "CONFLICT"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    ARCHIVE = "ARCHIVE"


@dataclass(slots=True)
class ProvisionalMemoryCandidate:
    kind: ProvisionalMemoryKind
    canonical_text: str
    source_refs: list[SourceRef]
    source_role: str
    session_id: str
    confidence: float = 0.0
    salience: float = 0.0
    stability: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_role = self.source_role.strip().lower()
        self.session_id = self.session_id.strip()
        self.canonical_text = self.canonical_text.strip()
        if not self.canonical_text:
            raise ValueError("canonical_text is required")
        if not self.source_refs:
            raise ValueError("source_refs is required")
        if not self.session_id:
            raise ValueError("session_id is required")
        if self.source_role not in {"user", "assistant", "developer", "system", "tool"}:
            raise ValueError(f"unsupported source_role: {self.source_role}")
        for field_name in ("confidence", "salience", "stability"):
            value = float(getattr(self, field_name))
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{field_name} must be in [0, 1]")
            setattr(self, field_name, value)

    @property
    def dedupe_key(self) -> str:
        return _dedupe_key(
            kind=self.kind.value,
            canonical_text=self.canonical_text,
            source_role=self.source_role,
        )


@dataclass(slots=True)
class ProvisionalMemoryRecord:
    record_id: str
    kind: ProvisionalMemoryKind
    canonical_text: str
    source_refs: list[SourceRef]
    source_role: str
    session_id: str
    confidence: float
    salience: float
    stability: float
    reinforcement_count: int = 1
    status: ProvisionalMemoryStatus = ProvisionalMemoryStatus.ACTIVE
    supersedes_record_id: Optional[str] = None
    superseded_by_record_id: Optional[str] = None
    conflict_with_record_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)
    last_reinforced_at: Optional[datetime] = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("record_id is required")
        if not self.canonical_text.strip():
            raise ValueError("canonical_text is required")
        if not self.source_refs:
            raise ValueError("source_refs is required")
        if self.reinforcement_count <= 0:
            raise ValueError("reinforcement_count must be > 0")
        for field_name in ("confidence", "salience", "stability"):
            value = float(getattr(self, field_name))
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{field_name} must be in [0, 1]")
            setattr(self, field_name, value)


@dataclass(slots=True)
class ProvisionalMemoryEvent:
    event_id: str
    event_type: ProvisionalMemoryEventType
    record_id: str
    timestamp: datetime
    reason: str
    source_refs: list[SourceRef] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProvisionalSearchHit:
    record: ProvisionalMemoryRecord
    score: float
    matched_terms: list[str] = field(default_factory=list)


def _session_ids_from_metadata(metadata: dict[str, str], *, fallback_session_id: str) -> list[str]:
    raw = str(dict(metadata or {}).get("session_ids_json") or "").strip()
    if not raw:
        return [fallback_session_id] if fallback_session_id else []
    try:
        payload = json.loads(raw)
    except Exception:
        payload = []
    if not isinstance(payload, list):
        return [fallback_session_id] if fallback_session_id else []
    return _dedupe_ids(
        [str(item).strip() for item in payload if str(item).strip()] + ([fallback_session_id] if fallback_session_id else [])
    )


def _metadata_with_session_ids(metadata: dict[str, str], session_id: str) -> dict[str, str]:
    session_ids = _session_ids_from_metadata(metadata, fallback_session_id=session_id)
    updated = dict(metadata or {})
    updated["session_ids_json"] = json.dumps(session_ids, ensure_ascii=False)
    updated["distinct_session_count"] = str(len(session_ids))
    return updated


def _build_record(
    candidate: ProvisionalMemoryCandidate,
    *,
    record_id: str,
    now: datetime,
    supersedes_record_id: str | None = None,
) -> ProvisionalMemoryRecord:
    metadata = _metadata_with_session_ids(dict(candidate.metadata), candidate.session_id)
    return ProvisionalMemoryRecord(
        record_id=record_id,
        kind=candidate.kind,
        canonical_text=candidate.canonical_text,
        source_refs=list(candidate.source_refs),
        source_role=candidate.source_role,
        session_id=candidate.session_id,
        confidence=candidate.confidence,
        salience=candidate.salience,
        stability=candidate.stability,
        reinforcement_count=1,
        status=ProvisionalMemoryStatus.ACTIVE,
        supersedes_record_id=supersedes_record_id,
        conflict_with_record_ids=[],
        created_at=now,
        updated_at=now,
        last_reinforced_at=now,
        metadata=metadata,
    )


def _score_record(record: ProvisionalMemoryRecord, query: str) -> tuple[float, list[str]]:
    query_tokens = set(_tokenize(query))
    text_tokens = set(_tokenize(record.canonical_text))
    if not query_tokens or not text_tokens:
        matched = []
        overlap = 0.0
    else:
        matched = sorted(query_tokens & text_tokens)
        overlap = float(len(matched)) / float(len(query_tokens))
    phrase_bonus = 0.25 if _normalize_text(query) and _normalize_text(query) in _normalize_text(record.canonical_text) else 0.0
    score = (
        overlap * 0.65
        + phrase_bonus
        + float(record.confidence) * 0.12
        + float(record.salience) * 0.13
        + float(record.stability) * 0.10
    )
    if record.status is ProvisionalMemoryStatus.CONFLICTED:
        score *= 0.94
    return min(1.0, max(0.0, score)), matched


_LIVE_STATUSES = {
    ProvisionalMemoryStatus.ACTIVE,
    ProvisionalMemoryStatus.CONFLICTED,
}


def _dedupe_ids(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


class InMemoryProvisionalMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, ProvisionalMemoryRecord] = {}
        self._events: list[ProvisionalMemoryEvent] = []
        self._dedupe_index: dict[str, str] = {}

    def _append_event(
        self,
        *,
        event_type: ProvisionalMemoryEventType,
        record_id: str,
        reason: str,
        source_refs: list[SourceRef],
        metadata: dict[str, str] | None = None,
    ) -> ProvisionalMemoryEvent:
        event = ProvisionalMemoryEvent(
            event_id=_event_id(
                event_type=event_type.value,
                record_id=record_id,
                reason=reason,
                ordinal=len(self._events) + 1,
            ),
            event_type=event_type,
            record_id=record_id,
            timestamp=_now_utc(),
            reason=reason,
            source_refs=list(source_refs),
            metadata=dict(metadata or {}),
        )
        self._events.append(event)
        return event

    def get_record(self, record_id: str) -> ProvisionalMemoryRecord:
        try:
            return self._records[record_id]
        except KeyError as exc:
            raise KeyError(f"unknown provisional record: {record_id}") from exc

    def list_records(self, *, status: str = "all") -> list[ProvisionalMemoryRecord]:
        normalized = str(status or "all").strip().lower() or "all"
        allowed = {"all", "live"} | {item.value for item in ProvisionalMemoryStatus}
        if normalized not in allowed:
            raise ValueError(f"unsupported provisional status filter: {status}")
        rows = list(self._records.values())
        if normalized == "live":
            rows = [record for record in rows if record.status in _LIVE_STATUSES]
        elif normalized != "all":
            rows = [record for record in rows if record.status.value == normalized]
        rows.sort(key=lambda item: (item.updated_at.isoformat(), item.record_id), reverse=True)
        return rows

    def upsert_candidate(
        self,
        candidate: ProvisionalMemoryCandidate,
        *,
        reason: str,
    ) -> ProvisionalMemoryRecord:
        existing_id = self._dedupe_index.get(candidate.dedupe_key)
        if existing_id:
            record = self.get_record(existing_id)
            if record.status in _LIVE_STATUSES:
                record.source_refs.extend(candidate.source_refs)
                record.reinforcement_count += 1
                record.updated_at = _now_utc()
                record.last_reinforced_at = record.updated_at
                record.confidence = max(record.confidence, candidate.confidence)
                record.salience = max(record.salience, candidate.salience)
                record.stability = max(record.stability, candidate.stability)
                record.metadata = _metadata_with_session_ids(record.metadata, candidate.session_id)
                self._append_event(
                    event_type=ProvisionalMemoryEventType.REINFORCE,
                    record_id=record.record_id,
                    reason=reason,
                    source_refs=candidate.source_refs,
                    metadata={"dedupe_key": candidate.dedupe_key},
                )
                return record
        now = _now_utc()
        record = _build_record(
            candidate,
            record_id=_record_id_for_candidate(
                kind=candidate.kind.value,
                canonical_text=candidate.canonical_text,
                source_role=candidate.source_role,
            ),
            now=now,
        )
        self._records[record.record_id] = record
        self._dedupe_index[candidate.dedupe_key] = record.record_id
        self._append_event(
            event_type=ProvisionalMemoryEventType.ADD,
            record_id=record.record_id,
            reason=reason,
            source_refs=candidate.source_refs,
            metadata={"dedupe_key": candidate.dedupe_key},
        )
        return record

    def mark_conflict(
        self,
        record_id: str,
        other_record_id: str,
        *,
        reason: str,
    ) -> tuple[ProvisionalMemoryRecord, ProvisionalMemoryRecord]:
        left = self.get_record(record_id)
        right = self.get_record(other_record_id)
        if left.record_id == right.record_id:
            raise ValueError("conflict requires two distinct provisional records")
        if left.status not in _LIVE_STATUSES or right.status not in _LIVE_STATUSES:
            raise ValueError("only live provisional records can be marked conflicted")
        now = _now_utc()
        left.conflict_with_record_ids = _dedupe_ids(list(left.conflict_with_record_ids) + [right.record_id])
        right.conflict_with_record_ids = _dedupe_ids(list(right.conflict_with_record_ids) + [left.record_id])
        left.status = ProvisionalMemoryStatus.CONFLICTED
        right.status = ProvisionalMemoryStatus.CONFLICTED
        left.updated_at = now
        right.updated_at = now
        self._append_event(
            event_type=ProvisionalMemoryEventType.CONFLICT,
            record_id=left.record_id,
            reason=reason,
            source_refs=right.source_refs,
            metadata={"other_record_id": right.record_id},
        )
        self._append_event(
            event_type=ProvisionalMemoryEventType.CONFLICT,
            record_id=right.record_id,
            reason=reason,
            source_refs=left.source_refs,
            metadata={"other_record_id": left.record_id},
        )
        return left, right

    def supersede_record(
        self,
        record_id: str,
        replacement_candidate: ProvisionalMemoryCandidate,
        *,
        reason: str,
    ) -> ProvisionalMemoryRecord:
        previous = self.get_record(record_id)
        previous.status = ProvisionalMemoryStatus.SUPERSEDED
        previous.updated_at = _now_utc()
        replacement = _build_record(
            replacement_candidate,
            record_id=_record_id_for_candidate(
                kind=replacement_candidate.kind.value,
                canonical_text=replacement_candidate.canonical_text,
                source_role=replacement_candidate.source_role,
                supersedes_record_id=previous.record_id,
            ),
            now=_now_utc(),
            supersedes_record_id=previous.record_id,
        )
        previous.superseded_by_record_id = replacement.record_id
        replacement.conflict_with_record_ids = list(previous.conflict_with_record_ids)
        replacement.metadata = _metadata_with_session_ids(
            dict(previous.metadata) | dict(replacement.metadata),
            replacement_candidate.session_id,
        )
        if replacement.conflict_with_record_ids:
            replacement.status = ProvisionalMemoryStatus.CONFLICTED
            replacement.updated_at = previous.updated_at
            for neighbor_id in replacement.conflict_with_record_ids:
                neighbor = self._records.get(neighbor_id)
                if neighbor is None:
                    continue
                neighbor.conflict_with_record_ids = _dedupe_ids(
                    [
                        replacement.record_id if value == previous.record_id else value
                        for value in list(neighbor.conflict_with_record_ids)
                    ]
                    + [replacement.record_id]
                )
                neighbor.status = ProvisionalMemoryStatus.CONFLICTED
                neighbor.updated_at = previous.updated_at
        self._records[replacement.record_id] = replacement
        self._dedupe_index[replacement_candidate.dedupe_key] = replacement.record_id
        self._append_event(
            event_type=ProvisionalMemoryEventType.SUPERSEDE,
            record_id=previous.record_id,
            reason=reason,
            source_refs=replacement_candidate.source_refs,
            metadata={"replacement_record_id": replacement.record_id},
        )
        self._append_event(
            event_type=ProvisionalMemoryEventType.ADD,
            record_id=replacement.record_id,
            reason=reason,
            source_refs=replacement_candidate.source_refs,
            metadata={"supersedes_record_id": previous.record_id},
        )
        return replacement

    def record_near_duplicate(
        self,
        *,
        record_id: str,
        other_record_id: str,
        similarity_score: float,
        metadata: dict[str, str] | None = None,
    ) -> ProvisionalMemoryEvent:
        record = self.get_record(record_id)
        other = self.get_record(other_record_id)
        return self._append_event(
            event_type=ProvisionalMemoryEventType.NEAR_DUPLICATE,
            record_id=record.record_id,
            reason="near_duplicate_detected",
            source_refs=list(other.source_refs),
            metadata={
                "other_record_id": other.record_id,
                "similarity_score": f"{max(0.0, min(1.0, float(similarity_score))):.4f}",
                **dict(metadata or {}),
            },
        )

    def search(self, query: str, *, limit: int = 10) -> list[ProvisionalSearchHit]:
        hits: list[ProvisionalSearchHit] = []
        for record in self._records.values():
            if record.status not in _LIVE_STATUSES:
                continue
            score, matched = _score_record(record, query)
            if score <= 0.0 and matched == []:
                continue
            hits.append(ProvisionalSearchHit(record=record, score=score, matched_terms=matched))
        hits.sort(key=lambda hit: (-hit.score, hit.record.created_at.isoformat(), hit.record.record_id))
        return hits[: max(1, int(limit))]

    def list_events(
        self,
        *,
        record_id: str | None = None,
        event_type: ProvisionalMemoryEventType | None = None,
    ) -> list[ProvisionalMemoryEvent]:
        rows = list(self._events)
        if record_id is not None:
            rows = [event for event in rows if event.record_id == record_id]
        if event_type is not None:
            rows = [event for event in rows if event.event_type is event_type]
        return rows

    def diagnostics_snapshot(self) -> dict[str, int]:
        active_count = 0
        superseded_count = 0
        conflicted_count = 0
        archived_count = 0
        for record in self._records.values():
            if record.status is ProvisionalMemoryStatus.ACTIVE:
                active_count += 1
            elif record.status is ProvisionalMemoryStatus.SUPERSEDED:
                superseded_count += 1
            elif record.status is ProvisionalMemoryStatus.CONFLICTED:
                conflicted_count += 1
            elif record.status is ProvisionalMemoryStatus.ARCHIVED:
                archived_count += 1
        return {
            "total_count": len(self._records),
            "active_count": active_count,
            "superseded_count": superseded_count,
            "conflicted_count": conflicted_count,
            "archived_count": archived_count,
            "event_count": len(self._events),
        }

    def close(self) -> None:
        return None


class SqliteProvisionalMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _schema_version(self) -> int:
        with self._lock:
            row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def _init_schema(self) -> None:
        version = self._schema_version()
        if version not in {0, _SCHEMA_VERSION}:
            raise RuntimeError(f"unsupported provisional schema version: {version}")
        if version == _SCHEMA_VERSION:
            return
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS provisional_records (
                    record_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    canonical_text TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    source_role TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    salience REAL NOT NULL,
                    stability REAL NOT NULL,
                    reinforcement_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    supersedes_record_id TEXT,
                    superseded_by_record_id TEXT,
                    conflict_with_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_reinforced_at TEXT,
                    metadata_json TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS provisional_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_provisional_status ON provisional_records(status);
                CREATE INDEX IF NOT EXISTS idx_provisional_updated_at ON provisional_records(updated_at);
                CREATE INDEX IF NOT EXISTS idx_provisional_events_record ON provisional_events(record_id);
                """
            )
            self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    @staticmethod
    def _serialize_refs(source_refs: list[SourceRef]) -> str:
        return json.dumps([contract_to_dict(ref) for ref in source_refs], ensure_ascii=False)

    @staticmethod
    def _serialize_metadata(metadata: dict[str, str]) -> str:
        return json.dumps(dict(metadata), ensure_ascii=False)

    @staticmethod
    def _serialize_conflicts(values: list[str]) -> str:
        return json.dumps(_dedupe_ids(list(values)), ensure_ascii=False)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ProvisionalMemoryRecord:
        return ProvisionalMemoryRecord(
            record_id=str(row["record_id"]),
            kind=ProvisionalMemoryKind(str(row["kind"])),
            canonical_text=str(row["canonical_text"]),
            source_refs=[source_ref_from_dict(item) for item in json.loads(row["source_refs_json"] or "[]")],
            source_role=str(row["source_role"]),
            session_id=str(row["session_id"]),
            confidence=float(row["confidence"]),
            salience=float(row["salience"]),
            stability=float(row["stability"]),
            reinforcement_count=int(row["reinforcement_count"]),
            status=ProvisionalMemoryStatus(str(row["status"])),
            supersedes_record_id=row["supersedes_record_id"],
            superseded_by_record_id=row["superseded_by_record_id"],
            conflict_with_record_ids=[str(item).strip() for item in json.loads(row["conflict_with_json"] or "[]") if str(item).strip()],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            last_reinforced_at=datetime.fromisoformat(str(row["last_reinforced_at"])) if row["last_reinforced_at"] else None,
            metadata={str(k): str(v) for k, v in json.loads(row["metadata_json"] or "{}").items()},
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ProvisionalMemoryEvent:
        return ProvisionalMemoryEvent(
            event_id=str(row["event_id"]),
            event_type=ProvisionalMemoryEventType(str(row["event_type"])),
            record_id=str(row["record_id"]),
            timestamp=datetime.fromisoformat(str(row["timestamp"])),
            reason=str(row["reason"]),
            source_refs=[source_ref_from_dict(item) for item in json.loads(row["source_refs_json"] or "[]")],
            metadata={str(k): str(v) for k, v in json.loads(row["metadata_json"] or "{}").items()},
        )

    def _append_event(
        self,
        *,
        event_type: ProvisionalMemoryEventType,
        record_id: str,
        reason: str,
        source_refs: list[SourceRef],
        metadata: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM provisional_events").fetchone()
            ordinal = int(row["count"]) + 1 if row else 1
        event = ProvisionalMemoryEvent(
            event_id=_event_id(
                event_type=event_type.value,
                record_id=record_id,
                reason=reason,
                ordinal=ordinal,
            ),
            event_type=event_type,
            record_id=record_id,
            timestamp=_now_utc(),
            reason=reason,
            source_refs=list(source_refs),
            metadata=dict(metadata or {}),
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO provisional_events (
                    event_id, event_type, record_id, timestamp, reason, source_refs_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.record_id,
                    event.timestamp.isoformat(),
                    event.reason,
                    self._serialize_refs(event.source_refs),
                    self._serialize_metadata(event.metadata),
                ),
            )

    def get_record(self, record_id: str) -> ProvisionalMemoryRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM provisional_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown provisional record: {record_id}")
        return self._row_to_record(row)

    def list_records(self, *, status: str = "all") -> list[ProvisionalMemoryRecord]:
        normalized = str(status or "all").strip().lower() or "all"
        allowed = {"all", "live"} | {item.value for item in ProvisionalMemoryStatus}
        if normalized not in allowed:
            raise ValueError(f"unsupported provisional status filter: {status}")
        if normalized == "all":
            query = "SELECT * FROM provisional_records ORDER BY updated_at DESC, record_id ASC"
            params: tuple[object, ...] = ()
        elif normalized == "live":
            query = (
                "SELECT * FROM provisional_records WHERE status IN (?, ?) "
                "ORDER BY updated_at DESC, record_id ASC"
            )
            params = (
                ProvisionalMemoryStatus.ACTIVE.value,
                ProvisionalMemoryStatus.CONFLICTED.value,
            )
        else:
            query = "SELECT * FROM provisional_records WHERE status = ? ORDER BY updated_at DESC, record_id ASC"
            params = (normalized,)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def upsert_candidate(
        self,
        candidate: ProvisionalMemoryCandidate,
        *,
        reason: str,
    ) -> ProvisionalMemoryRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM provisional_records WHERE dedupe_key = ?",
                (candidate.dedupe_key,),
            ).fetchone()
        if row is not None:
            record = self._row_to_record(row)
            if record.status in _LIVE_STATUSES:
                now = _now_utc()
                updated_refs = record.source_refs + list(candidate.source_refs)
                updated_confidence = max(record.confidence, candidate.confidence)
                updated_salience = max(record.salience, candidate.salience)
                updated_stability = max(record.stability, candidate.stability)
                updated_metadata = _metadata_with_session_ids(record.metadata, candidate.session_id)
                with self._lock, self._conn:
                    self._conn.execute(
                        """
                        UPDATE provisional_records
                        SET source_refs_json = ?, reinforcement_count = ?, confidence = ?, salience = ?,
                            stability = ?, updated_at = ?, last_reinforced_at = ?, metadata_json = ?
                        WHERE record_id = ?
                        """,
                        (
                            self._serialize_refs(updated_refs),
                            int(record.reinforcement_count) + 1,
                            updated_confidence,
                            updated_salience,
                            updated_stability,
                            now.isoformat(),
                            now.isoformat(),
                            self._serialize_metadata(updated_metadata),
                            record.record_id,
                        ),
                    )
                self._append_event(
                    event_type=ProvisionalMemoryEventType.REINFORCE,
                    record_id=record.record_id,
                    reason=reason,
                    source_refs=candidate.source_refs,
                    metadata={"dedupe_key": candidate.dedupe_key},
                )
                return self.get_record(record.record_id)

        now = _now_utc()
        record = _build_record(
            candidate,
            record_id=_record_id_for_candidate(
                kind=candidate.kind.value,
                canonical_text=candidate.canonical_text,
                source_role=candidate.source_role,
            ),
            now=now,
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO provisional_records (
                    record_id, kind, canonical_text, source_refs_json, source_role, session_id, confidence,
                    salience, stability, reinforcement_count, status, supersedes_record_id,
                    superseded_by_record_id, conflict_with_json, created_at, updated_at, last_reinforced_at, metadata_json, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.kind.value,
                    record.canonical_text,
                    self._serialize_refs(record.source_refs),
                    record.source_role,
                    record.session_id,
                    record.confidence,
                    record.salience,
                    record.stability,
                    record.reinforcement_count,
                    record.status.value,
                    record.supersedes_record_id,
                    record.superseded_by_record_id,
                    self._serialize_conflicts(record.conflict_with_record_ids),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.last_reinforced_at.isoformat() if record.last_reinforced_at else None,
                    self._serialize_metadata(record.metadata),
                    candidate.dedupe_key,
                ),
            )
        self._append_event(
            event_type=ProvisionalMemoryEventType.ADD,
            record_id=record.record_id,
            reason=reason,
            source_refs=candidate.source_refs,
            metadata={"dedupe_key": candidate.dedupe_key},
        )
        return self.get_record(record.record_id)

    def mark_conflict(
        self,
        record_id: str,
        other_record_id: str,
        *,
        reason: str,
    ) -> tuple[ProvisionalMemoryRecord, ProvisionalMemoryRecord]:
        left = self.get_record(record_id)
        right = self.get_record(other_record_id)
        if left.record_id == right.record_id:
            raise ValueError("conflict requires two distinct provisional records")
        if left.status not in _LIVE_STATUSES or right.status not in _LIVE_STATUSES:
            raise ValueError("only live provisional records can be marked conflicted")
        now = _now_utc().isoformat()
        left_conflicts = _dedupe_ids(list(left.conflict_with_record_ids) + [right.record_id])
        right_conflicts = _dedupe_ids(list(right.conflict_with_record_ids) + [left.record_id])
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE provisional_records
                SET status = ?, conflict_with_json = ?, updated_at = ?
                WHERE record_id = ?
                """,
                (
                    ProvisionalMemoryStatus.CONFLICTED.value,
                    self._serialize_conflicts(left_conflicts),
                    now,
                    left.record_id,
                ),
            )
            self._conn.execute(
                """
                UPDATE provisional_records
                SET status = ?, conflict_with_json = ?, updated_at = ?
                WHERE record_id = ?
                """,
                (
                    ProvisionalMemoryStatus.CONFLICTED.value,
                    self._serialize_conflicts(right_conflicts),
                    now,
                    right.record_id,
                ),
            )
        self._append_event(
            event_type=ProvisionalMemoryEventType.CONFLICT,
            record_id=left.record_id,
            reason=reason,
            source_refs=right.source_refs,
            metadata={"other_record_id": right.record_id},
        )
        self._append_event(
            event_type=ProvisionalMemoryEventType.CONFLICT,
            record_id=right.record_id,
            reason=reason,
            source_refs=left.source_refs,
            metadata={"other_record_id": left.record_id},
        )
        return self.get_record(left.record_id), self.get_record(right.record_id)

    def supersede_record(
        self,
        record_id: str,
        replacement_candidate: ProvisionalMemoryCandidate,
        *,
        reason: str,
    ) -> ProvisionalMemoryRecord:
        previous = self.get_record(record_id)
        replacement = _build_record(
            replacement_candidate,
            record_id=_record_id_for_candidate(
                kind=replacement_candidate.kind.value,
                canonical_text=replacement_candidate.canonical_text,
                source_role=replacement_candidate.source_role,
                supersedes_record_id=previous.record_id,
            ),
            now=_now_utc(),
            supersedes_record_id=previous.record_id,
        )
        replacement.conflict_with_record_ids = list(previous.conflict_with_record_ids)
        replacement.metadata = _metadata_with_session_ids(
            dict(previous.metadata) | dict(replacement.metadata),
            replacement_candidate.session_id,
        )
        if replacement.conflict_with_record_ids:
            replacement.status = ProvisionalMemoryStatus.CONFLICTED
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE provisional_records
                SET status = ?, superseded_by_record_id = ?, updated_at = ?
                WHERE record_id = ?
                """,
                (
                    ProvisionalMemoryStatus.SUPERSEDED.value,
                    replacement.record_id,
                    _now_utc().isoformat(),
                    previous.record_id,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO provisional_records (
                    record_id, kind, canonical_text, source_refs_json, source_role, session_id, confidence,
                    salience, stability, reinforcement_count, status, supersedes_record_id,
                    superseded_by_record_id, conflict_with_json, created_at, updated_at, last_reinforced_at, metadata_json, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    replacement.record_id,
                    replacement.kind.value,
                    replacement.canonical_text,
                    self._serialize_refs(replacement.source_refs),
                    replacement.source_role,
                    replacement.session_id,
                    replacement.confidence,
                    replacement.salience,
                    replacement.stability,
                    replacement.reinforcement_count,
                    replacement.status.value,
                    replacement.supersedes_record_id,
                    replacement.superseded_by_record_id,
                    self._serialize_conflicts(replacement.conflict_with_record_ids),
                    replacement.created_at.isoformat(),
                    replacement.updated_at.isoformat(),
                    replacement.last_reinforced_at.isoformat() if replacement.last_reinforced_at else None,
                    self._serialize_metadata(replacement.metadata),
                    replacement_candidate.dedupe_key,
                ),
            )
            if replacement.conflict_with_record_ids:
                for neighbor_id in replacement.conflict_with_record_ids:
                    row = self._conn.execute(
                        "SELECT conflict_with_json FROM provisional_records WHERE record_id = ?",
                        (neighbor_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    neighbor_conflicts = [
                        replacement.record_id if str(item).strip() == previous.record_id else str(item).strip()
                        for item in json.loads(row["conflict_with_json"] or "[]")
                    ]
                    neighbor_conflicts = _dedupe_ids(neighbor_conflicts + [replacement.record_id])
                    self._conn.execute(
                        """
                        UPDATE provisional_records
                        SET status = ?, conflict_with_json = ?, updated_at = ?
                        WHERE record_id = ?
                        """,
                        (
                            ProvisionalMemoryStatus.CONFLICTED.value,
                            self._serialize_conflicts(neighbor_conflicts),
                            replacement.updated_at.isoformat(),
                            neighbor_id,
                        ),
                    )
        self._append_event(
            event_type=ProvisionalMemoryEventType.SUPERSEDE,
            record_id=previous.record_id,
            reason=reason,
            source_refs=replacement_candidate.source_refs,
            metadata={"replacement_record_id": replacement.record_id},
        )
        self._append_event(
            event_type=ProvisionalMemoryEventType.ADD,
            record_id=replacement.record_id,
            reason=reason,
            source_refs=replacement_candidate.source_refs,
            metadata={"supersedes_record_id": previous.record_id},
        )
        return self.get_record(replacement.record_id)

    def record_near_duplicate(
        self,
        *,
        record_id: str,
        other_record_id: str,
        similarity_score: float,
        metadata: dict[str, str] | None = None,
    ) -> ProvisionalMemoryEvent:
        record = self.get_record(record_id)
        other = self.get_record(other_record_id)
        event = ProvisionalMemoryEvent(
            event_id=_event_id(
                event_type=ProvisionalMemoryEventType.NEAR_DUPLICATE.value,
                record_id=record.record_id,
                reason="near_duplicate_detected",
                ordinal=len(self.list_events()) + 1,
            ),
            event_type=ProvisionalMemoryEventType.NEAR_DUPLICATE,
            record_id=record.record_id,
            timestamp=_now_utc(),
            reason="near_duplicate_detected",
            source_refs=list(other.source_refs),
            metadata={
                "other_record_id": other.record_id,
                "similarity_score": f"{max(0.0, min(1.0, float(similarity_score))):.4f}",
                **dict(metadata or {}),
            },
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO provisional_events (
                    event_id, event_type, record_id, timestamp, reason, source_refs_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.record_id,
                    event.timestamp.isoformat(),
                    event.reason,
                    self._serialize_refs(event.source_refs),
                    self._serialize_metadata(event.metadata),
                ),
            )
        return event

    def search(self, query: str, *, limit: int = 10) -> list[ProvisionalSearchHit]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM provisional_records
                WHERE status IN (?, ?)
                ORDER BY updated_at DESC, record_id ASC
                """,
                (
                    ProvisionalMemoryStatus.ACTIVE.value,
                    ProvisionalMemoryStatus.CONFLICTED.value,
                ),
            ).fetchall()
        hits: list[ProvisionalSearchHit] = []
        for row in rows:
            record = self._row_to_record(row)
            score, matched = _score_record(record, query)
            if score <= 0.0 and matched == []:
                continue
            hits.append(ProvisionalSearchHit(record=record, score=score, matched_terms=matched))
        hits.sort(key=lambda hit: (-hit.score, hit.record.created_at.isoformat(), hit.record.record_id))
        return hits[: max(1, int(limit))]

    def list_events(
        self,
        *,
        record_id: str | None = None,
        event_type: ProvisionalMemoryEventType | None = None,
    ) -> list[ProvisionalMemoryEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if record_id is not None:
            clauses.append("record_id = ?")
            params.append(record_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type.value)
        query = """
            SELECT event_id, event_type, record_id, timestamp, reason, source_refs_json, metadata_json
            FROM provisional_events
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY seq ASC"
        with self._lock:
            rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_event(row) for row in rows]

    def diagnostics_snapshot(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM provisional_records
                GROUP BY status
                """
            ).fetchall()
            event_row = self._conn.execute("SELECT COUNT(*) AS count FROM provisional_events").fetchone()
        counts = {
            "total_count": 0,
            "active_count": 0,
            "superseded_count": 0,
            "conflicted_count": 0,
            "archived_count": 0,
            "event_count": int(event_row["count"]) if event_row else 0,
        }
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            counts["total_count"] += count
            if status == ProvisionalMemoryStatus.ACTIVE.value:
                counts["active_count"] = count
            elif status == ProvisionalMemoryStatus.SUPERSEDED.value:
                counts["superseded_count"] = count
            elif status == ProvisionalMemoryStatus.CONFLICTED.value:
                counts["conflicted_count"] = count
            elif status == ProvisionalMemoryStatus.ARCHIVED.value:
                counts["archived_count"] = count
        return counts


__all__ = [
    "InMemoryProvisionalMemoryStore",
    "ProvisionalMemoryCandidate",
    "ProvisionalMemoryEvent",
    "ProvisionalMemoryEventType",
    "ProvisionalMemoryKind",
    "ProvisionalMemoryRecord",
    "ProvisionalMemoryStatus",
    "ProvisionalSearchHit",
    "SqliteProvisionalMemoryStore",
]
