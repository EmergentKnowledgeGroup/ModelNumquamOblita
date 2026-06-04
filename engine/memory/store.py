from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Optional
from uuid import uuid4

from ..contracts import AtomType, CandidateAtom, NormalizedTurn, SourceRef

_HALF_LIFE_SCALARS: dict[AtomType, float] = {
    AtomType.EPISODE: 2.0 / 3.0,
    AtomType.ATOMIC_FACT: 1.5,
    AtomType.RELATIONAL: 1.0,
    AtomType.AFFECTIVE: 0.75,
    AtomType.PROCEDURAL_STYLE: 1.25,
}


def half_life_days_for_atom_type(*, base_half_life_days: int, atom_type: AtomType) -> int:
    """Return type-aware default half-life days for newly created atoms."""

    base = max(1, int(base_half_life_days))
    scale = float(_HALF_LIFE_SCALARS.get(atom_type, 1.0))
    return max(1, int(round(float(base) * scale)))


class AtomStatus(str, Enum):
    """Allowed lifecycle statuses for stored atoms."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    TOMBSTONED = "tombstoned"


class EventType(str, Enum):
    """Append-only provenance event types."""

    ADD = "ADD"
    REINFORCE = "REINFORCE"
    CONFLICT = "CONFLICT"
    SUPERSEDE = "SUPERSEDE"
    TOMBSTONE = "TOMBSTONE"
    PURGE = "PURGE"


@dataclass(slots=True)
class MemoryAtom:
    """Canonical persisted atom with provenance-linked metadata."""

    atom_id: str
    atom_type: AtomType
    canonical_text: str
    source_refs: list[SourceRef]
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    confidence: float = 0.0
    salience: float = 0.0
    salience_half_life_days: int = 180
    last_reinforced_at: Optional[datetime] = None
    support_count: int = 1
    contradiction_count: int = 0
    status: AtomStatus = AtomStatus.ACTIVE
    version_of: Optional[str] = None
    tombstoned_at: Optional[datetime] = None
    purge_after: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Validate atom invariants for safe persistence."""

        if not self.atom_id.strip():
            raise ValueError("atom_id is required")
        if not self.canonical_text.strip():
            raise ValueError("canonical_text is required")
        if not self.source_refs:
            raise ValueError("source_refs is required")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        if not (0.0 <= self.salience <= 1.0):
            raise ValueError("salience must be in [0, 1]")
        if self.salience_half_life_days <= 0:
            raise ValueError("salience_half_life_days must be > 0")
        if self.support_count <= 0:
            raise ValueError("support_count must be > 0")
        if self.tombstoned_at and self.purge_after and self.purge_after < self.tombstoned_at:
            raise ValueError("purge_after must be >= tombstoned_at")


@dataclass(slots=True)
class ProvenanceEvent:
    """Single immutable provenance event."""

    event_id: str
    event_type: EventType
    atom_id: str
    timestamp: datetime
    source_refs: list[SourceRef]
    reason: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ContradictionEdge:
    """Relationship entry between contradictory atoms."""

    left_atom_id: str
    right_atom_id: str
    created_at: datetime
    reason: str


@dataclass(slots=True)
class RawContextTurn:
    """Read-only source-preserved turn captured alongside import."""

    source_id: str
    sequence_index: int
    role: str
    quote_text: str
    message_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    conversation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if self.sequence_index < 0:
            raise ValueError("sequence_index must be >= 0")
        if not str(self.role or "").strip():
            raise ValueError("role is required")
        if not str(self.quote_text or ""):
            raise ValueError("quote_text is required")


@dataclass(slots=True)
class RecognitionRecord:
    """Persistent recognition signal captured after retrieval/writeback."""

    event_id: str
    atom_id: str
    recognized: bool
    score: float
    query_text: str
    timestamp: datetime


class ProvenanceLedger:
    """Append-only event log used for auditing memory mutations."""

    def __init__(self) -> None:
        """Initialize empty provenance event storage."""

        self._events: list[ProvenanceEvent] = []

    def append(self, event: ProvenanceEvent) -> None:
        """Append a provenance event to the immutable log."""

        self._events.append(event)

    def all_events(self) -> list[ProvenanceEvent]:
        """Return all recorded events in insertion order."""

        return list(self._events)

    def events_for_atom(self, atom_id: str) -> list[ProvenanceEvent]:
        """Return all events associated with an atom id."""

        return [event for event in self._events if event.atom_id == atom_id]


class AtomStore:
    """In-memory atom repository with append-only provenance and conflict graph."""

    def __init__(self, *, salience_half_life_days: int = 180) -> None:
        """Initialize store with default decay metadata policy."""

        if salience_half_life_days <= 0:
            raise ValueError("salience_half_life_days must be > 0")
        self.salience_half_life_days = salience_half_life_days
        self._atoms: dict[str, MemoryAtom] = {}
        self._dedupe_index: dict[str, str] = {}
        self._conflicts: dict[str, set[str]] = defaultdict(set)
        self._shared_language: dict[str, dict[str, Any]] = {}
        self._raw_turns_by_source: dict[str, list[RawContextTurn]] = defaultdict(list)
        self._recognition_events: list[RecognitionRecord] = []
        self._cache_scope_id = f"atom-store:{uuid4().hex}"
        self.ledger = ProvenanceLedger()

    def _now(self) -> datetime:
        """Return current UTC timestamp."""

        return datetime.now(timezone.utc)

    @staticmethod
    def _dedupe_key(
        *,
        atom_type: AtomType,
        canonical_text: str,
        entities: Iterable[str],
        topics: Iterable[str],
    ) -> str:
        """Build conservative dedupe fingerprint to avoid unrelated merges."""

        payload = "|".join(
            [
                atom_type.value,
                canonical_text.strip().lower(),
                ",".join(sorted(item.strip().lower() for item in entities if item.strip())),
                ",".join(sorted(item.strip().lower() for item in topics if item.strip())),
            ]
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def add_candidate(self, candidate: CandidateAtom, *, reason: str = "extractor_add") -> MemoryAtom:
        """Add candidate atom or reinforce exact dedupe match.

        This method never mutates canonical text in place.
        """

        now = self._now()
        key = self._dedupe_key(
            atom_type=candidate.atom_type,
            canonical_text=candidate.canonical_text,
            entities=candidate.entities,
            topics=candidate.topics,
        )
        existing_id = self._dedupe_index.get(key)
        if existing_id is None:
            atom = MemoryAtom(
                atom_id=f"mem_{uuid4().hex}",
                atom_type=candidate.atom_type,
                canonical_text=candidate.canonical_text.strip(),
                source_refs=list(candidate.source_refs),
                entities=list(candidate.entities),
                topics=list(candidate.topics),
                confidence=candidate.confidence,
                salience=candidate.salience,
                salience_half_life_days=half_life_days_for_atom_type(
                    base_half_life_days=self.salience_half_life_days,
                    atom_type=candidate.atom_type,
                ),
                last_reinforced_at=now,
                created_at=now,
                updated_at=now,
            )
            self._atoms[atom.atom_id] = atom
            self._dedupe_index[key] = atom.atom_id
            self.ledger.append(
                ProvenanceEvent(
                    event_id=f"evt_{uuid4().hex}",
                    event_type=EventType.ADD,
                    atom_id=atom.atom_id,
                    timestamp=now,
                    source_refs=list(candidate.source_refs),
                    reason=reason,
                )
            )
            return atom

        atom = self._atoms[existing_id]
        atom.source_refs.extend(candidate.source_refs)
        atom.support_count += 1
        atom.last_reinforced_at = now
        atom.updated_at = now
        atom.confidence = max(atom.confidence, candidate.confidence)
        atom.salience = max(atom.salience, candidate.salience)
        self.ledger.append(
            ProvenanceEvent(
                event_id=f"evt_{uuid4().hex}",
                event_type=EventType.REINFORCE,
                atom_id=atom.atom_id,
                timestamp=now,
                source_refs=list(candidate.source_refs),
                reason=reason,
            )
        )
        return atom

    def get_atom(self, atom_id: str) -> MemoryAtom:
        """Fetch a stored atom by id."""

        return self._atoms[atom_id]

    def list_atoms(self) -> list[MemoryAtom]:
        """Return all stored atoms."""

        return list(self._atoms.values())

    def record_raw_turn(self, turn: NormalizedTurn) -> RawContextTurn:
        """Persist source-preserved turn text for bounded quote/provenance recall."""

        source_id = str(turn.source_id or "").strip()
        message_id = str(turn.message_id or "").strip() or None
        sequence_index = int(turn.sequence_index if turn.sequence_index is not None else len(self._raw_turns_by_source[source_id]))
        record = RawContextTurn(
            source_id=source_id,
            conversation_id=str(turn.conversation_id or "").strip() or None,
            message_id=message_id,
            sequence_index=sequence_index,
            role=str(turn.role or "").strip().lower(),
            quote_text=str(turn.quote_text if turn.quote_text is not None else turn.text),
            timestamp=turn.timestamp,
        )
        rows = self._raw_turns_by_source[source_id]
        for idx, existing in enumerate(rows):
            if existing.message_id and record.message_id and existing.message_id == record.message_id:
                rows[idx] = record
                rows.sort(key=lambda item: item.sequence_index)
                return record
            if existing.sequence_index == record.sequence_index and existing.message_id == record.message_id:
                rows[idx] = record
                rows.sort(key=lambda item: item.sequence_index)
                return record
        rows.append(record)
        rows.sort(key=lambda item: item.sequence_index)
        return record

    def fetch_raw_context_slice(
        self,
        source_id: str,
        *,
        message_id: str | None = None,
        sequence_index: int | None = None,
        before: int = 1,
        after: int = 1,
        max_turns: int = 3,
        max_chars: int = 1200,
    ) -> list[RawContextTurn]:
        """Return bounded neighboring raw turns for the requested source/message."""

        rows = list(self._raw_turns_by_source.get(str(source_id or "").strip(), []))
        if not rows:
            return []
        center = None
        target_message_id = str(message_id or "").strip() or None
        if target_message_id is not None:
            for idx, row in enumerate(rows):
                if row.message_id == target_message_id:
                    center = idx
                    break
        if center is None and sequence_index is not None:
            for idx, row in enumerate(rows):
                if row.sequence_index == int(sequence_index):
                    center = idx
                    break
        if center is None:
            return []
        start = max(0, center - max(0, int(before)))
        end = min(len(rows), center + max(0, int(after)) + 1)
        window = rows[start:end][: max(1, int(max_turns))]
        bounded: list[RawContextTurn] = []
        chars_used = 0
        budget = max(1, int(max_chars))
        for row in window:
            text = str(row.quote_text or "")
            remaining = budget - chars_used
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[: max(1, remaining - 1)].rstrip() + "…"
            bounded.append(
                RawContextTurn(
                    source_id=row.source_id,
                    conversation_id=row.conversation_id,
                    message_id=row.message_id,
                    sequence_index=row.sequence_index,
                    role=row.role,
                    quote_text=text,
                    timestamp=row.timestamp,
                )
            )
            chars_used += len(text)
        return bounded

    def _drop_dedupe_links(self, atom_id: str) -> None:
        """Remove dedupe index pointers targeting an atom."""

        dead_keys = [key for key, value in self._dedupe_index.items() if value == atom_id]
        for key in dead_keys:
            self._dedupe_index.pop(key, None)

    def supersede_atom(self, atom_id: str, replacement: CandidateAtom, *, reason: str = "manual_update") -> MemoryAtom:
        """Create a replacement atom while preserving historical record.

        Existing atom remains immutable in canonical text and is marked as superseded.
        """

        old = self._atoms[atom_id]
        old.status = AtomStatus.SUPERSEDED
        old.updated_at = self._now()
        replacement_atom = self.add_candidate(replacement, reason=reason)
        replacement_atom.version_of = old.atom_id
        replacement_atom.updated_at = self._now()

        self.ledger.append(
            ProvenanceEvent(
                event_id=f"evt_{uuid4().hex}",
                event_type=EventType.SUPERSEDE,
                atom_id=old.atom_id,
                timestamp=self._now(),
                source_refs=list(replacement.source_refs),
                reason=reason,
                metadata={"replacement_atom_id": replacement_atom.atom_id},
            )
        )
        return replacement_atom

    def mark_conflict(self, left_atom_id: str, right_atom_id: str, *, reason: str) -> ContradictionEdge:
        """Record contradiction edge without deleting either atom."""

        if left_atom_id == right_atom_id:
            raise ValueError("conflict requires two distinct atom ids")
        left = self._atoms[left_atom_id]
        right = self._atoms[right_atom_id]
        left.status = AtomStatus.CONFLICTED
        right.status = AtomStatus.CONFLICTED
        left.contradiction_count += 1
        right.contradiction_count += 1
        left.updated_at = self._now()
        right.updated_at = self._now()

        self._conflicts[left_atom_id].add(right_atom_id)
        self._conflicts[right_atom_id].add(left_atom_id)

        edge = ContradictionEdge(
            left_atom_id=left_atom_id,
            right_atom_id=right_atom_id,
            created_at=self._now(),
            reason=reason,
        )
        self.ledger.append(
            ProvenanceEvent(
                event_id=f"evt_{uuid4().hex}",
                event_type=EventType.CONFLICT,
                atom_id=left_atom_id,
                timestamp=edge.created_at,
                source_refs=[],
                reason=reason,
                metadata={"other_atom_id": right_atom_id},
            )
        )
        return edge

    def conflict_neighbors(self, atom_id: str) -> set[str]:
        """Return ids of atoms marked as contradictory to target atom."""

        return set(self._conflicts.get(atom_id, set()))

    def conflict_map(self) -> dict[str, set[str]]:
        """Return a snapshot of all contradiction edges."""

        return {atom_id: set(neighbors) for atom_id, neighbors in self._conflicts.items()}

    def cache_scope(self) -> str:
        return self._cache_scope_id

    def cache_token(self) -> tuple[object, ...]:
        """Return retrieval-cache invalidation token."""

        latest_atom_update = max((atom.updated_at.isoformat() for atom in self._atoms.values()), default="")
        latest_shared_update = max(
            (str(payload.get("updated_at") or "") for payload in self._shared_language.values()),
            default="",
        )
        mutation_count = len(self.ledger.all_events())
        return (
            "atom-store-cache-v2",
            self._cache_scope_id,
            len(self._atoms),
            len(self._conflicts),
            len(self._shared_language),
            latest_atom_update,
            latest_shared_update,
            sum(len(items) for items in self._raw_turns_by_source.values()),
            mutation_count,
        )

    def tombstone_atom(
        self,
        atom_id: str,
        *,
        reason: str,
        retention_days: int = 30,
    ) -> MemoryAtom:
        """Mark atom as tombstoned and schedule delayed purge."""

        if retention_days < 0:
            raise ValueError("retention_days must be >= 0")
        atom = self._atoms[atom_id]
        now = self._now()
        atom.status = AtomStatus.TOMBSTONED
        atom.tombstoned_at = now
        atom.purge_after = now + timedelta(days=retention_days)
        atom.updated_at = now

        self.ledger.append(
            ProvenanceEvent(
                event_id=f"evt_{uuid4().hex}",
                event_type=EventType.TOMBSTONE,
                atom_id=atom.atom_id,
                timestamp=now,
                source_refs=[],
                reason=reason,
                metadata={"retention_days": str(retention_days)},
            )
        )
        return atom

    def purge_due_atoms(self, *, now: Optional[datetime] = None) -> list[str]:
        """Purge tombstoned atoms whose retention window has elapsed."""

        as_of = now or self._now()
        to_purge = [
            atom_id
            for atom_id, atom in self._atoms.items()
            if atom.status == AtomStatus.TOMBSTONED
            and atom.purge_after is not None
            and atom.purge_after <= as_of
        ]
        purged: list[str] = []
        for atom_id in to_purge:
            self._drop_dedupe_links(atom_id)
            self._atoms.pop(atom_id, None)
            for neighbor in list(self._conflicts.get(atom_id, set())):
                self._conflicts[neighbor].discard(atom_id)
            self._conflicts.pop(atom_id, None)
            self.ledger.append(
                ProvenanceEvent(
                    event_id=f"evt_{uuid4().hex}",
                    event_type=EventType.PURGE,
                    atom_id=atom_id,
                    timestamp=as_of,
                    source_refs=[],
                    reason="retention_elapsed",
                )
            )
            purged.append(atom_id)
        return purged

    def upsert_shared_language_key(
        self,
        *,
        phrase: str,
        atom_ids: list[str],
        aliases: list[str] | None = None,
        domains: list[str] | None = None,
        support_count: int = 1,
        weight: float = 0.8,
        confidence: float = 0.8,
        curated: bool = False,
        key_id: str | None = None,
    ) -> dict[str, Any]:
        """Create/update shared-language key and enforce atom provenance links."""

        normalized = phrase.strip().lower()
        if not normalized:
            raise ValueError("phrase is required")
        linked_ids = sorted({str(item).strip() for item in atom_ids if str(item).strip()})
        if not linked_ids:
            raise ValueError("atom_ids is required")
        missing = [atom_id for atom_id in linked_ids if atom_id not in self._atoms]
        if missing:
            raise ValueError(f"unknown atom ids: {', '.join(missing)}")

        now = self._now().isoformat()
        existing_key_id: str | None = None
        for maybe_key_id, payload in self._shared_language.items():
            if str(payload.get("phrase") or "").strip().lower() == normalized:
                existing_key_id = maybe_key_id
                break
        resolved_key_id = existing_key_id or key_id or f"slk_{uuid4().hex[:12]}"

        aliases_norm = sorted({item.strip() for item in (aliases or []) if item and item.strip()})
        domains_norm = sorted({item.strip().lower() for item in (domains or []) if item and item.strip()})
        prior = self._shared_language.get(resolved_key_id)
        created_at = str(prior.get("created_at")) if prior else now
        payload = {
            "key_id": resolved_key_id,
            "phrase": phrase.strip(),
            "atom_ids": linked_ids,
            "aliases": aliases_norm,
            "domains": domains_norm,
            "support_count": max(1, int(support_count)),
            "weight": max(0.0, min(1.0, float(weight))),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "curated": bool(curated),
            "created_at": created_at,
            "updated_at": now,
        }
        self._shared_language[resolved_key_id] = payload
        return dict(payload)

    def list_shared_language_keys(self) -> list[dict[str, Any]]:
        """Return shared-language keys in stable order."""

        rows = list(self._shared_language.values())
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return [dict(row) for row in rows]

    def record_recognition_event(
        self,
        *,
        atom_id: str,
        recognized: bool,
        score: float,
        query_text: str,
        timestamp: Optional[datetime] = None,
    ) -> RecognitionRecord:
        """Persist one recognition event for salience/decay feedback."""

        if atom_id not in self._atoms:
            raise ValueError(f"unknown atom id: {atom_id}")
        event = RecognitionRecord(
            event_id=f"rec_{uuid4().hex}",
            atom_id=atom_id,
            recognized=bool(recognized),
            score=max(0.0, min(1.0, float(score))),
            query_text=str(query_text or "").strip(),
            timestamp=timestamp or self._now(),
        )
        self._recognition_events.append(event)
        return event

    def list_recognition_events(
        self,
        *,
        atom_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[RecognitionRecord]:
        """Return recognition events ordered by timestamp ascending."""

        rows = [event for event in self._recognition_events if atom_id is None or event.atom_id == atom_id]
        rows.sort(key=lambda item: item.timestamp)
        if limit is not None and limit >= 0:
            rows = rows[-int(limit) :]
        return list(rows)

    def recognition_bias(self, atom_id: str, *, window: int = 16) -> float:
        """Return signed recognition bias in [-1, 1] for one atom."""

        events = self.list_recognition_events(atom_id=atom_id, limit=window)
        if not events:
            return 0.0
        signed = [(event.score if event.recognized else -event.score) for event in events]
        return max(-1.0, min(1.0, sum(signed) / len(signed)))

    def recognition_stats(self) -> dict[str, float]:
        """Return aggregate recognition metrics for diagnostics surfaces."""

        total = len(self._recognition_events)
        if total == 0:
            return {"events": 0.0, "recognized": 0.0, "unrecognized": 0.0, "recognized_rate": 0.0}
        recognized = sum(1 for event in self._recognition_events if event.recognized)
        unrecognized = total - recognized
        return {
            "events": float(total),
            "recognized": float(recognized),
            "unrecognized": float(unrecognized),
            "recognized_rate": recognized / max(total, 1),
        }
