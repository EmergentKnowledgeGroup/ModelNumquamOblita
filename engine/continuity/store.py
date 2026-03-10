from __future__ import annotations

from copy import deepcopy
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean
import threading
from uuid import uuid4

from .model import ContinuitySnapshot, RecognitionEvent


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class ContinuityExpansion:
    """Single-snapshot continuity expansion payload for retrieval."""

    revision: int
    constellation_neighbors: dict[str, set[str]]
    arc_neighbors: dict[str, set[str]]
    shared_boosts: dict[str, float]
    recognition_bonus: dict[str, float]


@dataclass(slots=True)
class RecognitionTelemetry:
    """Recognition event log with bounded influence scoring."""

    _events: list[RecognitionEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(
        self,
        *,
        atom_id: str,
        recognized: bool,
        score: float,
        query_text: str,
        timestamp: datetime | None = None,
    ) -> RecognitionEvent:
        event = RecognitionEvent(
            event_id=f"rec_{uuid4().hex}",
            atom_id=atom_id,
            recognized=recognized,
            score=_clamp(score, 0.0, 1.0),
            query_text=query_text.strip(),
            timestamp=timestamp or datetime.now(timezone.utc),
        )
        with self._lock:
            self._events.append(event)
        return event

    def events(self) -> list[RecognitionEvent]:
        with self._lock:
            return list(self._events)

    def load(self, events: list[RecognitionEvent], *, replace: bool = False) -> None:
        with self._lock:
            if replace:
                self._events = list(events)
                return
            self._events.extend(events)

    def atom_bonus(self, atom_id: str, *, window: int = 16) -> float:
        with self._lock:
            relevant = [evt for evt in self._events if evt.atom_id == atom_id][-window:]
        if not relevant:
            return 0.0
        signed_scores = [evt.score if evt.recognized else -evt.score for evt in relevant]
        avg = mean(signed_scores)
        return _clamp(avg * 0.06, -0.06, 0.06)

    def bonus_map(self, atom_ids: set[str]) -> dict[str, float]:
        return {atom_id: self.atom_bonus(atom_id) for atom_id in atom_ids}


@dataclass(slots=True)
class ContinuityStore:
    """Runtime continuity store for snapshot layers and telemetry."""

    snapshot: ContinuitySnapshot | None = None
    telemetry: RecognitionTelemetry = field(default_factory=RecognitionTelemetry)
    _cache_scope_id: str = field(default_factory=lambda: f"continuity:{uuid4().hex}")
    _snapshot_revision: int = 0
    _snapshot_lock: threading.Lock = field(default_factory=threading.Lock)
    _cache_lock: threading.Lock = field(default_factory=threading.Lock)
    _cached_graph_revision: int = -1
    _cached_constellation_neighbors: dict[str, set[str]] = field(default_factory=dict)
    _cached_arc_neighbors: dict[str, set[str]] = field(default_factory=dict)
    _cached_atom_ids: set[str] = field(default_factory=set)

    def set_snapshot(self, snapshot: ContinuitySnapshot) -> int:
        with self._snapshot_lock:
            self.snapshot = deepcopy(snapshot)
            self._snapshot_revision += 1
            with self._cache_lock:
                self._cached_graph_revision = -1
                self._cached_constellation_neighbors = {}
                self._cached_arc_neighbors = {}
                self._cached_atom_ids = set()
            return self._snapshot_revision

    def snapshot_view(self) -> tuple[int, ContinuitySnapshot | None]:
        with self._snapshot_lock:
            active = deepcopy(self.snapshot) if self.snapshot is not None else None
            return self._snapshot_revision, active

    def cache_scope(self) -> str:
        return self._cache_scope_id

    def cache_token(self) -> tuple[str, int, str]:
        revision, _snapshot = self.snapshot_view()
        return (self._cache_scope_id, int(revision), self._snapshot_fingerprint(_snapshot))

    def constellation_neighbors(self, snapshot: ContinuitySnapshot | None = None) -> dict[str, set[str]]:
        if snapshot is not None:
            return self._build_constellation_neighbors(snapshot)
        revision, active = self.snapshot_view()
        if not active:
            return {}
        self._ensure_graph_cache(revision=revision, snapshot=active)
        with self._cache_lock:
            return self._cached_constellation_neighbors

    def arc_neighbors(self, snapshot: ContinuitySnapshot | None = None) -> dict[str, set[str]]:
        if snapshot is not None:
            return self._build_arc_neighbors(snapshot)
        revision, active = self.snapshot_view()
        if not active:
            return {}
        self._ensure_graph_cache(revision=revision, snapshot=active)
        with self._cache_lock:
            return self._cached_arc_neighbors

    def shared_language_match_ids(self, query: str, *, snapshot: ContinuitySnapshot | None = None) -> set[str]:
        return set(self.shared_language_boosts(query, snapshot=snapshot).keys())

    def shared_language_boosts(
        self,
        query: str,
        *,
        snapshot: ContinuitySnapshot | None = None,
    ) -> dict[str, float]:
        active = snapshot if snapshot is not None else self.snapshot_view()[1]
        if not active:
            return {}
        q = query.lower()
        matched: dict[str, float] = {}
        for key in active.shared_language_keys:
            candidates = [key.phrase, *list(key.aliases)]
            if any(token and token.lower() in q for token in candidates):
                base_boost = _clamp(key.weight * 0.10 + key.confidence * 0.08, 0.02, 0.18)
                for atom_id in key.atom_ids:
                    matched[atom_id] = max(matched.get(atom_id, 0.0), base_boost)
        return matched

    def recognition_bonus_map(self, *, snapshot: ContinuitySnapshot | None = None) -> dict[str, float]:
        if snapshot is not None:
            atom_ids: set[str] = set()
            for constellation in snapshot.constellations:
                atom_ids.update(constellation.atom_ids)
            for arc in snapshot.narrative_arcs:
                atom_ids.update(arc.atom_ids)
            for key in snapshot.shared_language_keys:
                atom_ids.update(key.atom_ids)
            return self.telemetry.bonus_map(atom_ids)
        revision, active = self.snapshot_view()
        if not active:
            return {}
        self._ensure_graph_cache(revision=revision, snapshot=active)
        with self._cache_lock:
            atom_ids = set(self._cached_atom_ids)
        return self.telemetry.bonus_map(atom_ids)

    def expansion_for_query(self, query: str) -> ContinuityExpansion:
        revision, snapshot = self.snapshot_view()
        if snapshot is None:
            return ContinuityExpansion(
                revision=revision,
                constellation_neighbors={},
                arc_neighbors={},
                shared_boosts={},
                recognition_bonus={},
            )
        self._ensure_graph_cache(revision=revision, snapshot=snapshot)
        shared_boosts = self.shared_language_boosts(query, snapshot=snapshot)
        with self._cache_lock:
            constellation_neighbors = self._cached_constellation_neighbors
            arc_neighbors = self._cached_arc_neighbors
            atom_ids = set(self._cached_atom_ids)
        return ContinuityExpansion(
            revision=revision,
            constellation_neighbors=constellation_neighbors,
            arc_neighbors=arc_neighbors,
            shared_boosts=shared_boosts,
            recognition_bonus=self.telemetry.bonus_map(atom_ids),
        )

    def warm_snapshot_cache(self) -> None:
        revision, snapshot = self.snapshot_view()
        if snapshot is None:
            return
        self._ensure_graph_cache(revision=revision, snapshot=snapshot)

    def _snapshot_fingerprint(self, snapshot: ContinuitySnapshot | None) -> str:
        if snapshot is None:
            return "none"
        constellation_bits = tuple(
            sorted(
                (
                    str(constellation.constellation_id),
                    tuple(sorted(str(atom_id) for atom_id in constellation.atom_ids)),
                )
                for constellation in snapshot.constellations
            )
        )
        arc_bits = tuple(
            sorted(
                (
                    str(arc.arc_id),
                    tuple(sorted(str(atom_id) for atom_id in arc.atom_ids)),
                )
                for arc in snapshot.narrative_arcs
            )
        )
        shared_bits = tuple(
            sorted(
                (
                    str(key.key_id),
                    str(key.phrase).strip().lower(),
                    tuple(sorted(str(alias).strip().lower() for alias in key.aliases)),
                    tuple(sorted(str(atom_id) for atom_id in key.atom_ids)),
                    round(float(key.weight), 6),
                    round(float(key.confidence), 6),
                )
                for key in snapshot.shared_language_keys
            )
        )
        return repr((snapshot.generated_at.isoformat(), constellation_bits, arc_bits, shared_bits))

    def _ensure_graph_cache(self, *, revision: int, snapshot: ContinuitySnapshot) -> None:
        with self._cache_lock:
            if self._cached_graph_revision == revision:
                return
            constellation = self._build_constellation_neighbors(snapshot)
            arc = self._build_arc_neighbors(snapshot)
            atom_ids: set[str] = set()
            atom_ids.update(constellation.keys())
            atom_ids.update(arc.keys())
            for key in snapshot.shared_language_keys:
                atom_ids.update(key.atom_ids)
            self._cached_constellation_neighbors = constellation
            self._cached_arc_neighbors = arc
            self._cached_atom_ids = atom_ids
            self._cached_graph_revision = revision

    def _build_constellation_neighbors(self, snapshot: ContinuitySnapshot) -> dict[str, set[str]]:
        result: dict[str, set[str]] = defaultdict(set)
        for constellation in snapshot.constellations:
            for atom_id in constellation.atom_ids:
                for peer in constellation.atom_ids:
                    if peer != atom_id:
                        result[atom_id].add(peer)
        return dict(result)

    def _build_arc_neighbors(self, snapshot: ContinuitySnapshot) -> dict[str, set[str]]:
        result: dict[str, set[str]] = defaultdict(set)
        for arc in snapshot.narrative_arcs:
            for atom_id in arc.atom_ids:
                for peer in arc.atom_ids:
                    if peer != atom_id:
                        result[atom_id].add(peer)
        return dict(result)
