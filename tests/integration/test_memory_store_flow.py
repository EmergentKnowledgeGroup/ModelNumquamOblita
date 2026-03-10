from __future__ import annotations

from datetime import datetime, timezone

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStatus, AtomStore, EventType


def test_memory_store_end_to_end_flow() -> None:
    store = AtomStore(salience_half_life_days=180)

    first = CandidateAtom(
        candidate_id="cand_1",
        atom_type=AtomType.EPISODE,
        canonical_text="We discussed continuity plans.",
        source_refs=[SourceRef(source_id="conv_1", timestamp=datetime.now(timezone.utc))],
        entities=["user", "assistant"],
        topics=["continuity"],
        confidence=0.82,
        salience=0.71,
    )
    second = CandidateAtom(
        candidate_id="cand_2",
        atom_type=AtomType.EPISODE,
        canonical_text="We discussed continuity plans.",
        source_refs=[SourceRef(source_id="conv_2", timestamp=datetime.now(timezone.utc))],
        entities=["user", "assistant"],
        topics=["continuity"],
        confidence=0.91,
        salience=0.75,
    )

    atom = store.add_candidate(first)
    reinforced = store.add_candidate(second)
    assert atom.atom_id == reinforced.atom_id
    assert reinforced.support_count == 2
    assert reinforced.status == AtomStatus.ACTIVE

    alternate = store.add_candidate(
        CandidateAtom(
            candidate_id="cand_3",
            atom_type=AtomType.EPISODE,
            canonical_text="We canceled continuity plans.",
            source_refs=[SourceRef(source_id="conv_3", timestamp=datetime.now(timezone.utc))],
            entities=["user", "assistant"],
            topics=["continuity"],
            confidence=0.77,
            salience=0.68,
        )
    )

    store.mark_conflict(reinforced.atom_id, alternate.atom_id, reason="timeline divergence")
    events = store.ledger.all_events()
    assert any(event.event_type == EventType.ADD for event in events)
    assert any(event.event_type == EventType.REINFORCE for event in events)
    assert any(event.event_type == EventType.CONFLICT for event in events)
