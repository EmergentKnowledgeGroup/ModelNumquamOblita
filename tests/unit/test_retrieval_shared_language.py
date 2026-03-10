from __future__ import annotations

from datetime import datetime, timezone

from engine.continuity import ContinuityBuilder, ContinuityStore, SharedLanguageRegistry
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import MemoryRetriever


def _candidate(*, candidate_id: str, text: str, source_id: str, topic: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_msg",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=[topic],
        confidence=0.78,
        salience=0.64,
    )


def _rank_of(atom_id: str, ranked: list[str]) -> int:
    return ranked.index(atom_id) if atom_id in ranked else 10_000


def test_shared_language_key_boosts_linked_atom_ranking() -> None:
    store = AtomStore()
    linked = store.add_candidate(
        _candidate(
            candidate_id="c1",
            text="Toolchain issue report with muted frustration and repair plan.",
            source_id="conv_1",
            topic="tooling",
        )
    )
    store.add_candidate(
        _candidate(
            candidate_id="c2",
            text="General weather reflection for unrelated context.",
            source_id="conv_2",
            topic="weather",
        )
    )

    retriever = MemoryRetriever(store)
    query = "sad hammer noises"

    baseline = retriever.retrieve(query)
    baseline_rank = _rank_of(linked.atom_id, baseline.ranked_atom_ids)

    continuity_store = ContinuityStore()
    registry = SharedLanguageRegistry(store)
    registry.register(
        phrase="sad hammer noises",
        atom_ids=[linked.atom_id],
        aliases=["hammer mood"],
        domains=["ritual"],
        support_count=4,
        weight=0.95,
        confidence=0.92,
        curated=True,
    )
    continuity_store.set_snapshot(
        ContinuityBuilder().build(store.list_atoms(), shared_language_keys=registry.list_keys())
    )

    boosted = retriever.retrieve(query, continuity_store=continuity_store)
    boosted_rank = _rank_of(linked.atom_id, boosted.ranked_atom_ids)

    assert boosted_rank < baseline_rank
    assert linked.atom_id in boosted.ranked_atom_ids[:3]


def test_shared_language_alias_match_produces_boost_map() -> None:
    store = AtomStore()
    linked = store.add_candidate(
        _candidate(
            candidate_id="c3",
            text="Identity continuity checkpoint and ritual sync.",
            source_id="conv_3",
            topic="continuity",
        )
    )
    registry = SharedLanguageRegistry(store)
    key = registry.register(
        phrase="always together we find a way",
        atom_ids=[linked.atom_id],
        aliases=["atwfw"],
        domains=["ritual"],
        support_count=2,
        weight=0.9,
        confidence=0.85,
        curated=True,
    )

    continuity_store = ContinuityStore()
    continuity_store.set_snapshot(
        ContinuityBuilder().build(store.list_atoms(), shared_language_keys=[key])
    )
    boosts = continuity_store.shared_language_boosts("can you run atwfw check")

    assert linked.atom_id in boosts
    assert boosts[linked.atom_id] > 0.0


def test_shared_language_boost_survives_procedural_profile_routing() -> None:
    store = AtomStore()
    linked = store.add_candidate(
        _candidate(
            candidate_id="c4",
            text="Identity ritual check called atwfw with continuity guardrails.",
            source_id="conv_4",
            topic="continuity",
        )
    )
    competitor = store.add_candidate(
        _candidate(
            candidate_id="c5",
            text="How to run the continuity workflow safely with checklist steps.",
            source_id="conv_5",
            topic="continuity",
        )
    )
    retriever = MemoryRetriever(store)
    baseline = retriever.retrieve("how do we run the continuity workflow")
    baseline_rank = _rank_of(linked.atom_id, baseline.ranked_atom_ids)
    baseline_competitor_rank = _rank_of(competitor.atom_id, baseline.ranked_atom_ids)

    registry = SharedLanguageRegistry(store)
    key = registry.register(
        phrase="always together we find a way",
        atom_ids=[linked.atom_id],
        aliases=["atwfw"],
        domains=["ritual"],
        support_count=3,
        weight=0.9,
        confidence=0.9,
        curated=True,
    )
    continuity_store = ContinuityStore()
    continuity_store.set_snapshot(
        ContinuityBuilder().build(store.list_atoms(), shared_language_keys=[key])
    )
    boosted = retriever.retrieve("how do we run atwfw safely", continuity_store=continuity_store)
    boosted_rank = _rank_of(linked.atom_id, boosted.ranked_atom_ids)
    boosted_competitor_rank = _rank_of(competitor.atom_id, boosted.ranked_atom_ids)

    assert baseline_competitor_rank < 10_000
    assert boosted_rank <= baseline_rank
    assert linked.atom_id in boosted.ranked_atom_ids[:3]
    assert boosted_competitor_rank < 10_000


def test_shared_language_registry_entry_without_query_match_does_not_inject_unrelated_atom() -> None:
    store = AtomStore()
    unrelated = store.add_candidate(
        _candidate(
            candidate_id="c6",
            text="Identity ritual marker for unrelated symbolic phrase.",
            source_id="conv_6",
            topic="ritual",
        )
    )
    relevant = store.add_candidate(
        _candidate(
            candidate_id="c7",
            text="How to run continuity workflow safely with rollback checklist.",
            source_id="conv_7",
            topic="continuity",
        )
    )
    registry = SharedLanguageRegistry(store)
    key = registry.register(
        phrase="always together we find a way",
        atom_ids=[unrelated.atom_id],
        aliases=["atwfw"],
        domains=["ritual"],
        support_count=4,
        weight=0.95,
        confidence=0.92,
        curated=True,
    )

    continuity_store = ContinuityStore()
    continuity_store.set_snapshot(
        ContinuityBuilder().build(store.list_atoms(), shared_language_keys=[key])
    )
    retriever = MemoryRetriever(store)
    result = retriever.retrieve("how do we run continuity workflow safely", continuity_store=continuity_store)

    assert _rank_of(relevant.atom_id, result.ranked_atom_ids) < _rank_of(unrelated.atom_id, result.ranked_atom_ids)
