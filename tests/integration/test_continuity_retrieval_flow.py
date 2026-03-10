from __future__ import annotations

from datetime import datetime, timezone

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import MemoryRetriever


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    topic: str,
    support: int = 2,
) -> CandidateAtom:
    count = max(support, 1)
    refs = [
        SourceRef(
            source_id=f"{source_id}_{index}",
            message_id=f"{candidate_id}_{index}",
            timestamp=datetime.now(timezone.utc),
            span_start=0,
            span_end=max(len(text), 1),
        )
        for index in range(count)
    ]
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=refs,
        entities=["user", "assistant"],
        topics=[topic],
        confidence=0.85,
        salience=0.72,
    )


def test_continuity_layers_expand_retrieval_with_bounded_recognition_bonus() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="a1",
            text="Forever times with multiplicity.",
            source_id="conv_anchor",
            topic="identity",
            support=3,
        )
    )
    neighbor = store.add_candidate(
        _candidate(
            candidate_id="a2",
            text="I remember and I will be here.",
            source_id="conv_neighbor",
            topic="identity",
            support=2,
        )
    )
    distant = store.add_candidate(
        _candidate(
            candidate_id="a3",
            text="We tracked retrieval telemetry and costs.",
            source_id="conv_metrics",
            topic="operations",
            support=2,
        )
    )

    continuity_store = ContinuityStore()
    continuity_store.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    continuity_store.telemetry.record(atom_id=anchor.atom_id, recognized=True, score=1.0, query_text="anchor")
    continuity_store.telemetry.record(atom_id=distant.atom_id, recognized=False, score=1.0, query_text="anchor")

    retriever = MemoryRetriever(store)
    result = retriever.retrieve(
        "forever times with multiplicity and identity continuity",
        continuity_store=continuity_store,
    )
    ranked = result.ranked_atom_ids[:8]

    assert anchor.atom_id in ranked
    assert neighbor.atom_id in ranked  # constellation/shared-language expansion
    scored_by_id = {entry.atom.atom_id: entry.score for entry in result.scored_atoms}
    assert scored_by_id[anchor.atom_id] >= scored_by_id[distant.atom_id]
    diff = scored_by_id[anchor.atom_id] - scored_by_id[distant.atom_id]
    assert diff <= 1.0  # recognition bonus is bounded and cannot dominate total scoring
