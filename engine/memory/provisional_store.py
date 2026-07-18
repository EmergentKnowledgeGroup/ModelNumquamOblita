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
_SCHEMA_VERSION = 4
_MAX_COMPLETED_MAINTENANCE_RUNS = 256
_TEMPORAL_RETAINED_EVENT_ROWS = 10_000
_TEMPORAL_EVENT_HARD_CAP = 100_000
_TEMPORAL_EVENT_RETENTION_DAYS = 3652
_TEMPORAL_STATE_RETENTION_DAYS = 3652
_TEMPORAL_TERMINAL_IDEMPOTENCY_DAYS = 30
_TEMPORAL_NONTERMINAL_IDEMPOTENCY_DAYS = 18_263


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


class TemporalDisposition(str, Enum):
    """Explicit temporal command state; eligibility is deliberately read-time only."""

    NONE = "none"
    SCHEDULED = "scheduled"
    SNOOZED = "snoozed"
    ACKNOWLEDGED = "acknowledged"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


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
    # v0.2.2 fields default to inert values so ordinary v0.2 records remain
    # ordinary provisional memories after a v3 -> v4 upgrade.
    store_uuid: str = ""
    principal_id: str = ""
    runtime_id: str = ""
    temporal_kind: str = ""
    temporal_disposition: TemporalDisposition = TemporalDisposition.NONE
    temporal_revision: int = 0
    due_window_start_utc: Optional[datetime] = None
    due_window_end_utc: Optional[datetime] = None
    temporal_timezone: str = ""
    temporal_precision: str = ""
    original_expression: str = ""
    temporal_resolution_metadata: dict[str, object] = field(default_factory=dict)
    decay_not_before_utc: Optional[datetime] = None
    snoozed_until_utc: Optional[datetime] = None

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

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        include_dormant: bool = False,
        dormant_only: bool = False,
    ) -> list[ProvisionalSearchHit]:
        hits: list[ProvisionalSearchHit] = []
        for record in self._records.values():
            if dormant_only and record.lifecycle is not ProvisionalLifecycle.DORMANT:
                continue
            if not dormant_only and record.status not in _LIVE_STATUSES and not (
                include_dormant and record.lifecycle is ProvisionalLifecycle.DORMANT
            ):
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
        elif legacy_version in {2, 3}:
            backup_target = (
                Path(legacy_backup_path)
                if legacy_backup_path is not None
                else self.db_path.with_name(f"{self.db_path.name}.pre-v4.sqlite3")
            )
            if backup_target.exists():
                backup_target = backup_target.with_name(
                    f"{backup_target.stem}-{uuid.uuid4().hex[:8]}{backup_target.suffix}"
                )
            verified_backup = self._backup_and_verify_pre_v4_store(
                self.db_path,
                backup_target,
                expected_version=legacy_version,
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
            pre_v4_backup=verified_backup,
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

    @classmethod
    def _backup_and_verify_pre_v4_store(
        cls,
        source_path: Path,
        target_path: Path,
        *,
        expected_version: int,
    ) -> Path:
        """Create and verify the mandatory pre-v4 backup before any write connection."""

        source = source_path.expanduser().resolve()
        target = target_path.expanduser().resolve()
        if source == target:
            raise ValueError("pre-v4 backup target must differ from the live store")
        if target.exists():
            raise FileExistsError("pre-v4 backup target already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        with cls._read_only_connection(source) as source_conn:
            tables = {
                str(row[0])
                for row in source_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            count_tables = [
                name
                for name in ("provisional_records", "provisional_events", "provisional_evidence_units")
                if name in tables
            ]
            source_counts = {
                name: int(source_conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in count_tables
            }
            with sqlite3.connect(str(target)) as destination:
                source_conn.backup(destination)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        with sqlite3.connect(str(target)) as backup:
            backup_version = int(backup.execute("PRAGMA user_version").fetchone()[0])
            integrity = str(backup.execute("PRAGMA integrity_check").fetchone()[0])
            backup_counts = {
                name: int(backup.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in source_counts
            }
        if backup_version != int(expected_version) or integrity.lower() != "ok" or backup_counts != source_counts:
            raise RuntimeError("PRE_V4_BACKUP_VERIFICATION_FAILED")
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
        pre_v4_backup: Path | None = None,
    ) -> None:
        version = self._schema_version()
        if version not in {0, 2, 3, _SCHEMA_VERSION}:
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
            self._migrate_v3_to_v4(pre_v4_backup=pre_v4_backup)
            self._ensure_maintenance_schema()
            return
        if version == 3:
            self._migrate_v3_to_v4(pre_v4_backup=pre_v4_backup)
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
                    claim_key TEXT NOT NULL DEFAULT '',
                    store_uuid TEXT NOT NULL DEFAULT '',
                    principal_id TEXT NOT NULL DEFAULT '',
                    runtime_id TEXT NOT NULL DEFAULT '',
                    temporal_kind TEXT NOT NULL DEFAULT '',
                    temporal_disposition TEXT NOT NULL DEFAULT 'none',
                    temporal_revision INTEGER NOT NULL DEFAULT 0,
                    due_window_start_utc TEXT,
                    due_window_end_utc TEXT,
                    temporal_timezone TEXT NOT NULL DEFAULT '',
                    temporal_precision TEXT NOT NULL DEFAULT '',
                    original_expression TEXT NOT NULL DEFAULT '',
                    temporal_resolution_json TEXT NOT NULL DEFAULT '{}',
                    decay_not_before_utc TEXT,
                    snoozed_until_utc TEXT
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
                CREATE INDEX IF NOT EXISTS idx_provisional_temporal_scope_due
                    ON provisional_records(store_uuid, principal_id, runtime_id, temporal_disposition, due_window_start_utc, created_at, record_id);
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
                CREATE TABLE IF NOT EXISTS provisional_temporal_state_events (
                    event_id TEXT PRIMARY KEY,
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    prior_disposition TEXT NOT NULL,
                    new_disposition TEXT NOT NULL,
                    prior_revision INTEGER NOT NULL,
                    new_revision INTEGER NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_temporal_state_events_scope_record
                    ON provisional_temporal_state_events(store_uuid, principal_id, runtime_id, record_id, new_revision);
                CREATE TABLE IF NOT EXISTS provisional_turn_clock_events (
                    event_id TEXT PRIMARY KEY,
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    timeline_id TEXT,
                    role TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    provenance_status TEXT NOT NULL,
                    signed_registration_issued_at_utc TEXT,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_turn_clock_scope_role
                    ON provisional_turn_clock_events(store_uuid, principal_id, runtime_id, role, observed_at_utc DESC, event_id DESC);
                CREATE TABLE IF NOT EXISTS provisional_temporal_delivery_events (
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    delivery_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    receipt_identity TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    PRIMARY KEY(store_uuid, principal_id, runtime_id, delivery_id)
                );
                CREATE INDEX IF NOT EXISTS idx_temporal_delivery_record
                    ON provisional_temporal_delivery_events(store_uuid, principal_id, runtime_id, record_id, observed_at_utc DESC);
                CREATE TABLE IF NOT EXISTS provisional_temporal_idempotency (
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    record_id TEXT,
                    created_at_utc TEXT NOT NULL,
                    PRIMARY KEY(store_uuid, principal_id, runtime_id, operation, idempotency_key)
                );
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
                CREATE TABLE IF NOT EXISTS provisional_temporal_state_events (
                    event_id TEXT PRIMARY KEY,
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    prior_disposition TEXT NOT NULL,
                    new_disposition TEXT NOT NULL,
                    prior_revision INTEGER NOT NULL,
                    new_revision INTEGER NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_temporal_state_events_scope_record
                    ON provisional_temporal_state_events(store_uuid, principal_id, runtime_id, record_id, new_revision);
                CREATE INDEX IF NOT EXISTS idx_temporal_state_events_scope_timestamp
                    ON provisional_temporal_state_events(store_uuid, principal_id, runtime_id, observed_at_utc, event_id);
                CREATE TABLE IF NOT EXISTS provisional_turn_clock_events (
                    event_id TEXT PRIMARY KEY,
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    timeline_id TEXT,
                    role TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    provenance_status TEXT NOT NULL,
                    signed_registration_issued_at_utc TEXT,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_turn_clock_scope_role
                    ON provisional_turn_clock_events(store_uuid, principal_id, runtime_id, role, observed_at_utc DESC, event_id DESC);
                CREATE INDEX IF NOT EXISTS idx_turn_clock_scope_timestamp
                    ON provisional_turn_clock_events(store_uuid, principal_id, runtime_id, observed_at_utc, event_id);
                CREATE TABLE IF NOT EXISTS provisional_temporal_delivery_events (
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    delivery_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    receipt_identity TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    PRIMARY KEY(store_uuid, principal_id, runtime_id, delivery_id)
                );
                CREATE INDEX IF NOT EXISTS idx_temporal_delivery_record
                    ON provisional_temporal_delivery_events(store_uuid, principal_id, runtime_id, record_id, observed_at_utc DESC);
                CREATE INDEX IF NOT EXISTS idx_temporal_delivery_scope_timestamp
                    ON provisional_temporal_delivery_events(store_uuid, principal_id, runtime_id, observed_at_utc, delivery_id);
                CREATE TABLE IF NOT EXISTS provisional_temporal_idempotency (
                    store_uuid TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    record_id TEXT,
                    created_at_utc TEXT NOT NULL,
                    PRIMARY KEY(store_uuid, principal_id, runtime_id, operation, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_temporal_idempotency_scope_record_created
                    ON provisional_temporal_idempotency(store_uuid, principal_id, runtime_id, record_id, created_at_utc);
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

    def _migrate_v3_to_v4(self, *, pre_v4_backup: Path | None) -> None:
        """Transactional, repeat-safe temporal schema upgrade; version flips last."""
        if pre_v4_backup is None or not pre_v4_backup.is_file():
            raise ValueError("PRE_V4_BACKUP_REQUIRED")
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                existing_columns = {
                    str(item[1]) for item in self._conn.execute("PRAGMA table_info(provisional_records)").fetchall()
                }
                for column, declaration in (
                    ("store_uuid", "TEXT NOT NULL DEFAULT ''"),
                    ("principal_id", "TEXT NOT NULL DEFAULT ''"),
                    ("runtime_id", "TEXT NOT NULL DEFAULT ''"),
                    ("temporal_kind", "TEXT NOT NULL DEFAULT ''"),
                    ("temporal_disposition", "TEXT NOT NULL DEFAULT 'none'"),
                    ("temporal_revision", "INTEGER NOT NULL DEFAULT 0"),
                    ("due_window_start_utc", "TEXT"),
                    ("due_window_end_utc", "TEXT"),
                    ("temporal_timezone", "TEXT NOT NULL DEFAULT ''"),
                    ("temporal_precision", "TEXT NOT NULL DEFAULT ''"),
                    ("original_expression", "TEXT NOT NULL DEFAULT ''"),
                    ("temporal_resolution_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ("decay_not_before_utc", "TEXT"),
                    ("snoozed_until_utc", "TEXT"),
                ):
                    if column not in existing_columns:
                        self._conn.execute(f"ALTER TABLE provisional_records ADD COLUMN {column} {declaration}")
                self._execute_schema_script(
                    """
                    CREATE INDEX IF NOT EXISTS idx_provisional_temporal_scope_due
                        ON provisional_records(store_uuid, principal_id, runtime_id, temporal_disposition, due_window_start_utc, created_at, record_id);
                    CREATE TABLE IF NOT EXISTS provisional_temporal_state_events (
                        event_id TEXT PRIMARY KEY, store_uuid TEXT NOT NULL, principal_id TEXT NOT NULL, runtime_id TEXT NOT NULL,
                        record_id TEXT NOT NULL, operation TEXT NOT NULL, prior_disposition TEXT NOT NULL, new_disposition TEXT NOT NULL,
                        prior_revision INTEGER NOT NULL, new_revision INTEGER NOT NULL, observed_at_utc TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL, payload_digest TEXT NOT NULL, result_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_temporal_state_events_scope_record
                        ON provisional_temporal_state_events(store_uuid, principal_id, runtime_id, record_id, new_revision);
                    CREATE TABLE IF NOT EXISTS provisional_turn_clock_events (
                        event_id TEXT PRIMARY KEY, store_uuid TEXT NOT NULL, principal_id TEXT NOT NULL, runtime_id TEXT NOT NULL,
                        timeline_id TEXT, role TEXT NOT NULL, event_kind TEXT NOT NULL, observed_at_utc TEXT NOT NULL,
                        provenance_status TEXT NOT NULL, signed_registration_issued_at_utc TEXT, idempotency_key TEXT NOT NULL, payload_digest TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_turn_clock_scope_role
                        ON provisional_turn_clock_events(store_uuid, principal_id, runtime_id, role, observed_at_utc DESC, event_id DESC);
                    CREATE TABLE IF NOT EXISTS provisional_temporal_delivery_events (
                        store_uuid TEXT NOT NULL, principal_id TEXT NOT NULL, runtime_id TEXT NOT NULL, delivery_id TEXT NOT NULL,
                        record_id TEXT NOT NULL, receipt_identity TEXT NOT NULL, observed_at_utc TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL, payload_digest TEXT NOT NULL,
                        PRIMARY KEY(store_uuid, principal_id, runtime_id, delivery_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_temporal_delivery_record
                        ON provisional_temporal_delivery_events(store_uuid, principal_id, runtime_id, record_id, observed_at_utc DESC);
                    CREATE TABLE IF NOT EXISTS provisional_temporal_idempotency (
                        store_uuid TEXT NOT NULL, principal_id TEXT NOT NULL, runtime_id TEXT NOT NULL, operation TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL, payload_digest TEXT NOT NULL, result_json TEXT NOT NULL, record_id TEXT,
                        created_at_utc TEXT NOT NULL,
                        PRIMARY KEY(store_uuid, principal_id, runtime_id, operation, idempotency_key)
                    );
                    """
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO provisional_control(control_key, control_value) VALUES ('v4_pre_upgrade_backup', ?)",
                    (str(pre_v4_backup.resolve()),),
                )
                self._conn.execute("PRAGMA user_version=4")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _execute_schema_script(self, script: str) -> None:
        """Execute DDL without sqlite3.executescript's implicit transaction commit."""
        for statement in script.split(";"):
            if statement.strip():
                self._conn.execute(statement)

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
            store_uuid=str(row["store_uuid"]) if "store_uuid" in row.keys() else "",
            principal_id=str(row["principal_id"]) if "principal_id" in row.keys() else "",
            runtime_id=str(row["runtime_id"]) if "runtime_id" in row.keys() else "",
            temporal_kind=str(row["temporal_kind"]) if "temporal_kind" in row.keys() else "",
            temporal_disposition=TemporalDisposition(
                str(row["temporal_disposition"]) if "temporal_disposition" in row.keys() else "none"
            ),
            temporal_revision=int(row["temporal_revision"]) if "temporal_revision" in row.keys() else 0,
            due_window_start_utc=(datetime.fromisoformat(str(row["due_window_start_utc"])) if "due_window_start_utc" in row.keys() and row["due_window_start_utc"] else None),
            due_window_end_utc=(datetime.fromisoformat(str(row["due_window_end_utc"])) if "due_window_end_utc" in row.keys() and row["due_window_end_utc"] else None),
            temporal_timezone=str(row["temporal_timezone"]) if "temporal_timezone" in row.keys() else "",
            temporal_precision=str(row["temporal_precision"]) if "temporal_precision" in row.keys() else "",
            original_expression=str(row["original_expression"]) if "original_expression" in row.keys() else "",
            temporal_resolution_metadata=(json.loads(row["temporal_resolution_json"] or "{}") if "temporal_resolution_json" in row.keys() else {}),
            decay_not_before_utc=(datetime.fromisoformat(str(row["decay_not_before_utc"])) if "decay_not_before_utc" in row.keys() and row["decay_not_before_utc"] else None),
            snoozed_until_utc=(datetime.fromisoformat(str(row["snoozed_until_utc"])) if "snoozed_until_utc" in row.keys() and row["snoozed_until_utc"] else None),
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

    @staticmethod
    def _temporal_timestamp(value: datetime | str, *, field_name: str) -> datetime:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            raise ValueError(f"{field_name} must be an offset-aware timestamp")
        return parsed.astimezone(timezone.utc)

    def _temporal_scope(self, *, principal_id: str, runtime_id: str, store_uuid: str | None = None) -> tuple[str, str, str]:
        owner = str(principal_id or "").strip()
        runtime = str(runtime_id or "").strip()
        supplied_store = str(store_uuid or self.store_uuid).strip()
        if not owner or not runtime or supplied_store != self.store_uuid:
            raise ValueError("TEMPORAL_SCOPE_REQUIRED")
        return supplied_store, owner, runtime

    @staticmethod
    def _temporal_payload_digest(payload: dict[str, object]) -> str:
        assert_safe_content(payload)
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest()

    def _temporal_idempotency_replay(
        self, *, scope: tuple[str, str, str], operation: str, idempotency_key: str, payload_digest: str
    ) -> dict[str, object] | None:
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("TEMPORAL_IDEMPOTENCY_KEY_REQUIRED")
        row = self._conn.execute(
            """SELECT payload_digest, result_json FROM provisional_temporal_idempotency
               WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND operation=? AND idempotency_key=?""",
            (*scope, operation, key),
        ).fetchone()
        if row is None:
            return None
        if str(row["payload_digest"]) != payload_digest:
            raise ValueError("TEMPORAL_IDEMPOTENCY_CONFLICT")
        result = json.loads(str(row["result_json"]))
        return {str(key): value for key, value in result.items()} if isinstance(result, dict) else {"result": result}

    def _store_temporal_idempotency(
        self,
        *,
        scope: tuple[str, str, str],
        operation: str,
        idempotency_key: str,
        payload_digest: str,
        result: dict[str, object],
        record_id: str | None,
        now: datetime,
    ) -> None:
        assert_safe_content(result)
        self._conn.execute(
            """INSERT INTO provisional_temporal_idempotency
               (store_uuid,principal_id,runtime_id,operation,idempotency_key,payload_digest,result_json,record_id,created_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (*scope, operation, str(idempotency_key).strip(), payload_digest,
             json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")), record_id, now.isoformat()),
        )

    def _temporal_event_cap_available(self, *, scope: tuple[str, str, str], table: str, error_code: str) -> None:
        """Fail closed at the durable per-scope event cap; pruning is maintenance-only."""

        row = self._conn.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE store_uuid=? AND principal_id=? AND runtime_id=?", scope
        ).fetchone()
        if int(row["count"] if row is not None else 0) >= _TEMPORAL_EVENT_HARD_CAP:
            raise ValueError(error_code)

    def _temporal_state_event_cap_available(self, *, scope: tuple[str, str, str]) -> None:
        """Never evict active record history to make room for a state mutation."""

        total_row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM provisional_temporal_state_events WHERE store_uuid=? AND principal_id=? AND runtime_id=?",
            scope,
        ).fetchone()
        if int(total_row["count"] if total_row is not None else 0) < _TEMPORAL_EVENT_HARD_CAP:
            return
        active_row = self._conn.execute(
            """SELECT COUNT(*) AS count
               FROM provisional_temporal_state_events AS event
               JOIN provisional_records AS record ON record.record_id = event.record_id
               WHERE event.store_uuid=? AND event.principal_id=? AND event.runtime_id=?
                 AND record.store_uuid=? AND record.principal_id=? AND record.runtime_id=?
                 AND record.temporal_disposition IN ('scheduled', 'snoozed')""",
            (*scope, *scope),
        ).fetchone()
        # A full state table cannot be made writable by a normal write.  The active
        # count is intentionally inspected so the protected case remains explicit.
        if int(active_row["count"] if active_row is not None else 0) >= _TEMPORAL_EVENT_HARD_CAP:
            raise ValueError("TEMPORAL_STATE_EVENT_CAP_REACHED")
        raise ValueError("TEMPORAL_STATE_EVENT_CAP_REACHED")

    def maintain_temporal_retention(
        self,
        *,
        now: datetime | str | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Explicitly prune temporal telemetry/history only; reads never call this.

        The method deliberately leaves provisional records and evidence untouched.
        Rows are selected and deleted in the specification's stable timestamp/id
        order so repeated maintenance passes are deterministic.
        """

        server_now = self._temporal_timestamp(now, field_name="now") if now is not None else self._clock().astimezone(timezone.utc)
        event_cutoff = (server_now - timedelta(days=_TEMPORAL_EVENT_RETENTION_DAYS)).isoformat()
        state_cutoff = (server_now - timedelta(days=_TEMPORAL_STATE_RETENTION_DAYS)).isoformat()
        terminal_idempotency_cutoff = (server_now - timedelta(days=_TEMPORAL_TERMINAL_IDEMPOTENCY_DAYS)).isoformat()
        nonterminal_idempotency_cutoff = (server_now - timedelta(days=_TEMPORAL_NONTERMINAL_IDEMPOTENCY_DAYS)).isoformat()
        deleted: dict[str, int] = {
            "turn_clock_events": 0,
            "delivery_events": 0,
            "state_events": 0,
            "idempotency_rows": 0,
        }

        def bounded_ids(table: str, id_column: str, scope: tuple[str, str, str]) -> list[tuple[str, str, str, str]]:
            rows = self._conn.execute(
                f"SELECT {id_column},observed_at_utc FROM {table} "
                "WHERE store_uuid=? AND principal_id=? AND runtime_id=? "
                f"ORDER BY observed_at_utc DESC,{id_column} DESC",
                scope,
            ).fetchall()
            keep = {
                str(row[id_column])
                for row in rows[:_TEMPORAL_RETAINED_EVENT_ROWS]
                if str(row["observed_at_utc"]) > event_cutoff
            }
            return [(*scope, str(row[id_column])) for row in reversed(rows) if str(row[id_column]) not in keep]

        with self._write_transaction(immediate=True):
            scopes = [tuple(str(row[key]) for key in ("store_uuid", "principal_id", "runtime_id")) for row in self._conn.execute(
                """SELECT store_uuid,principal_id,runtime_id FROM provisional_turn_clock_events
                   UNION SELECT store_uuid,principal_id,runtime_id FROM provisional_temporal_delivery_events"""
            ).fetchall()]
            turn_ids: list[tuple[str, str, str, str]] = []
            delivery_ids: list[tuple[str, str, str, str]] = []
            for scope in scopes:
                turn_ids.extend(bounded_ids("provisional_turn_clock_events", "event_id", scope))
                delivery_ids.extend(bounded_ids("provisional_temporal_delivery_events", "delivery_id", scope))
            state_rows = self._conn.execute(
                """SELECT event.event_id
                   FROM provisional_temporal_state_events AS event
                   JOIN provisional_records AS record ON record.record_id = event.record_id
                   WHERE record.temporal_disposition IN ('acknowledged', 'cancelled', 'expired')
                     AND record.store_uuid = event.store_uuid
                     AND record.principal_id = event.principal_id
                     AND record.runtime_id = event.runtime_id
                     AND (SELECT MAX(terminal.observed_at_utc)
                          FROM provisional_temporal_state_events AS terminal
                          WHERE terminal.record_id = record.record_id
                            AND terminal.store_uuid = record.store_uuid
                            AND terminal.principal_id = record.principal_id
                            AND terminal.runtime_id = record.runtime_id
                            AND terminal.new_disposition IN ('acknowledged', 'cancelled', 'expired')) <= ?
                   ORDER BY event.observed_at_utc ASC,event.event_id ASC""",
                (state_cutoff,),
            ).fetchall()
            idem_rows = self._conn.execute(
                """SELECT idem.store_uuid,idem.principal_id,idem.runtime_id,idem.operation,idem.idempotency_key
                   FROM provisional_temporal_idempotency AS idem
                   LEFT JOIN provisional_records AS record ON record.record_id = idem.record_id
                   WHERE (
                       record.temporal_disposition IN ('acknowledged', 'cancelled', 'expired')
                       AND (SELECT MAX(terminal.observed_at_utc)
                            FROM provisional_temporal_state_events AS terminal
                            WHERE terminal.record_id = record.record_id
                              AND terminal.store_uuid = record.store_uuid
                              AND terminal.principal_id = record.principal_id
                              AND terminal.runtime_id = record.runtime_id
                              AND terminal.new_disposition IN ('acknowledged', 'cancelled', 'expired')) <= ?
                   ) OR (
                       (record.record_id IS NULL OR record.temporal_disposition NOT IN ('acknowledged', 'cancelled', 'expired'))
                       AND COALESCE(record.created_at, idem.created_at_utc) <= ?
                   )
                   ORDER BY idem.created_at_utc ASC,idem.operation ASC,idem.idempotency_key ASC""",
                (terminal_idempotency_cutoff, nonterminal_idempotency_cutoff),
            ).fetchall()
            deleted.update({
                "turn_clock_events": len(turn_ids),
                "delivery_events": len(delivery_ids),
                "state_events": len(state_rows),
                "idempotency_rows": len(idem_rows),
            })
            if not dry_run:
                self._conn.executemany(
                    "DELETE FROM provisional_turn_clock_events WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND event_id=?",
                    turn_ids,
                )
                self._conn.executemany(
                    "DELETE FROM provisional_temporal_delivery_events WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND delivery_id=?",
                    delivery_ids,
                )
                self._conn.executemany(
                    "DELETE FROM provisional_temporal_state_events WHERE event_id=?",
                    [(str(row["event_id"]),) for row in state_rows],
                )
                self._conn.executemany(
                    """DELETE FROM provisional_temporal_idempotency
                       WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND operation=? AND idempotency_key=?""",
                    [tuple(row) for row in idem_rows],
                )
        return deleted

    @staticmethod
    def _effective_temporal_window(record: ProvisionalMemoryRecord) -> tuple[datetime, datetime]:
        if record.due_window_start_utc is None or record.due_window_end_utc is None:
            raise ValueError("TEMPORAL_WINDOW_UNAVAILABLE")
        start = record.snoozed_until_utc or record.due_window_start_utc
        duration = record.due_window_end_utc - record.due_window_start_utc
        end = start + duration
        return start, end

    def _temporal_projection(self, record: ProvisionalMemoryRecord, *, now: datetime) -> dict[str, object]:
        start, end = self._effective_temporal_window(record)
        if record.temporal_disposition not in {TemporalDisposition.SCHEDULED, TemporalDisposition.SNOOZED}:
            eligibility = "suppressed"
        elif now < start:
            eligibility = "pending"
        elif now < end:
            eligibility = "due"
        else:
            eligibility = "overdue"
        return {
            "record": record,
            "eligibility": eligibility,
            "effective_window_start_utc": start,
            "effective_window_end_utc": end,
        }

    def schedule_temporal(
        self,
        record_id: str,
        principal_id: str,
        runtime_id: str,
        *,
        temporal_kind: str,
        due_window_start_utc: datetime | str,
        due_window_end_utc: datetime | str,
        timezone_name: str,
        precision: str,
        original_expression: str,
        idempotency_key: str,
        expected_revision: int = 0,
        resolution_metadata: dict[str, object] | None = None,
        decay_not_before_utc: datetime | str | None = None,
        store_uuid: str | None = None,
    ) -> dict[str, object]:
        """Attach the one permitted initial temporal state to an existing provisional record."""
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        kind = str(temporal_kind or "").strip().lower()
        if kind not in {"reminder", "future_event"}:
            raise ValueError("TEMPORAL_KIND_INVALID")
        start = self._temporal_timestamp(due_window_start_utc, field_name="due_window_start_utc")
        end = self._temporal_timestamp(due_window_end_utc, field_name="due_window_end_utc")
        if end <= start:
            raise ValueError("TEMPORAL_WINDOW_INVALID")
        zone, precision_text, expression = str(timezone_name or "").strip(), str(precision or "").strip(), str(original_expression or "").strip()
        if not zone or precision_text not in {"exact", "date", "month", "approximate"} or not expression:
            raise ValueError("TEMPORAL_SCHEDULE_INVALID")
        resolution = dict(resolution_metadata or {})
        decay = self._temporal_timestamp(decay_not_before_utc, field_name="decay_not_before_utc") if decay_not_before_utc else end
        payload = {
            "record_id": str(record_id), "temporal_kind": kind, "start": start.isoformat(), "end": end.isoformat(),
            "timezone": zone, "precision": precision_text, "original_expression": expression,
            "resolution_metadata": resolution, "decay_not_before_utc": decay.isoformat(), "expected_revision": int(expected_revision),
        }
        digest = self._temporal_payload_digest(payload)
        now = self._clock().astimezone(timezone.utc)
        with self._write_transaction(immediate=True):
            replay = self._temporal_idempotency_replay(scope=scope, operation="schedule", idempotency_key=idempotency_key, payload_digest=digest)
            if replay is not None:
                return replay
            row = self._conn.execute("SELECT * FROM provisional_records WHERE record_id=?", (str(record_id),)).fetchone()
            if row is None:
                raise KeyError(f"unknown provisional record: {record_id}")
            record = self._row_to_record(row)
            if record.temporal_disposition is not TemporalDisposition.NONE or int(expected_revision) != record.temporal_revision:
                raise ValueError("TEMPORAL_REVISION_CONFLICT")
            if record.store_uuid and (record.store_uuid, record.principal_id, record.runtime_id) != scope:
                raise KeyError(f"unknown provisional record: {record_id}")
            self._temporal_state_event_cap_available(scope=scope)
            revision = record.temporal_revision + 1
            result = {"record_id": record.record_id, "disposition": TemporalDisposition.SCHEDULED.value, "revision": revision, "replayed": False}
            self._conn.execute(
                """UPDATE provisional_records SET store_uuid=?,principal_id=?,runtime_id=?,temporal_kind=?,temporal_disposition=?,temporal_revision=?,
                   due_window_start_utc=?,due_window_end_utc=?,temporal_timezone=?,temporal_precision=?,original_expression=?,temporal_resolution_json=?,
                   decay_not_before_utc=?,snoozed_until_utc=NULL,updated_at=? WHERE record_id=?""",
                (*scope, kind, TemporalDisposition.SCHEDULED.value, revision, start.isoformat(), end.isoformat(), zone, precision_text, expression,
                 json.dumps(resolution, ensure_ascii=True, sort_keys=True, separators=(",", ":")), decay.isoformat(), now.isoformat(), record.record_id),
            )
            self._conn.execute(
                """INSERT INTO provisional_temporal_state_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"tse_{uuid.uuid4().hex}", *scope, record.record_id, "schedule", record.temporal_disposition.value,
                 TemporalDisposition.SCHEDULED.value, record.temporal_revision, revision, now.isoformat(), str(idempotency_key).strip(), digest,
                 json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))),
            )
            self._store_temporal_idempotency(scope=scope, operation="schedule", idempotency_key=idempotency_key,
                                             payload_digest=digest, result=result, record_id=record.record_id, now=now)
        return result

    def get_temporal(self, record_id: str, principal_id: str, runtime_id: str, *, store_uuid: str | None = None, now_utc: datetime | str | None = None) -> dict[str, object]:
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        now = self._temporal_timestamp(now_utc, field_name="now_utc") if now_utc is not None else self._clock().astimezone(timezone.utc)
        with self._lock:
            row = self._conn.execute("SELECT * FROM provisional_records WHERE record_id=? AND store_uuid=? AND principal_id=? AND runtime_id=?", (str(record_id), *scope)).fetchone()
        if row is None:
            raise KeyError(f"unknown temporal record: {record_id}")
        return self._temporal_projection(self._row_to_record(row), now=now)

    def list_temporal(self, principal_id: str, runtime_id: str, *, store_uuid: str | None = None, due_only: bool = False,
                      include_upcoming: bool = True, include_suppressed: bool = False, limit: int = 10,
                      now_utc: datetime | str | None = None) -> list[dict[str, object]]:
        if not 1 <= int(limit) <= 2_000:
            raise ValueError("TEMPORAL_LIMIT_INVALID")
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        now = self._temporal_timestamp(now_utc, field_name="now_utc") if now_utc is not None else self._clock().astimezone(timezone.utc)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM provisional_records WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND temporal_disposition != 'none'",
                scope,
            ).fetchall()
        projections = [self._temporal_projection(self._row_to_record(row), now=now) for row in rows]
        if not include_suppressed:
            projections = [item for item in projections if item["eligibility"] != "suppressed"]
        if due_only:
            projections = [item for item in projections if item["eligibility"] in {"due", "overdue"}]
        elif not include_upcoming:
            projections = [item for item in projections if item["eligibility"] != "pending"]
        rank = {"overdue": 0, "due": 1, "pending": 2, "suppressed": 3}
        projections.sort(key=lambda item: (rank[str(item["eligibility"])], item["effective_window_start_utc"], item["record"].created_at, item["record"].record_id))
        return projections[: int(limit)]

    def resolve_temporal(self, record_id: str, principal_id: str, runtime_id: str, *, action: str, expected_revision: int,
                         idempotency_key: str, snoozed_until_utc: datetime | str | None = None,
                         store_uuid: str | None = None) -> dict[str, object]:
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        operation = str(action or "").strip().lower()
        target = {"acknowledge": TemporalDisposition.ACKNOWLEDGED, "cancel": TemporalDisposition.CANCELLED, "snooze": TemporalDisposition.SNOOZED}.get(operation)
        if target is None:
            raise ValueError("TEMPORAL_ACTION_INVALID")
        snooze = self._temporal_timestamp(snoozed_until_utc, field_name="snoozed_until_utc") if snoozed_until_utc is not None else None
        if target is TemporalDisposition.SNOOZED and snooze is None:
            raise ValueError("TEMPORAL_SNOOZE_REQUIRED")
        if target is not TemporalDisposition.SNOOZED and snooze is not None:
            raise ValueError("TEMPORAL_SNOOZE_UNEXPECTED")
        payload = {"record_id": str(record_id), "action": operation, "expected_revision": int(expected_revision), "snoozed_until_utc": snooze.isoformat() if snooze else None}
        digest = self._temporal_payload_digest(payload)
        now = self._clock().astimezone(timezone.utc)
        with self._write_transaction(immediate=True):
            replay = self._temporal_idempotency_replay(scope=scope, operation="resolve", idempotency_key=idempotency_key, payload_digest=digest)
            if replay is not None:
                return replay
            row = self._conn.execute("SELECT * FROM provisional_records WHERE record_id=? AND store_uuid=? AND principal_id=? AND runtime_id=?", (str(record_id), *scope)).fetchone()
            if row is None:
                raise KeyError(f"unknown temporal record: {record_id}")
            record = self._row_to_record(row)
            if record.temporal_disposition not in {TemporalDisposition.SCHEDULED, TemporalDisposition.SNOOZED} or record.temporal_revision != int(expected_revision):
                raise ValueError("TEMPORAL_REVISION_CONFLICT")
            self._temporal_state_event_cap_available(scope=scope)
            revision = record.temporal_revision + 1
            decay = record.decay_not_before_utc
            if snooze is not None:
                _, current_effective_end = self._effective_temporal_window(record)
                duration = record.due_window_end_utc - record.due_window_start_utc
                grace = max(timedelta(0), (decay or current_effective_end) - current_effective_end)
                decay = snooze + duration + grace
            result = {"record_id": record.record_id, "disposition": target.value, "revision": revision, "replayed": False}
            self._conn.execute(
                "UPDATE provisional_records SET temporal_disposition=?,temporal_revision=?,snoozed_until_utc=?,decay_not_before_utc=?,updated_at=? WHERE record_id=?",
                (target.value, revision, snooze.isoformat() if snooze else record.snoozed_until_utc.isoformat() if record.snoozed_until_utc else None,
                 decay.isoformat() if decay else None, now.isoformat(), record.record_id),
            )
            self._conn.execute("INSERT INTO provisional_temporal_state_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"tse_{uuid.uuid4().hex}", *scope, record.record_id, operation, record.temporal_disposition.value, target.value,
                 record.temporal_revision, revision, now.isoformat(), str(idempotency_key).strip(), digest,
                 json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))))
            self._store_temporal_idempotency(scope=scope, operation="resolve", idempotency_key=idempotency_key,
                                             payload_digest=digest, result=result, record_id=record.record_id, now=now)
        return result

    def expire_temporal(
        self,
        record_id: str,
        principal_id: str,
        runtime_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        now_utc: datetime | str | None = None,
        store_uuid: str | None = None,
    ) -> dict[str, object]:
        """Maintenance-only terminal transition after the protected grace anchor."""

        scope = self._temporal_scope(
            principal_id=principal_id,
            runtime_id=runtime_id,
            store_uuid=store_uuid,
        )
        now = (
            self._temporal_timestamp(now_utc, field_name="now_utc")
            if now_utc is not None
            else self._clock().astimezone(timezone.utc)
        )
        payload = {
            "record_id": str(record_id),
            "action": "expire",
            "expected_revision": int(expected_revision),
        }
        digest = self._temporal_payload_digest(payload)
        with self._write_transaction(immediate=True):
            replay = self._temporal_idempotency_replay(
                scope=scope,
                operation="expire",
                idempotency_key=idempotency_key,
                payload_digest=digest,
            )
            if replay is not None:
                return replay
            row = self._conn.execute(
                "SELECT * FROM provisional_records WHERE record_id=? AND store_uuid=? AND principal_id=? AND runtime_id=?",
                (str(record_id), *scope),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown temporal record: {record_id}")
            record = self._row_to_record(row)
            if (
                record.temporal_disposition not in {TemporalDisposition.SCHEDULED, TemporalDisposition.SNOOZED}
                or record.temporal_revision != int(expected_revision)
            ):
                raise ValueError("TEMPORAL_REVISION_CONFLICT")
            if record.decay_not_before_utc is None or now < record.decay_not_before_utc.astimezone(timezone.utc):
                raise ValueError("TEMPORAL_EXPIRY_NOT_ELIGIBLE")
            self._temporal_state_event_cap_available(scope=scope)
            revision = record.temporal_revision + 1
            result = {
                "record_id": record.record_id,
                "disposition": TemporalDisposition.EXPIRED.value,
                "revision": revision,
                "replayed": False,
            }
            self._conn.execute(
                "UPDATE provisional_records SET temporal_disposition=?,temporal_revision=?,updated_at=? WHERE record_id=?",
                (TemporalDisposition.EXPIRED.value, revision, now.isoformat(), record.record_id),
            )
            self._conn.execute(
                "INSERT INTO provisional_temporal_state_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"tse_{uuid.uuid4().hex}",
                    *scope,
                    record.record_id,
                    "expire",
                    record.temporal_disposition.value,
                    TemporalDisposition.EXPIRED.value,
                    record.temporal_revision,
                    revision,
                    now.isoformat(),
                    str(idempotency_key).strip(),
                    digest,
                    json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._store_temporal_idempotency(
                scope=scope,
                operation="expire",
                idempotency_key=idempotency_key,
                payload_digest=digest,
                result=result,
                record_id=record.record_id,
                now=now,
            )
        return result

    def record_turn_clock_event(self, principal_id: str, runtime_id: str, *, event_id: str, role: str, event_kind: str,
                                idempotency_key: str, timeline_id: str | None = None, provenance_status: str = "server_receipt",
                                signed_registration_issued_at_utc: datetime | str | None = None,
                                store_uuid: str | None = None) -> dict[str, object]:
        """Record only server-receipt clock facts; caller times are provenance, never the production clock."""
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        normalized_id, normalized_role, normalized_kind = str(event_id or "").strip(), str(role or "").strip().lower(), str(event_kind or "").strip().lower()
        if not normalized_id or normalized_role not in {"user", "assistant"} or normalized_kind not in {"server_receipt", "server_completion_receipt"}:
            raise ValueError("TEMPORAL_TURN_EVENT_INVALID")
        issued = self._temporal_timestamp(signed_registration_issued_at_utc, field_name="signed_registration_issued_at_utc") if signed_registration_issued_at_utc else None
        payload = {"event_id": normalized_id, "role": normalized_role, "event_kind": normalized_kind, "timeline_id": str(timeline_id or ""),
                   "provenance_status": str(provenance_status or "").strip(), "signed_registration_issued_at_utc": issued.isoformat() if issued else None}
        digest = self._temporal_payload_digest(payload)
        now = self._clock().astimezone(timezone.utc)
        with self._write_transaction(immediate=True):
            replay = self._temporal_idempotency_replay(scope=scope, operation="turn_clock", idempotency_key=idempotency_key, payload_digest=digest)
            if replay is not None:
                return replay
            collision = self._conn.execute("SELECT payload_digest FROM provisional_turn_clock_events WHERE event_id=?", (normalized_id,)).fetchone()
            if collision is not None and str(collision["payload_digest"]) != digest:
                raise ValueError("TEMPORAL_TURN_EVENT_CONFLICT")
            result = {"event_id": normalized_id, "observed_at_utc": now.isoformat(), "replayed": collision is not None}
            if collision is None:
                self._temporal_event_cap_available(
                    scope=scope,
                    table="provisional_turn_clock_events",
                    error_code="TEMPORAL_TURN_EVENT_CAP_REACHED",
                )
                self._conn.execute("INSERT INTO provisional_turn_clock_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (normalized_id, *scope, str(timeline_id or "") or None, normalized_role, normalized_kind, now.isoformat(),
                     str(provenance_status or "").strip(), issued.isoformat() if issued else None, str(idempotency_key).strip(), digest))
            self._store_temporal_idempotency(scope=scope, operation="turn_clock", idempotency_key=idempotency_key,
                                             payload_digest=digest, result=result, record_id=None, now=now)
        return result

    def latest_turn_clock_events(self, principal_id: str, runtime_id: str, *, store_uuid: str | None = None) -> dict[str, dict[str, object] | None]:
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        result: dict[str, dict[str, object] | None] = {"user": None, "assistant": None}
        with self._lock:
            for role in result:
                row = self._conn.execute(
                    """SELECT event_id,timeline_id,role,event_kind,observed_at_utc,provenance_status,signed_registration_issued_at_utc
                       FROM provisional_turn_clock_events WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND role=?
                       ORDER BY observed_at_utc DESC,event_id DESC LIMIT 1""", (*scope, role)
                ).fetchone()
                if row is not None:
                    result[role] = {key: row[key] for key in row.keys()}
        return result

    def record_delivery_event(self, record_id: str, principal_id: str, runtime_id: str, *, delivery_id: str, receipt_identity: str,
                              idempotency_key: str, payload_digest: str, store_uuid: str | None = None) -> dict[str, object]:
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        delivery, receipt, external_digest = str(delivery_id or "").strip(), str(receipt_identity or "").strip(), str(payload_digest or "").strip()
        if not delivery or not receipt or not re.fullmatch(r"[0-9a-f]{64}", external_digest):
            raise ValueError("TEMPORAL_DELIVERY_INVALID")
        payload = {"record_id": str(record_id), "delivery_id": delivery, "receipt_identity": receipt, "payload_digest": external_digest}
        digest = self._temporal_payload_digest(payload)
        now = self._clock().astimezone(timezone.utc)
        with self._write_transaction(immediate=True):
            replay = self._temporal_idempotency_replay(scope=scope, operation="delivery", idempotency_key=idempotency_key, payload_digest=digest)
            if replay is not None:
                return replay
            record = self._conn.execute("SELECT record_id FROM provisional_records WHERE record_id=? AND store_uuid=? AND principal_id=? AND runtime_id=?", (str(record_id), *scope)).fetchone()
            if record is None:
                raise KeyError(f"unknown temporal record: {record_id}")
            existing = self._conn.execute("SELECT receipt_identity,payload_digest FROM provisional_temporal_delivery_events WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND delivery_id=?", (*scope, delivery)).fetchone()
            if existing is not None and (str(existing["receipt_identity"]) != receipt or str(existing["payload_digest"]) != external_digest):
                raise ValueError("TEMPORAL_DELIVERY_CONFLICT")
            result = {"delivery_id": delivery, "record_id": str(record_id), "observed_at_utc": now.isoformat(), "replayed": existing is not None}
            if existing is None:
                self._temporal_event_cap_available(
                    scope=scope,
                    table="provisional_temporal_delivery_events",
                    error_code="TEMPORAL_DELIVERY_EVENT_CAP_REACHED",
                )
                self._conn.execute("INSERT INTO provisional_temporal_delivery_events VALUES(?,?,?,?,?,?,?,?,?)",
                    (*scope, delivery, str(record_id), receipt, now.isoformat(), str(idempotency_key).strip(), external_digest))
            self._store_temporal_idempotency(scope=scope, operation="delivery", idempotency_key=idempotency_key,
                                             payload_digest=digest, result=result, record_id=str(record_id), now=now)
        return result

    def latest_delivery_event(
        self,
        record_id: str,
        principal_id: str,
        runtime_id: str,
        *,
        store_uuid: str | None = None,
    ) -> dict[str, object] | None:
        """Return scoped access telemetry without mutating reminder or evidence state."""

        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        with self._lock:
            row = self._conn.execute(
                """SELECT delivery_id,record_id,receipt_identity,observed_at_utc
                   FROM provisional_temporal_delivery_events
                   WHERE store_uuid=? AND principal_id=? AND runtime_id=? AND record_id=?
                   ORDER BY observed_at_utc DESC,delivery_id DESC LIMIT 1""",
                (*scope, str(record_id)),
            ).fetchone()
        return {str(key): row[key] for key in row.keys()} if row is not None else None

    def temporal_diagnostics(self, principal_id: str, runtime_id: str, *, store_uuid: str | None = None) -> dict[str, int]:
        """Aggregate-only temporal read; it deliberately exposes no reminder text."""
        scope = self._temporal_scope(principal_id=principal_id, runtime_id=runtime_id, store_uuid=store_uuid)
        with self._lock:
            rows = self._conn.execute(
                "SELECT temporal_disposition,COUNT(*) AS count FROM provisional_records WHERE store_uuid=? AND principal_id=? AND runtime_id=? GROUP BY temporal_disposition", scope
            ).fetchall()
            deliveries = self._conn.execute("SELECT COUNT(*) FROM provisional_temporal_delivery_events WHERE store_uuid=? AND principal_id=? AND runtime_id=?", scope).fetchone()[0]
            turns = self._conn.execute("SELECT COUNT(*) FROM provisional_turn_clock_events WHERE store_uuid=? AND principal_id=? AND runtime_id=?", scope).fetchone()[0]
        result = {f"{item.value}_count": 0 for item in TemporalDisposition}
        result.update({f"{str(row['temporal_disposition'])}_count": int(row["count"]) for row in rows})
        result["delivery_count"] = int(deliveries)
        result["turn_clock_event_count"] = int(turns)
        return result

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
                    superseded_by_record_id, conflict_with_json, created_at, updated_at, last_reinforced_at,
                    metadata_json, dedupe_key, claim_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    record.claim_key,
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
                    superseded_by_record_id, conflict_with_json, created_at, updated_at, last_reinforced_at,
                    metadata_json, dedupe_key, claim_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    replacement.claim_key,
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

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        include_dormant: bool = False,
        dormant_only: bool = False,
    ) -> list[ProvisionalSearchHit]:
        statuses = (
            (ProvisionalMemoryStatus.DORMANT.value,)
            if dormant_only
            else (
                ProvisionalMemoryStatus.ACTIVE.value,
                ProvisionalMemoryStatus.CONFLICTED.value,
                *([ProvisionalMemoryStatus.DORMANT.value] if include_dormant else []),
            )
        )
        placeholders = ", ".join("?" for _ in statuses)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM provisional_records
                WHERE status IN ({placeholders})
                ORDER BY updated_at DESC, record_id ASC
                """,
                statuses,
            ).fetchall()
        hits: list[ProvisionalSearchHit] = []
        for row in rows:
            record = self._row_to_record(row)
            score, matched = _score_record(record, query)
            if score <= 0.0 and matched == []:
                continue
            if record.lifecycle is ProvisionalLifecycle.DORMANT:
                score *= 0.55
            if record.lifecycle is ProvisionalLifecycle.DORMANT:
                score *= 0.55
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
    "TemporalDisposition",
    "source_role_eligible",
]
