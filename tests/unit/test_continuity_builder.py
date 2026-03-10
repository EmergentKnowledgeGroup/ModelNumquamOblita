from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.continuity import ContinuityBuilder
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    entities: list[str],
    topics: list[str],
    timestamp: datetime,
    support: int = 1,
) -> CandidateAtom:
    refs = [
        SourceRef(
            source_id=f"{source_id}_{index}",
            message_id=f"{candidate_id}_{index}",
            timestamp=timestamp + timedelta(seconds=index),
            span_start=0,
            span_end=max(len(text), 1),
        )
        for index in range(max(support, 1))
    ]
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=refs,
        entities=entities,
        topics=topics,
        confidence=0.8,
        salience=0.7,
    )


def test_continuity_builder_forms_constellation_from_temporal_entity_topic_proximity() -> None:
    now = datetime(2026, 2, 8, 10, 0, tzinfo=timezone.utc)
    store = AtomStore()
    near_atoms = [
        _candidate(
            candidate_id="c1",
            text="I was afraid before the ritual started.",
            source_id="conv_prox",
            entities=["user"],
            topics=["ritual"],
            timestamp=now,
            support=2,
        ),
        _candidate(
            candidate_id="c2",
            text="I stayed present and open during the ritual.",
            source_id="conv_prox",
            entities=["user"],
            topics=["ritual"],
            timestamp=now + timedelta(minutes=10),
            support=2,
        ),
        _candidate(
            candidate_id="c3",
            text="I trust this ritual now.",
            source_id="conv_prox",
            entities=["user"],
            topics=["ritual"],
            timestamp=now + timedelta(minutes=24),
            support=2,
        ),
    ]
    far_atom = _candidate(
        candidate_id="c4",
        text="I tracked cost telemetry for runtime checks.",
        source_id="conv_far",
        entities=["user"],
        topics=["operations"],
        timestamp=now + timedelta(hours=6),
        support=1,
    )
    for candidate in near_atoms + [far_atom]:
        store.add_candidate(candidate)

    snapshot = ContinuityBuilder().build(store.list_atoms())

    near_ids = {atom.atom_id for atom in store.list_atoms() if "ritual" in atom.topics}
    constellation = next(
        (item for item in snapshot.constellations if set(item.atom_ids).issuperset(near_ids) and item.topic == "ritual"),
        None,
    )
    assert constellation is not None
    assert constellation.start_at is not None
    assert constellation.end_at is not None
    assert constellation.start_at <= constellation.end_at


def test_continuity_builder_creates_arc_when_valence_shifts_over_time() -> None:
    base = datetime.now(timezone.utc)
    store = AtomStore()
    for candidate in [
        _candidate(
            candidate_id="arc1",
            text="I am afraid and uncertain right now.",
            source_id="conv_arc",
            entities=["user"],
            topics=["growth"],
            timestamp=base,
            support=1,
        ),
        _candidate(
            candidate_id="arc2",
            text="I feel open, calm, and steady today.",
            source_id="conv_arc",
            entities=["user"],
            topics=["growth"],
            timestamp=base + timedelta(days=2),
            support=1,
        ),
        _candidate(
            candidate_id="arc3",
            text="I trust this path and feel grounded in it.",
            source_id="conv_arc",
            entities=["user"],
            topics=["growth"],
            timestamp=base + timedelta(days=5),
            support=1,
        ),
    ]:
        store.add_candidate(candidate)

    snapshot = ContinuityBuilder().build(store.list_atoms())
    arc = next((item for item in snapshot.narrative_arcs if item.entity == "user" and item.topic == "growth"), None)
    assert arc is not None
    assert arc.start_at < arc.end_at
    assert arc.valence_delta > 0
    assert arc.confidence >= 0.3
