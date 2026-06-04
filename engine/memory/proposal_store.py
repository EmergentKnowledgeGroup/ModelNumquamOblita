from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path

from ..contracts import SourceRef, contract_to_dict, source_ref_from_dict

_SCHEMA_VERSION = 1


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _dedupe_key(*, kind: str, canonical_text: str, source_role: str, reason_code: str) -> str:
    payload = "|".join([kind, _normalize_text(canonical_text), source_role.strip().lower(), reason_code.strip().lower()])
    return sha256(payload.encode("utf-8")).hexdigest()


def _record_id(*, kind: str, canonical_text: str, source_role: str, reason_code: str) -> str:
    payload = "|".join([kind, _normalize_text(canonical_text), source_role.strip().lower(), reason_code.strip().lower()])
    return f"prop_{sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _event_id(*, event_type: str, record_id: str, reason: str, ordinal: int) -> str:
    payload = "|".join([event_type, record_id, reason.strip().lower(), str(int(ordinal))])
    return f"prevt_{sha256(payload.encode('utf-8')).hexdigest()[:16]}"


class ProposalKind(str, Enum):
    IDENTITY_SUMMARY = "identity_summary"
    RELATIONSHIP_SUMMARY = "relationship_summary"
    INFERRED_MOTIVE = "inferred_motive"
    OTHER_PERSON_INTERNAL_STATE = "other_person_internal_state"
    LIFE_STORY_CLAIM = "life_story_claim"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


class ProposalEventType(str, Enum):
    ADD = "ADD"
    REINFORCE = "REINFORCE"


@dataclass(slots=True)
class ProposalCandidate:
    kind: ProposalKind
    canonical_text: str
    source_refs: list[SourceRef]
    source_role: str
    session_id: str
    reason_code: str
    confidence: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.canonical_text = str(self.canonical_text or "").strip()
        self.source_role = str(self.source_role or "").strip().lower()
        self.session_id = str(self.session_id or "").strip()
        self.reason_code = str(self.reason_code or "").strip().lower()
        if not self.canonical_text:
            raise ValueError("canonical_text is required")
        if not self.source_refs:
            raise ValueError("source_refs is required")
        if self.source_role not in {"user", "assistant", "developer", "system", "tool"}:
            raise ValueError(f"unsupported source_role: {self.source_role}")
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.reason_code:
            raise ValueError("reason_code is required")
        value = float(self.confidence)
        if value < 0.0 or value > 1.0:
            raise ValueError("confidence must be in [0, 1]")
        self.confidence = value

    @property
    def dedupe_key(self) -> str:
        return _dedupe_key(
            kind=self.kind.value,
            canonical_text=self.canonical_text,
            source_role=self.source_role,
            reason_code=self.reason_code,
        )


@dataclass(slots=True)
class ProposalRecord:
    record_id: str
    kind: ProposalKind
    canonical_text: str
    source_refs: list[SourceRef]
    source_role: str
    session_id: str
    reason_code: str
    confidence: float
    reinforcement_count: int = 1
    status: ProposalStatus = ProposalStatus.PENDING
    memory_layer: str = "proposal_only"
    trust_tier: str = "proposal_pending"
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProposalEvent:
    event_id: str
    event_type: ProposalEventType
    record_id: str
    timestamp: datetime
    reason: str
    source_refs: list[SourceRef] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


def _build_record(candidate: ProposalCandidate, *, now: datetime) -> ProposalRecord:
    return ProposalRecord(
        record_id=_record_id(
            kind=candidate.kind.value,
            canonical_text=candidate.canonical_text,
            source_role=candidate.source_role,
            reason_code=candidate.reason_code,
        ),
        kind=candidate.kind,
        canonical_text=candidate.canonical_text,
        source_refs=list(candidate.source_refs),
        source_role=candidate.source_role,
        session_id=candidate.session_id,
        reason_code=candidate.reason_code,
        confidence=candidate.confidence,
        reinforcement_count=1,
        status=ProposalStatus.PENDING,
        created_at=now,
        updated_at=now,
        metadata=dict(candidate.metadata),
    )


class InMemoryProposalStore:
    def __init__(self) -> None:
        self._records: dict[str, ProposalRecord] = {}
        self._events: list[ProposalEvent] = []
        self._dedupe_index: dict[str, str] = {}

    def _append_event(
        self,
        *,
        event_type: ProposalEventType,
        record_id: str,
        reason: str,
        source_refs: list[SourceRef],
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._events.append(
            ProposalEvent(
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
        )

    def upsert_candidate(self, candidate: ProposalCandidate, *, reason: str) -> ProposalRecord:
        existing_id = self._dedupe_index.get(candidate.dedupe_key)
        if existing_id is not None:
            record = self._records[existing_id]
            record.source_refs.extend(candidate.source_refs)
            record.reinforcement_count += 1
            record.updated_at = _now_utc()
            record.confidence = max(record.confidence, candidate.confidence)
            self._append_event(
                event_type=ProposalEventType.REINFORCE,
                record_id=record.record_id,
                reason=reason,
                source_refs=candidate.source_refs,
                metadata={"dedupe_key": candidate.dedupe_key},
            )
            return record
        record = _build_record(candidate, now=_now_utc())
        self._records[record.record_id] = record
        self._dedupe_index[candidate.dedupe_key] = record.record_id
        self._append_event(
            event_type=ProposalEventType.ADD,
            record_id=record.record_id,
            reason=reason,
            source_refs=candidate.source_refs,
            metadata={"dedupe_key": candidate.dedupe_key},
        )
        return record

    def list_records(self) -> list[ProposalRecord]:
        return sorted(self._records.values(), key=lambda item: (item.created_at, item.record_id))

    def list_events(self) -> list[ProposalEvent]:
        return list(self._events)

    def diagnostics_snapshot(self) -> dict[str, int]:
        pending = sum(1 for record in self._records.values() if record.status is ProposalStatus.PENDING)
        reviewed = sum(1 for record in self._records.values() if record.status is ProposalStatus.REVIEWED)
        dismissed = sum(1 for record in self._records.values() if record.status is ProposalStatus.DISMISSED)
        return {
            "total_count": len(self._records),
            "pending_count": pending,
            "reviewed_count": reviewed,
            "dismissed_count": dismissed,
            "event_count": len(self._events),
        }

    def close(self) -> None:
        return None


class SqliteProposalStore:
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

    def _schema_version(self) -> int:
        with self._lock:
            row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def _init_schema(self) -> None:
        version = self._schema_version()
        if version not in {0, _SCHEMA_VERSION}:
            raise RuntimeError(f"unsupported proposal schema version: {version}")
        if version == _SCHEMA_VERSION:
            return
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proposal_records (
                    record_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    canonical_text TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    source_role TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reinforcement_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    memory_layer TEXT NOT NULL,
                    trust_tier TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS proposal_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                """
            )
            self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _serialize_refs(source_refs: list[SourceRef]) -> str:
        return json.dumps([contract_to_dict(ref) for ref in source_refs], ensure_ascii=False)

    @staticmethod
    def _serialize_metadata(metadata: dict[str, str]) -> str:
        return json.dumps(dict(metadata), ensure_ascii=False)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ProposalRecord:
        return ProposalRecord(
            record_id=str(row["record_id"]),
            kind=ProposalKind(str(row["kind"])),
            canonical_text=str(row["canonical_text"]),
            source_refs=[source_ref_from_dict(item) for item in json.loads(row["source_refs_json"] or "[]")],
            source_role=str(row["source_role"]),
            session_id=str(row["session_id"]),
            reason_code=str(row["reason_code"]),
            confidence=float(row["confidence"]),
            reinforcement_count=int(row["reinforcement_count"]),
            status=ProposalStatus(str(row["status"])),
            memory_layer=str(row["memory_layer"]),
            trust_tier=str(row["trust_tier"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            metadata={str(k): str(v) for k, v in json.loads(row["metadata_json"] or "{}").items()},
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ProposalEvent:
        return ProposalEvent(
            event_id=str(row["event_id"]),
            event_type=ProposalEventType(str(row["event_type"])),
            record_id=str(row["record_id"]),
            timestamp=datetime.fromisoformat(str(row["timestamp"])),
            reason=str(row["reason"]),
            source_refs=[source_ref_from_dict(item) for item in json.loads(row["source_refs_json"] or "[]")],
            metadata={str(k): str(v) for k, v in json.loads(row["metadata_json"] or "{}").items()},
        )

    def _append_event(
        self,
        *,
        event_type: ProposalEventType,
        record_id: str,
        reason: str,
        source_refs: list[SourceRef],
        metadata: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM proposal_events").fetchone()
            ordinal = int(row["count"]) + 1 if row else 1
        event = ProposalEvent(
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
                INSERT INTO proposal_events (
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

    def upsert_candidate(self, candidate: ProposalCandidate, *, reason: str) -> ProposalRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM proposal_records WHERE dedupe_key = ?",
                (candidate.dedupe_key,),
            ).fetchone()
        if row is not None:
            record = self._row_to_record(row)
            updated_refs = record.source_refs + list(candidate.source_refs)
            now = _now_utc()
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    UPDATE proposal_records
                    SET source_refs_json = ?, reinforcement_count = ?, confidence = ?, updated_at = ?
                    WHERE record_id = ?
                    """,
                    (
                        self._serialize_refs(updated_refs),
                        int(record.reinforcement_count) + 1,
                        max(record.confidence, candidate.confidence),
                        now.isoformat(),
                        record.record_id,
                    ),
                )
            self._append_event(
                event_type=ProposalEventType.REINFORCE,
                record_id=record.record_id,
                reason=reason,
                source_refs=candidate.source_refs,
                metadata={"dedupe_key": candidate.dedupe_key},
            )
            refreshed = self._records_for_id(record.record_id)
            if not refreshed:
                raise RuntimeError(f"proposal record missing after reinforce: {record.record_id}")
            return refreshed[0]

        record = _build_record(candidate, now=_now_utc())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO proposal_records (
                    record_id, kind, canonical_text, source_refs_json, source_role, session_id, reason_code,
                    confidence, reinforcement_count, status, memory_layer, trust_tier, created_at, updated_at,
                    metadata_json, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.kind.value,
                    record.canonical_text,
                    self._serialize_refs(record.source_refs),
                    record.source_role,
                    record.session_id,
                    record.reason_code,
                    record.confidence,
                    record.reinforcement_count,
                    record.status.value,
                    record.memory_layer,
                    record.trust_tier,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    self._serialize_metadata(record.metadata),
                    candidate.dedupe_key,
                ),
            )
        self._append_event(
            event_type=ProposalEventType.ADD,
            record_id=record.record_id,
            reason=reason,
            source_refs=candidate.source_refs,
            metadata={"dedupe_key": candidate.dedupe_key},
        )
        return record

    def _records_for_id(self, record_id: str) -> list[ProposalRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM proposal_records WHERE record_id = ?",
                (record_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_records(self) -> list[ProposalRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM proposal_records
                ORDER BY created_at ASC, record_id ASC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_events(self) -> list[ProposalEvent]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, event_type, record_id, timestamp, reason, source_refs_json, metadata_json
                FROM proposal_events
                ORDER BY seq ASC
                """
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def diagnostics_snapshot(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM proposal_records
                GROUP BY status
                """
            ).fetchall()
            event_row = self._conn.execute("SELECT COUNT(*) AS count FROM proposal_events").fetchone()
        counts = {
            "total_count": 0,
            "pending_count": 0,
            "reviewed_count": 0,
            "dismissed_count": 0,
            "event_count": int(event_row["count"]) if event_row else 0,
        }
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            counts["total_count"] += count
            if status == ProposalStatus.PENDING.value:
                counts["pending_count"] = count
            elif status == ProposalStatus.REVIEWED.value:
                counts["reviewed_count"] = count
            elif status == ProposalStatus.DISMISSED.value:
                counts["dismissed_count"] = count
        return counts


__all__ = [
    "InMemoryProposalStore",
    "ProposalCandidate",
    "ProposalEvent",
    "ProposalEventType",
    "ProposalKind",
    "ProposalRecord",
    "ProposalStatus",
    "SqliteProposalStore",
]
