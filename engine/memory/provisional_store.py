from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Optional

from ..contracts import SourceRef, contract_to_dict, source_ref_from_dict
from .content_safety import SecretDetectedError, assert_safe_content, scrub_content

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_SCHEMA_VERSION = 3
_MAX_COMPLETED_MAINTENANCE_RUNS = 256


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
    DORMANT = "dormant"


class ProvisionalAuthorityTier(str, Enum):
    """Authority remains independent from maturity and lifecycle."""

    OBSERVED = "provisional_observed"
    CONSOLIDATED = "provisional_consolidated"


class ProvisionalMaturity(str, Enum):
    OBSERVED = "observed"
    REINFORCED = "reinforced"
    CONSOLIDATED = "consolidated"


class ProvisionalLifecycle(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    ARCHIVED = "archived"


class SourceRole(str, Enum):
    USER = "user"
    TOOL = "tool"
    EXTERNAL = "external"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    DEVELOPER = "developer"


class ProvisionalMemoryEventType(str, Enum):
    ADD = "ADD"
    REINFORCE = "REINFORCE"
    SUPERSEDE = "SUPERSEDE"
    CONFLICT = "CONFLICT"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    ARCHIVE = "ARCHIVE"
    CONSOLIDATE = "CONSOLIDATE"
    DORMANT = "DORMANT"
    REACTIVATE = "REACTIVATE"


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
    source_id: str = ""
    message_id: str = ""
    span_start: int = 0
    span_end: int = 0
    content: str = ""

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
        if self.source_role not in {"user", "assistant", "developer", "system", "tool", "external"}:
            raise ValueError(f"unsupported source_role: {self.source_role}")
        for field_name in ("confidence", "salience", "stability"):
            value = float(getattr(self, field_name))
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{field_name} must be in [0, 1]")
            setattr(self, field_name, value)

        if self.span_start < 0 or self.span_end < self.span_start:
            raise ValueError("invalid source span")

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
    authority_tier: ProvisionalAuthorityTier = ProvisionalAuthorityTier.OBSERVED
    maturity: ProvisionalMaturity = ProvisionalMaturity.OBSERVED
    lifecycle: ProvisionalLifecycle = ProvisionalLifecycle.ACTIVE
    derived: bool = False
    input_record_ids: list[str] = field(default_factory=list)
    independent_support_count: int = 0
    distinct_session_count: int = 0
    last_independent_support_at: Optional[datetime] = None
    policy_version: str = "v0.2"
    claim_key: str = ""

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


@dataclass(frozen=True, slots=True)
class EvidenceRegistration:
    source_id: str
    message_id: str
    source_role: str
    content_digest: str
    session_id: str
    handle: str


@dataclass(frozen=True, slots=True)
class ObservationDisposition:
    record_id: str
    support_delta: int
    evidence_fingerprint: str | None
    reason: str


def _content_digest(value: str) -> str:
    assert_safe_content(value)
    return sha256(_normalize_text(value).encode("utf-8")).hexdigest()


def _evidence_fingerprint(
    *, store_uuid: str, source_id: str, message_id: str, span_start: int, span_end: int, source_role: str, content_digest: str
) -> str:
    payload = "|".join((store_uuid, source_id, message_id, str(span_start), str(span_end), source_role, content_digest))
    return sha256(payload.encode("utf-8")).hexdigest()


def source_role_eligible(source_role: str, *, kind: ProvisionalMemoryKind, registered: bool, assistant_receipt_valid: bool = False) -> bool:
    """Policy primitive; authority is granted only to registered evidence."""
    role = str(source_role).strip().lower()
    if role in {SourceRole.USER.value, SourceRole.TOOL.value, SourceRole.EXTERNAL.value}:
        return bool(registered)
    if role == SourceRole.ASSISTANT.value:
        return kind is ProvisionalMemoryKind.SELF_CLAIM and bool(assistant_receipt_valid)
    return False


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
        claim_key=_dedupe_key(
            kind=candidate.kind.value,
            canonical_text=candidate.canonical_text,
            source_role=candidate.source_role,
        ),
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
    def __init__(
        self,
        db_path: str | Path,
        *,
        scrub_legacy_secrets: bool = False,
        scrub_authorized_by: str | None = None,
        legacy_backup_path: str | Path | None = None,
        clock=None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        legacy_version, legacy_secret_detected = self._preflight_legacy_store(self.db_path)
        normalized_reviewer = str(scrub_authorized_by or "").strip()
        verified_backup: Path | None = None
        if legacy_version == 2 and legacy_secret_detected:
            if not scrub_legacy_secrets:
                raise SecretDetectedError()
            if not normalized_reviewer:
                raise ValueError("SCRUB_REVIEW_AUTHORIZATION_REQUIRED")
            if legacy_backup_path is None:
                raise ValueError("SCRUB_BACKUP_REQUIRED")
            verified_backup = self._backup_and_verify_legacy_store(
                self.db_path,
                Path(legacy_backup_path),
            )
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._clock = clock or _now_utc
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema(
            scrub_legacy_secrets=scrub_legacy_secrets and legacy_secret_detected,
            scrub_authorized_by=normalized_reviewer or None,
            verified_backup=verified_backup,
        )

    @staticmethod
    def _read_only_connection(db_path: Path) -> sqlite3.Connection:
        uri = f"{db_path.expanduser().resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def _preflight_legacy_store(cls, db_path: Path) -> tuple[int, bool]:
        """Inspect v2 content before any writable SQLite connection is opened."""
        if not db_path.exists() or db_path.stat().st_size == 0:
            return 0, False
        with cls._read_only_connection(db_path) as source:
            version_row = source.execute("PRAGMA user_version").fetchone()
            version = int(version_row[0]) if version_row else 0
            if version != 2:
                return version, False
            try:
                for row in source.execute(
                    "SELECT canonical_text, metadata_json, source_refs_json FROM provisional_records"
                ):
                    assert_safe_content(
                        [
                            str(row["canonical_text"]),
                            json.loads(row["metadata_json"] or "{}"),
                            json.loads(row["source_refs_json"] or "[]"),
                        ]
                    )
                for row in source.execute(
                    "SELECT source_refs_json, metadata_json, reason FROM provisional_events"
                ):
                    assert_safe_content(
                        [
                            json.loads(row["source_refs_json"] or "[]"),
                            json.loads(row["metadata_json"] or "{}"),
                            str(row["reason"]),
                        ]
                    )
            except SecretDetectedError:
                return version, True
        return version, False

    @classmethod
    def _backup_and_verify_legacy_store(cls, source_path: Path, target_path: Path) -> Path:
        """Create and structurally verify the mandatory pre-scrub v2 backup."""
        source = source_path.expanduser().resolve()
        target = target_path.expanduser().resolve()
        if source == target:
            raise ValueError("legacy backup target must differ from the live store")
        if target.exists():
            raise FileExistsError("legacy backup target already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        with cls._read_only_connection(source) as source_conn, sqlite3.connect(str(target)) as destination:
            source_counts = (
                int(source_conn.execute("SELECT COUNT(*) FROM provisional_records").fetchone()[0]),
                int(source_conn.execute("SELECT COUNT(*) FROM provisional_events").fetchone()[0]),
            )
            source_conn.backup(destination)
        with sqlite3.connect(str(target)) as backup:
            backup_version = int(backup.execute("PRAGMA user_version").fetchone()[0])
            integrity = str(backup.execute("PRAGMA integrity_check").fetchone()[0])
            backup_counts = (
                int(backup.execute("SELECT COUNT(*) FROM provisional_records").fetchone()[0]),
                int(backup.execute("SELECT COUNT(*) FROM provisional_events").fetchone()[0]),
            )
        if backup_version != 2 or integrity.lower() != "ok" or backup_counts != source_counts:
            raise RuntimeError("LEGACY_BACKUP_VERIFICATION_FAILED")
        return target

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def backup_to(self, target_path: str | Path) -> Path:
        """Create a transactionally consistent SQLite backup of the live sidecar."""
        target = Path(target_path).expanduser().resolve()
        source = self.db_path.expanduser().resolve()
        if target == source:
            raise ValueError("backup target must differ from the live store")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(str(target)) as destination:
            self._conn.backup(destination)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

    def _schema_version(self) -> int:
        with self._lock:
            row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def _init_schema(
        self,
        *,
        scrub_legacy_secrets: bool = False,
        scrub_authorized_by: str | None = None,
        verified_backup: Path | None = None,
    ) -> None:
        version = self._schema_version()
        if version not in {0, 2, _SCHEMA_VERSION}:
            raise RuntimeError(f"unsupported provisional schema version: {version}")
        if version == _SCHEMA_VERSION:
            self._ensure_maintenance_schema()
            return
        if version == 2:
            self._migrate_v2_to_v3(
                scrub_legacy_secrets=scrub_legacy_secrets,
                scrub_authorized_by=scrub_authorized_by,
                verified_backup=verified_backup,
            )
            self._ensure_maintenance_schema()
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
                    dedupe_key TEXT NOT NULL UNIQUE,
                    authority_tier TEXT NOT NULL DEFAULT 'provisional_observed',
                    maturity TEXT NOT NULL DEFAULT 'observed',
                    lifecycle TEXT NOT NULL DEFAULT 'active',
                    derived INTEGER NOT NULL DEFAULT 0,
                    input_record_ids_json TEXT NOT NULL DEFAULT '[]',
                    independent_support_count INTEGER NOT NULL DEFAULT 0,
                    distinct_session_count INTEGER NOT NULL DEFAULT 0,
                    last_independent_support_at TEXT,
                    policy_version TEXT NOT NULL DEFAULT 'v0.2',
                    claim_key TEXT NOT NULL DEFAULT ''
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
                CREATE TABLE IF NOT EXISTS provisional_evidence_units (
                    evidence_fingerprint TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    span_start INTEGER NOT NULL,
                    span_end INTEGER NOT NULL,
                    source_role TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    registered INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provisional_control (
                    control_key TEXT PRIMARY KEY,
                    control_value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provisional_boundaries (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    processed_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provisional_maintenance_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    lease_expires_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT,
                    cursor_start_json TEXT NOT NULL,
                    cursor_end_json TEXT NOT NULL,
                    transitions_json TEXT NOT NULL,
                    error_code TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_provisional_maintenance_running
                    ON provisional_maintenance_runs(status, lease_expires_at_utc);
                """
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO provisional_control(control_key, control_value) VALUES ('store_uuid', ?)",
                (str(uuid.uuid4()),),
            )
            self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        self._ensure_maintenance_schema()

    def _ensure_maintenance_schema(self) -> None:
        """Add maintenance state without changing the established store version."""

        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS provisional_maintenance_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    lease_expires_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT,
                    cursor_start_json TEXT NOT NULL,
                    cursor_end_json TEXT NOT NULL,
                    transitions_json TEXT NOT NULL,
                    error_code TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_provisional_maintenance_running
                    ON provisional_maintenance_runs(status, lease_expires_at_utc);
                """
            )

    def _migrate_v2_to_v3(
        self,
        *,
        scrub_legacy_secrets: bool,
        scrub_authorized_by: str | None,
        verified_backup: Path | None,
    ) -> None:
        """Transactional/repeat-safe v2 migration; user_version is committed last."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                rows = self._conn.execute("SELECT record_id, canonical_text, metadata_json, source_refs_json FROM provisional_records").fetchall()
                for row in rows:
                    payload = [str(row["canonical_text"]), json.loads(row["metadata_json"] or "{}"), json.loads(row["source_refs_json"] or "[]")]
                    try:
                        assert_safe_content(payload)
                    except SecretDetectedError:
                        if not scrub_legacy_secrets:
                            raise
                        scrubbed_metadata = scrub_content(json.loads(row["metadata_json"] or "{}"))
                        scrubbed_metadata["safety_reason"] = "legacy_secret_scrubbed"
                        self._conn.execute(
                            "UPDATE provisional_records SET canonical_text = ?, metadata_json = ?, source_refs_json = ? WHERE record_id = ?",
                            (
                                str(scrub_content(str(row["canonical_text"]))),
                                json.dumps(scrubbed_metadata),
                                json.dumps(scrub_content(json.loads(row["source_refs_json"] or "[]"))),
                                row["record_id"],
                            ),
                        )
                event_rows = self._conn.execute("SELECT seq, source_refs_json, metadata_json, reason FROM provisional_events").fetchall()
                for row in event_rows:
                    try:
                        assert_safe_content([json.loads(row["source_refs_json"] or "[]"), json.loads(row["metadata_json"] or "{}"), str(row["reason"])])
                    except SecretDetectedError:
                        if not scrub_legacy_secrets:
                            raise
                        scrubbed_metadata = scrub_content(json.loads(row["metadata_json"] or "{}"))
                        scrubbed_metadata["safety_reason"] = "legacy_secret_scrubbed"
                        self._conn.execute(
                            "UPDATE provisional_events SET source_refs_json=?, metadata_json=?, reason=? WHERE seq=?",
                            (
                                json.dumps(scrub_content(json.loads(row["source_refs_json"] or "[]"))),
                                json.dumps(scrubbed_metadata),
                                str(scrub_content(str(row["reason"]))),
                                row["seq"],
                            ),
                        )
                existing_columns = {str(item[1]) for item in self._conn.execute("PRAGMA table_info(provisional_records)").fetchall()}
                for column, declaration in (
                    ("authority_tier", "TEXT NOT NULL DEFAULT 'provisional_observed'"),
                    ("maturity", "TEXT NOT NULL DEFAULT 'observed'"),
                    ("lifecycle", "TEXT NOT NULL DEFAULT 'active'"),
                    ("derived", "INTEGER NOT NULL DEFAULT 0"),
                    ("input_record_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                    ("independent_support_count", "INTEGER NOT NULL DEFAULT 0"),
                    ("distinct_session_count", "INTEGER NOT NULL DEFAULT 0"),
                    ("last_independent_support_at", "TEXT"),
                    ("policy_version", "TEXT NOT NULL DEFAULT 'v0.2'"),
                    ("claim_key", "TEXT NOT NULL DEFAULT ''"),
                ):
                    if column not in existing_columns:
                        self._conn.execute(f"ALTER TABLE provisional_records ADD COLUMN {column} {declaration}")
                self._conn.executescript("""
                    CREATE TABLE IF NOT EXISTS provisional_evidence_units (
                        evidence_fingerprint TEXT PRIMARY KEY, record_id TEXT NOT NULL, source_id TEXT NOT NULL,
                        message_id TEXT NOT NULL, span_start INTEGER NOT NULL, span_end INTEGER NOT NULL,
                        source_role TEXT NOT NULL, content_digest TEXT NOT NULL, session_id TEXT NOT NULL,
                        registered INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS provisional_control (control_key TEXT PRIMARY KEY, control_value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS provisional_boundaries (
                        event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, observed_at_utc TEXT NOT NULL,
                        metadata_json TEXT NOT NULL, processed_at_utc TEXT NOT NULL
                    );
                """)
                self._conn.execute("INSERT OR IGNORE INTO provisional_control(control_key, control_value) VALUES ('store_uuid', ?)", (str(uuid.uuid4()),))
                if scrub_legacy_secrets:
                    if not scrub_authorized_by or verified_backup is None:
                        raise ValueError("SCRUB_REVIEW_AUTHORIZATION_REQUIRED")
                    self._conn.execute(
                        "INSERT OR REPLACE INTO provisional_control(control_key, control_value) VALUES ('legacy_scrub_authorized_by', ?)",
                        (scrub_authorized_by,),
                    )
                    self._conn.execute(
                        "INSERT OR REPLACE INTO provisional_control(control_key, control_value) VALUES ('legacy_scrub_backup', ?)",
                        (str(verified_backup),),
                    )
                self._conn.execute("UPDATE provisional_records SET claim_key = dedupe_key WHERE claim_key = ''")
                self._conn.execute("PRAGMA user_version=3")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @property
    def store_uuid(self) -> str:
        with self._lock:
            row = self._conn.execute("SELECT control_value FROM provisional_control WHERE control_key = 'store_uuid'").fetchone()
        if row is None:
            raise RuntimeError("store_uuid unavailable")
        return str(row[0])

    def record_boundary(
        self,
        *,
        event_id: str,
        event_type: str,
        observed_at_utc: str,
        metadata: dict[str, str] | None = None,
    ) -> bool:
        """Persist a boundary once; True means this call owns its maintenance pass."""

        assert_safe_content(metadata or {})
        normalized_id = str(event_id or "").strip()
        normalized_type = str(event_type or "").strip().lower()
        if not normalized_id or not normalized_type:
            raise ValueError("boundary event_id and event_type are required")
        now = self._clock().astimezone(timezone.utc).isoformat()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """INSERT OR IGNORE INTO provisional_boundaries
                   (event_id,event_type,observed_at_utc,metadata_json,processed_at_utc)
                   VALUES(?,?,?,?,?)""",
                (normalized_id, normalized_type, str(observed_at_utc or ""), self._serialize_metadata(metadata or {}), now),
            )
        return int(cursor.rowcount or 0) == 1

    def maintenance_cursor(self) -> dict[str, str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT control_value FROM provisional_control WHERE control_key = 'maintenance_cursor'"
            ).fetchone()
        if row is None:
            return {"created_at": "", "record_id": ""}
        try:
            value = json.loads(str(row[0]))
        except json.JSONDecodeError:
            return {"created_at": "", "record_id": ""}
        return {
            "created_at": str(value.get("created_at") or ""),
            "record_id": str(value.get("record_id") or ""),
        }

    def maintenance_begin(self, run_id: str, *, lease_seconds: int = 300) -> dict[str, object]:
        """Acquire the durable maintenance lease or report replay/join/conflict."""

        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            raise ValueError("maintenance run_id is required")
        if not 1 <= int(lease_seconds) <= 3600:
            raise ValueError("maintenance lease_seconds must be in 1..3600")
        now = self._clock().astimezone(timezone.utc)
        now_text = now.isoformat()
        expires_text = (now + timedelta(seconds=int(lease_seconds))).isoformat()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    "SELECT * FROM provisional_maintenance_runs WHERE run_id = ?", (normalized_run_id,)
                ).fetchone()
                if existing is not None and str(existing["status"]) == "completed":
                    self._conn.commit()
                    return {"state": "replay", "transitions": json.loads(str(existing["transitions_json"]))}
                active = self._conn.execute(
                    "SELECT * FROM provisional_maintenance_runs WHERE status = 'running'"
                ).fetchall()
                for row in active:
                    if datetime.fromisoformat(str(row["lease_expires_at_utc"])) > now:
                        self._conn.commit()
                        return {"state": "join" if str(row["run_id"]) == normalized_run_id else "conflict"}
                    self._conn.execute(
                        "UPDATE provisional_maintenance_runs SET status = 'failed', error_code = 'LEASE_EXPIRED' WHERE run_id = ?",
                        (str(row["run_id"]),),
                    )
                cursor = self.maintenance_cursor()
                self._conn.execute(
                    """
                    INSERT INTO provisional_maintenance_runs (
                        run_id, status, started_at_utc, lease_expires_at_utc, cursor_start_json,
                        cursor_end_json, transitions_json, error_code
                    ) VALUES (?, 'running', ?, ?, ?, '{}', '[]', '')
                    ON CONFLICT(run_id) DO UPDATE SET
                        status = 'running', started_at_utc = excluded.started_at_utc,
                        lease_expires_at_utc = excluded.lease_expires_at_utc,
                        cursor_start_json = excluded.cursor_start_json, cursor_end_json = '{}',
                        transitions_json = '[]', error_code = ''
                    """,
                    (normalized_run_id, now_text, expires_text, json.dumps(cursor, sort_keys=True)),
                )
                self._conn.commit()
                return {"state": "acquired", "cursor": cursor}
            except Exception:
                self._conn.rollback()
                raise

    def maintenance_candidates(
        self, *, cursor: dict[str, str], limit: int
    ) -> tuple[list[ProvisionalMemoryRecord], dict[str, str]]:
        if not 1 <= int(limit) <= 100:
            raise ValueError("maintenance limit must be in 1..100")
        terminal = tuple(item.value for item in (
            ProvisionalMemoryStatus.SUPERSEDED,
            ProvisionalMemoryStatus.CONFLICTED,
            ProvisionalMemoryStatus.ARCHIVED,
        ))
        params = [*terminal]
        created_at = str(cursor.get("created_at") or "")
        record_id = str(cursor.get("record_id") or "")
        where_after = ""
        if created_at or record_id:
            where_after = " AND (created_at > ? OR (created_at = ? AND record_id > ?))"
            params.extend([created_at, created_at, record_id])
        query = (
            "SELECT * FROM provisional_records WHERE status NOT IN (?, ?, ?)"
            + where_after
            + " ORDER BY created_at ASC, record_id ASC LIMIT ?"
        )
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
            if len(rows) < int(limit) and (created_at or record_id):
                remaining = int(limit) - len(rows)
                seen = {str(row["record_id"]) for row in rows}
                wrapped = self._conn.execute(
                    "SELECT * FROM provisional_records WHERE status NOT IN (?, ?, ?) "
                    "ORDER BY created_at ASC, record_id ASC LIMIT ?",
                    [*terminal, remaining],
                ).fetchall()
                rows.extend(row for row in wrapped if str(row["record_id"]) not in seen)
        records = [self._row_to_record(row) for row in rows]
        next_cursor = dict(cursor)
        if records:
            last = records[-1]
            next_cursor = {"created_at": last.created_at.isoformat(), "record_id": last.record_id}
        return records, next_cursor

    def maintenance_complete(
        self, run_id: str, *, cursor: dict[str, str], transitions: list[dict[str, str]]
    ) -> None:
        now = self._clock().astimezone(timezone.utc).isoformat()
        normalized_run_id = str(run_id or "").strip()
        payload = json.dumps(list(transitions), ensure_ascii=False, sort_keys=True)
        cursor_payload = json.dumps(dict(cursor), ensure_ascii=False, sort_keys=True)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT status FROM provisional_maintenance_runs WHERE run_id = ?", (normalized_run_id,)
            ).fetchone()
            if row is None or str(row["status"]) != "running":
                raise RuntimeError("MAINTENANCE_RUN_NOT_OWNED")
            self._conn.execute(
                """
                UPDATE provisional_maintenance_runs
                SET status = 'completed', completed_at_utc = ?, cursor_end_json = ?, transitions_json = ?
                WHERE run_id = ?
                """,
                (now, cursor_payload, payload, normalized_run_id),
            )
            self._conn.execute(
                "INSERT INTO provisional_control(control_key, control_value) VALUES ('maintenance_cursor', ?) "
                "ON CONFLICT(control_key) DO UPDATE SET control_value = excluded.control_value",
                (cursor_payload,),
            )
            self._conn.execute(
                """
                DELETE FROM provisional_maintenance_runs
                WHERE run_id IN (
                    SELECT run_id FROM provisional_maintenance_runs
                    WHERE status = 'completed'
                    ORDER BY completed_at_utc DESC, run_id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (_MAX_COMPLETED_MAINTENANCE_RUNS,),
            )

    def maintenance_fail(self, run_id: str, *, error_code: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE provisional_maintenance_runs SET status = 'failed', error_code = ? WHERE run_id = ? AND status = 'running'",
                (str(error_code or "MAINTENANCE_FAILED"), str(run_id or "").strip()),
            )

    @classmethod
    def migrate_legacy_store(
        cls,
        db_path: str | Path,
        *,
        scrub_legacy_secrets: bool = False,
        scrub_authorized_by: str | None = None,
        legacy_backup_path: str | Path | None = None,
    ) -> "SqliteProvisionalMemoryStore":
        """Explicit migration entry point; default is abort-on-secret, never silent scrub."""
        return cls(
            db_path,
            scrub_legacy_secrets=scrub_legacy_secrets,
            scrub_authorized_by=scrub_authorized_by,
            legacy_backup_path=legacy_backup_path,
        )

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
            authority_tier=ProvisionalAuthorityTier(str(row["authority_tier"]) if "authority_tier" in row.keys() else "provisional_observed"),
            maturity=ProvisionalMaturity(str(row["maturity"]) if "maturity" in row.keys() else "observed"),
            lifecycle=ProvisionalLifecycle(str(row["lifecycle"]) if "lifecycle" in row.keys() else "active"),
            derived=bool(row["derived"]) if "derived" in row.keys() else False,
            input_record_ids=[str(item) for item in json.loads(row["input_record_ids_json"] or "[]")] if "input_record_ids_json" in row.keys() else [],
            independent_support_count=int(row["independent_support_count"]) if "independent_support_count" in row.keys() else 0,
            distinct_session_count=int(row["distinct_session_count"]) if "distinct_session_count" in row.keys() else 0,
            last_independent_support_at=(datetime.fromisoformat(str(row["last_independent_support_at"])) if "last_independent_support_at" in row.keys() and row["last_independent_support_at"] else None),
            policy_version=str(row["policy_version"]) if "policy_version" in row.keys() else "v0.2",
            claim_key=str(row["claim_key"]) if "claim_key" in row.keys() else str(row["dedupe_key"]),
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

    @contextmanager
    def _write_transaction(self, *, immediate: bool = False):
        """Join an active write or own one atomic SQLite transaction."""
        with self._lock:
            owns_transaction = not self._conn.in_transaction
            if owns_transaction:
                self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield
            except Exception:
                if owns_transaction:
                    self._conn.rollback()
                raise
            else:
                if owns_transaction:
                    self._conn.commit()

    def _append_event(
        self,
        *,
        event_type: ProvisionalMemoryEventType,
        record_id: str,
        reason: str,
        source_refs: list[SourceRef],
        metadata: dict[str, str] | None = None,
    ) -> None:
        with self._write_transaction():
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
                timestamp=self._clock(),
                reason=reason,
                source_refs=list(source_refs),
                metadata=dict(metadata or {}),
            )
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
        _reactivate: bool = False,
    ) -> ProvisionalMemoryRecord:
        with self._write_transaction():
            row = self._conn.execute(
                "SELECT * FROM provisional_records WHERE dedupe_key = ?",
                (candidate.dedupe_key,),
            ).fetchone()
            if row is not None:
                record = self._row_to_record(row)
                reactivating = _reactivate and record.lifecycle in {
                    ProvisionalLifecycle.DORMANT,
                    ProvisionalLifecycle.ARCHIVED,
                }
                if record.status in _LIVE_STATUSES or reactivating:
                    now = self._clock()
                    updated_refs = record.source_refs + list(candidate.source_refs)
                    updated_confidence = max(record.confidence, candidate.confidence)
                    updated_salience = max(record.salience, candidate.salience)
                    updated_stability = max(record.stability, candidate.stability)
                    updated_metadata = _metadata_with_session_ids(record.metadata, candidate.session_id)
                    next_status = ProvisionalMemoryStatus.ACTIVE if reactivating else record.status
                    next_lifecycle = ProvisionalLifecycle.ACTIVE if reactivating else record.lifecycle
                    self._conn.execute(
                        """
                        UPDATE provisional_records
                        SET source_refs_json = ?, reinforcement_count = ?, confidence = ?, salience = ?,
                            stability = ?, updated_at = ?, last_reinforced_at = ?, metadata_json = ?,
                            status = ?, lifecycle = ?
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
                            next_status.value,
                            next_lifecycle.value,
                            record.record_id,
                        ),
                    )
                    self._append_event(
                        event_type=(
                            ProvisionalMemoryEventType.REACTIVATE
                            if reactivating
                            else ProvisionalMemoryEventType.REINFORCE
                        ),
                        record_id=record.record_id,
                        reason=reason,
                        source_refs=candidate.source_refs,
                        metadata={"dedupe_key": candidate.dedupe_key},
                    )
                    return self.get_record(record.record_id)
                return record

            now = self._clock()
            record = _build_record(
                candidate,
                record_id=_record_id_for_candidate(
                    kind=candidate.kind.value,
                    canonical_text=candidate.canonical_text,
                    source_role=candidate.source_role,
                ),
                now=now,
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

    def register_source(
        self,
        *,
        source_id: str,
        message_id: str,
        source_role: str,
        content: str,
        session_id: str,
    ) -> EvidenceRegistration:
        """Create a stateless, store-bound registration primitive (no memory write)."""
        role = str(source_role).strip().lower()
        if role not in {"user", "tool", "external"}:
            raise ValueError("only user/tool/external spans may be registered")
        digest = _content_digest(content)
        source_id, message_id = str(source_id).strip(), str(message_id).strip()
        if not source_id or not message_id:
            raise ValueError("source_id and message_id are required")
        payload = "|".join((self.store_uuid, source_id, message_id, role, digest, str(session_id).strip()))
        return EvidenceRegistration(source_id, message_id, role, digest, str(session_id).strip(), sha256(payload.encode("utf-8")).hexdigest())

    def observe_candidate(
        self,
        candidate: ProvisionalMemoryCandidate,
        *,
        reason: str,
        registration: EvidenceRegistration | None = None,
        assistant_receipt_valid: bool = False,
    ) -> ObservationDisposition:
        """Persist one candidate and count only registered independent evidence once."""
        assert_safe_content([candidate.canonical_text, candidate.metadata, candidate.content])
        content = candidate.content or candidate.canonical_text
        digest = _content_digest(content)
        registered = False
        if registration is not None:
            expected_payload = "|".join(
                (
                    self.store_uuid,
                    candidate.source_id,
                    candidate.message_id,
                    candidate.source_role,
                    digest,
                    candidate.session_id,
                )
            )
            registered = (
                registration.content_digest == digest
                and registration.source_role == candidate.source_role
                and registration.source_id == candidate.source_id
                and registration.message_id == candidate.message_id
                and registration.session_id == candidate.session_id
                and registration.handle == sha256(expected_payload.encode("utf-8")).hexdigest()
            )
        supporting = source_role_eligible(
            candidate.source_role,
            kind=candidate.kind,
            registered=registered,
            assistant_receipt_valid=assistant_receipt_valid,
        )
        source_id = candidate.source_id or ""
        message_id = candidate.message_id or ""
        fingerprint: str | None = None
        if supporting and source_id and message_id:
            fingerprint = _evidence_fingerprint(
                store_uuid=self.store_uuid,
                source_id=source_id,
                message_id=message_id,
                span_start=candidate.span_start,
                span_end=candidate.span_end,
                source_role=candidate.source_role,
                content_digest=digest,
            )
        if not supporting:
            record = self.upsert_candidate(candidate, reason=reason)
            return ObservationDisposition(record.record_id, 0, None, "unregistered_or_ineligible")

        with self._write_transaction(immediate=True):
            if fingerprint is not None:
                collision = self._conn.execute(
                    "SELECT content_digest FROM provisional_evidence_units WHERE source_id=? AND message_id=? AND span_start=? AND span_end=? AND source_role=?",
                    (source_id, message_id, candidate.span_start, candidate.span_end, candidate.source_role),
                ).fetchone()
                if collision is not None and str(collision["content_digest"]) != digest:
                    raise ValueError("EVIDENCE_IDENTITY_CONFLICT")
                present = self._conn.execute(
                    "SELECT record_id FROM provisional_evidence_units WHERE evidence_fingerprint=?",
                    (fingerprint,),
                ).fetchone()
                if present is not None:
                    return ObservationDisposition(str(present["record_id"]), 0, fingerprint, "replay")

            record = self.upsert_candidate(candidate, reason=reason, _reactivate=True)
            if record.status is ProvisionalMemoryStatus.SUPERSEDED:
                return ObservationDisposition(record.record_id, 0, None, "superseded")
            source_id = source_id or f"fallback:{record.record_id}"
            message_id = message_id or f"fallback:{digest}"
            fingerprint = fingerprint or _evidence_fingerprint(
                store_uuid=self.store_uuid,
                source_id=source_id,
                message_id=message_id,
                span_start=candidate.span_start,
                span_end=candidate.span_end,
                source_role=candidate.source_role,
                content_digest=digest,
            )
            collision = self._conn.execute(
                "SELECT content_digest FROM provisional_evidence_units WHERE source_id=? AND message_id=? AND span_start=? AND span_end=? AND source_role=?",
                (source_id, message_id, candidate.span_start, candidate.span_end, candidate.source_role),
            ).fetchone()
            if collision is not None and str(collision["content_digest"]) != digest:
                raise ValueError("EVIDENCE_IDENTITY_CONFLICT")
            present = self._conn.execute(
                "SELECT record_id FROM provisional_evidence_units WHERE evidence_fingerprint=?",
                (fingerprint,),
            ).fetchone()
            if present is not None:
                return ObservationDisposition(str(present["record_id"]), 0, fingerprint, "replay")
            now = self._clock()
            self._conn.execute(
                "INSERT INTO provisional_evidence_units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (fingerprint, record.record_id, source_id, message_id, candidate.span_start, candidate.span_end,
                 candidate.source_role, digest, candidate.session_id, now.isoformat()),
            )
            supports = self._conn.execute("SELECT COUNT(*) FROM provisional_evidence_units WHERE record_id=?", (record.record_id,)).fetchone()[0]
            sessions = self._conn.execute("SELECT COUNT(DISTINCT session_id) FROM provisional_evidence_units WHERE record_id=?", (record.record_id,)).fetchone()[0]
            maturity = ProvisionalMaturity.REINFORCED.value if supports >= 2 else ProvisionalMaturity.OBSERVED.value
            self._conn.execute(
                "UPDATE provisional_records SET independent_support_count=?, distinct_session_count=?, maturity=?, last_independent_support_at=? WHERE record_id=?",
                (supports, sessions, maturity, now.isoformat(), record.record_id),
            )
        return ObservationDisposition(record.record_id, 1, fingerprint, "accepted")

    def set_lifecycle(self, record_id: str, lifecycle: ProvisionalLifecycle, *, reason: str) -> ProvisionalMemoryRecord:
        record = self.get_record(record_id)
        if record.derived and record.status is ProvisionalMemoryStatus.SUPERSEDED:
            return record
        status = {
            ProvisionalLifecycle.ACTIVE: ProvisionalMemoryStatus.ACTIVE,
            ProvisionalLifecycle.DORMANT: ProvisionalMemoryStatus.DORMANT,
            ProvisionalLifecycle.ARCHIVED: ProvisionalMemoryStatus.ARCHIVED,
        }[lifecycle]
        now = self._clock()
        event_type = {
            ProvisionalLifecycle.ACTIVE: ProvisionalMemoryEventType.REACTIVATE,
            ProvisionalLifecycle.DORMANT: ProvisionalMemoryEventType.DORMANT,
            ProvisionalLifecycle.ARCHIVED: ProvisionalMemoryEventType.ARCHIVE,
        }[lifecycle]
        with self._write_transaction():
            self._conn.execute(
                "UPDATE provisional_records SET lifecycle=?, status=?, updated_at=? WHERE record_id=?",
                (lifecycle.value, status.value, now.isoformat(), record_id),
            )
            self._append_event(
                event_type=event_type,
                record_id=record_id,
                reason=reason,
                source_refs=[],
                metadata={"lifecycle": lifecycle.value},
            )
        return self.get_record(record_id)

    def create_consolidated_revision(
        self, *, record_ids: list[str], policy_version: str = "v0.2", reason: str = "threshold_met"
    ) -> ProvisionalMemoryRecord | None:
        """Create an immutable derived revision for one exact claim/input set."""
        inputs = [self.get_record(record_id) for record_id in sorted(set(record_ids))]
        if not inputs or any(record.conflict_with_record_ids or record.status is not ProvisionalMemoryStatus.ACTIVE for record in inputs):
            return None
        claim_keys = {record.claim_key or _dedupe_key(kind=record.kind.value, canonical_text=record.canonical_text, source_role=record.source_role) for record in inputs}
        if len(claim_keys) != 1:
            return None
        fingerprints: list[str] = []
        with self._lock:
            for record in inputs:
                fingerprints.extend(str(row[0]) for row in self._conn.execute(
                    "SELECT evidence_fingerprint FROM provisional_evidence_units WHERE record_id=? ORDER BY evidence_fingerprint", (record.record_id,)
                ).fetchall())
        if not fingerprints:
            return None
        derivation_id = sha256("|".join([next(iter(claim_keys)), *sorted(set(fingerprints)), policy_version]).encode("utf-8")).hexdigest()
        with self._lock:
            row = self._conn.execute("SELECT * FROM provisional_records WHERE metadata_json LIKE ?", (f'%"derivation_id": "{derivation_id}"%',)).fetchone()
        if row is not None:
            return self._row_to_record(row)
        now = self._clock()
        summary = inputs[0].canonical_text
        record_id = f"prov_con_{derivation_id[:16]}"
        source_refs = [ref for record in inputs for ref in record.source_refs]
        sessions = len({session for record in inputs for session in _session_ids_from_metadata(record.metadata, fallback_session_id=record.session_id)})
        with self._lock, self._conn:
            prior = self._conn.execute(
                "SELECT record_id FROM provisional_records WHERE authority_tier=? AND claim_key=? AND status=? ORDER BY created_at DESC LIMIT 1",
                (ProvisionalAuthorityTier.CONSOLIDATED.value, next(iter(claim_keys)), ProvisionalMemoryStatus.ACTIVE.value),
            ).fetchone()
            self._conn.execute(
                """INSERT INTO provisional_records(record_id,kind,canonical_text,source_refs_json,source_role,session_id,confidence,salience,stability,reinforcement_count,status,supersedes_record_id,superseded_by_record_id,conflict_with_json,created_at,updated_at,last_reinforced_at,metadata_json,dedupe_key,authority_tier,maturity,lifecycle,derived,input_record_ids_json,independent_support_count,distinct_session_count,last_independent_support_at,policy_version,claim_key)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record_id, inputs[0].kind.value, summary, self._serialize_refs(source_refs), inputs[0].source_role, inputs[0].session_id,
                 max(r.confidence for r in inputs), max(r.salience for r in inputs), max(r.stability for r in inputs), len(fingerprints),
                 ProvisionalMemoryStatus.ACTIVE.value, prior["record_id"] if prior else None, None, "[]", now.isoformat(), now.isoformat(), now.isoformat(),
                 self._serialize_metadata({"derivation_id": derivation_id, "reason": reason}), derivation_id,
                 ProvisionalAuthorityTier.CONSOLIDATED.value, ProvisionalMaturity.CONSOLIDATED.value, ProvisionalLifecycle.ACTIVE.value, 1,
                 json.dumps([r.record_id for r in inputs]), len(fingerprints), sessions, now.isoformat(), policy_version, next(iter(claim_keys))),
            )
            if prior:
                self._conn.execute("UPDATE provisional_records SET status=?, superseded_by_record_id=?, updated_at=? WHERE record_id=?", (ProvisionalMemoryStatus.SUPERSEDED.value, record_id, now.isoformat(), prior["record_id"]))
        self._append_event(event_type=ProvisionalMemoryEventType.CONSOLIDATE, record_id=record_id, reason=reason, source_refs=source_refs, metadata={"input_record_ids": json.dumps([r.record_id for r in inputs])})
        return self.get_record(record_id)

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
        now = self._clock().isoformat()
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
            now=self._clock(),
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
                    self._clock().isoformat(),
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
            timestamp=self._clock(),
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
    "EvidenceRegistration",
    "InMemoryProvisionalMemoryStore",
    "ObservationDisposition",
    "ProvisionalAuthorityTier",
    "ProvisionalMemoryCandidate",
    "ProvisionalMemoryEvent",
    "ProvisionalMemoryEventType",
    "ProvisionalMemoryKind",
    "ProvisionalLifecycle",
    "ProvisionalMaturity",
    "ProvisionalMemoryRecord",
    "ProvisionalMemoryStatus",
    "ProvisionalSearchHit",
    "SourceRole",
    "SqliteProvisionalMemoryStore",
    "source_role_eligible",
]
