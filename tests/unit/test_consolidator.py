from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.config import DecayPolicy
from engine.continuity import Consolidator, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStatus, AtomStore


def _candidate(
    *,
    candidate_id: str,
    text: str,
    timestamp: datetime,
    support: int = 1,
    salience: float = 0.7,
    topic: str = "continuity",
) -> CandidateAtom:
    refs = [
        SourceRef(
            source_id=f"conv_{candidate_id}_{index}",
            message_id=f"m_{candidate_id}_{index}",
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
        entities=["user"],
        topics=[topic],
        confidence=0.82,
        salience=salience,
    )


def _snapshot_signature(store: ContinuityStore) -> tuple[tuple, tuple, tuple]:
    _, snapshot = store.snapshot_view()
    assert snapshot is not None
    constellations = tuple(
        sorted((item.topic, tuple(item.atom_ids), round(item.strength, 4)) for item in snapshot.constellations)
    )
    arcs = tuple(
        sorted(
            (
                item.entity,
                item.topic,
                tuple(item.atom_ids),
                round(item.valence_delta, 4),
                round(item.confidence, 4),
            )
            for item in snapshot.narrative_arcs
        )
    )
    patterns = tuple(sorted((item.signature, tuple(item.atom_ids), item.support_count) for item in snapshot.dynamic_patterns))
    return constellations, arcs, patterns


def test_consolidator_decays_archives_promotes_and_applies() -> None:
    now = datetime.now(timezone.utc)
    store = AtomStore()
    stable = store.add_candidate(
        _candidate(candidate_id="stable", text="We do continuity checks daily.", timestamp=now - timedelta(days=90), support=3)
    )
    volatile = store.add_candidate(
        _candidate(
            candidate_id="volatile",
            text="One-off low signal",
            timestamp=now - timedelta(days=400),
            support=1,
            salience=0.12,
        )
    )
    volatile.last_reinforced_at = now - timedelta(days=400)
    stable.last_reinforced_at = now - timedelta(days=90)

    consolidator = Consolidator(store, policy=DecayPolicy(half_life_days=180, minimum_salience=0.08))
    summary = consolidator.run(now=now, apply_promotions=True)

    assert summary.decayed_atoms >= 1
    assert any(candidate.atom_type is AtomType.ATOMIC_FACT for candidate in summary.promoted_candidates)
    assert summary.applied_promotions == len(summary.promoted_candidates)
    assert store.get_atom(volatile.atom_id).status in {AtomStatus.ACTIVE, AtomStatus.ARCHIVED}
    assert store.get_atom(stable.atom_id).salience <= 0.7


def test_consolidator_rebuild_snapshot_is_idempotent_for_same_input() -> None:
    base = datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc)
    store = AtomStore()
    for candidate in [
        _candidate(
            candidate_id="a1",
            text="I am afraid and uncertain before this check.",
            timestamp=base,
            support=2,
            topic="growth",
        ),
        _candidate(
            candidate_id="a2",
            text="I feel open and calm in this check.",
            timestamp=base + timedelta(minutes=12),
            support=2,
            topic="growth",
        ),
        _candidate(
            candidate_id="a3",
            text="I trust this process and remain grounded.",
            timestamp=base + timedelta(days=3),
            support=2,
            topic="growth",
        ),
    ]:
        store.add_candidate(candidate)

    continuity_store = ContinuityStore()
    consolidator = Consolidator(store, policy=DecayPolicy(half_life_days=365, minimum_salience=0.02))

    first = consolidator.run_with_snapshot(continuity_store, now=base + timedelta(days=4), apply_promotions=False)
    sig_one = _snapshot_signature(continuity_store)
    second = consolidator.run_with_snapshot(continuity_store, now=base + timedelta(days=4), apply_promotions=False)
    sig_two = _snapshot_signature(continuity_store)

    assert first.snapshot_revision is not None
    assert second.snapshot_revision is not None
    assert second.snapshot_revision > first.snapshot_revision
    assert sig_one == sig_two
