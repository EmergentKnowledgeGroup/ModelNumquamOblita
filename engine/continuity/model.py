from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class DynamicPattern:
    """Recurring interaction motif derived from multiple atoms."""

    pattern_id: str
    signature: str
    atom_ids: list[str]
    support_count: int
    confidence: float


@dataclass(slots=True)
class Constellation:
    """Linked cluster of memories sharing semantic/relational context."""

    constellation_id: str
    topic: str
    atom_ids: list[str]
    strength: float
    entities: list[str] = field(default_factory=list)
    start_at: datetime | None = None
    end_at: datetime | None = None


@dataclass(slots=True)
class NarrativeArc:
    """Ordered transformation sequence across time."""

    arc_id: str
    entity: str
    topic: str
    atom_ids: list[str]
    start_at: datetime
    end_at: datetime
    confidence: float
    valence_delta: float = 0.0


@dataclass(slots=True)
class SharedLanguageKey:
    """High-identity callback phrase that should influence retrieval."""

    key_id: str
    phrase: str
    atom_ids: list[str]
    support_count: int
    weight: float
    aliases: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    confidence: float = 0.8
    curated: bool = False


@dataclass(slots=True)
class RecognitionEvent:
    """Post-retrieval recognition signal captured for feedback weighting."""

    event_id: str
    atom_id: str
    recognized: bool
    score: float
    query_text: str
    timestamp: datetime


@dataclass(slots=True)
class ContinuitySnapshot:
    """Derived continuity layers available for retrieval expansion."""

    generated_at: datetime
    dynamic_patterns: list[DynamicPattern] = field(default_factory=list)
    constellations: list[Constellation] = field(default_factory=list)
    narrative_arcs: list[NarrativeArc] = field(default_factory=list)
    shared_language_keys: list[SharedLanguageKey] = field(default_factory=list)
