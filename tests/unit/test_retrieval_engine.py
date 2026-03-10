from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.continuity import ContinuityStore, ContinuitySnapshot
from engine.config import default_config
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import MemoryRetriever


class _CountingStore(AtomStore):
    def __init__(self) -> None:
        super().__init__()
        self.list_atoms_calls = 0

    def list_atoms(self) -> list:
        self.list_atoms_calls += 1
        return super().list_atoms()


class _BrokenScopeStore(_CountingStore):
    def cache_scope(self) -> str:
        raise RuntimeError("uncertain store scope")


class _BrokenContinuityStore(ContinuityStore):
    def cache_token(self) -> tuple[str, int]:
        raise RuntimeError("uncertain continuity cache token")


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    confidence: float = 0.82,
    salience: float = 0.68,
) -> CandidateAtom:
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
        topics=["continuity"],
        confidence=confidence,
        salience=salience,
    )


def _rank_of(atom_id: str, ranked: list[str]) -> int:
    return ranked.index(atom_id) if atom_id in ranked else 10_000


def test_retriever_builds_memory_pack_with_bounded_sections_and_recall() -> None:
    store = AtomStore()
    atoms = [
        store.add_candidate(_candidate(candidate_id="c1", text="I prefer mornings for deep work.", source_id="conv_1")),
        store.add_candidate(_candidate(candidate_id="c2", text="I prefer nights for deep work.", source_id="conv_2")),
        store.add_candidate(_candidate(candidate_id="c3", text="We discussed continuity plans yesterday.", source_id="conv_3")),
        store.add_candidate(_candidate(candidate_id="c4", text="You love tea and quiet routines.", source_id="conv_4")),
        store.add_candidate(_candidate(candidate_id="c5", text="We ran retrieval verification checks.", source_id="conv_5")),
    ]
    store.mark_conflict(atoms[0].atom_id, atoms[1].atom_id, reason="preference_conflict")

    retriever = MemoryRetriever(store)
    result = retriever.retrieve("morning continuity work plan")

    assert atoms[0].atom_id in result.ranked_atom_ids[:8]
    assert len(result.ranked_atom_ids) <= retriever.config.retrieval.rerank_limit
    assert len(result.memory_pack.core) <= 6
    assert len(result.memory_pack.context) <= 8
    assert len(result.memory_pack.conflict) <= 6
    assert result.memory_pack.pack_confidence >= 0.0
    assert all(item.source_refs for item in result.memory_pack.core + result.memory_pack.context + result.memory_pack.conflict)
    conflict_ids = {item.atom_id for item in result.memory_pack.conflict}
    assert atoms[0].atom_id in conflict_ids or atoms[1].atom_id in conflict_ids


def test_retriever_memory_pack_respects_typed_pack_limits() -> None:
    store = AtomStore()
    atoms = [
        store.add_candidate(_candidate(candidate_id="pc1", text="I prefer mornings for deep work.", source_id="pc_1")),
        store.add_candidate(_candidate(candidate_id="pc2", text="I prefer nights for deep work.", source_id="pc_2")),
        store.add_candidate(_candidate(candidate_id="pc3", text="We discussed continuity plans yesterday.", source_id="pc_3")),
        store.add_candidate(_candidate(candidate_id="pc4", text="You love tea and quiet routines.", source_id="pc_4")),
        store.add_candidate(_candidate(candidate_id="pc5", text="We ran retrieval verification checks.", source_id="pc_5")),
    ]
    store.mark_conflict(atoms[0].atom_id, atoms[1].atom_id, reason="preference_conflict")
    cfg = default_config()
    cfg.retrieval.pack.core_limit = 1
    cfg.retrieval.pack.context_limit = 1
    cfg.retrieval.pack.conflict_limit = 1
    cfg.retrieval.pack.continuity_limit = 1
    retriever = MemoryRetriever(store, config=cfg)

    result = retriever.retrieve("morning continuity work plan")

    assert len(result.memory_pack.core) <= 1
    assert len(result.memory_pack.context) <= 1
    assert len(result.memory_pack.conflict) <= 1
    assert len(result.memory_pack.continuity) <= 1


def test_retriever_cache_policy_token_changes_when_typed_knobs_change() -> None:
    default_token = MemoryRetriever(AtomStore())._cache_policy_token()
    cfg = default_config()
    cfg.retrieval.pack.core_limit = 4
    cfg.retrieval.cache.fail_closed_on_uncertain_continuity_scope = False
    changed_token = MemoryRetriever(AtomStore(), config=cfg)._cache_policy_token()

    assert changed_token != default_token


def test_retriever_reuses_cache_when_store_token_is_stable() -> None:
    store = _CountingStore()
    store.add_candidate(_candidate(candidate_id="c1", text="Project alpha continuity plan.", source_id="conv_a"))
    store.add_candidate(_candidate(candidate_id="c2", text="Greg shared the timeline update.", source_id="conv_b"))
    retriever = MemoryRetriever(store)

    retriever.retrieve("project timeline")
    assert store.list_atoms_calls == 1

    retriever.retrieve("greg timeline")
    assert store.list_atoms_calls == 1


def test_retriever_invalidates_cache_when_store_token_changes() -> None:
    store = _CountingStore()
    store.add_candidate(_candidate(candidate_id="c1", text="Project alpha continuity plan.", source_id="conv_a"))
    retriever = MemoryRetriever(store)

    retriever.retrieve("project timeline")
    assert store.list_atoms_calls == 1

    # Reinforcement mutates atom metadata without changing atom count.
    store.add_candidate(_candidate(candidate_id="c2", text="Project alpha continuity plan.", source_id="conv_b"))
    retriever.retrieve("project timeline")
    assert store.list_atoms_calls == 2


def test_retriever_bypasses_cache_when_store_scope_token_is_uncertain() -> None:
    store = _BrokenScopeStore()
    store.add_candidate(_candidate(candidate_id="c1", text="Project alpha continuity plan.", source_id="conv_a"))
    retriever = MemoryRetriever(store)

    retriever.retrieve("project timeline")
    assert store.list_atoms_calls == 1

    retriever.retrieve("project timeline")
    assert store.list_atoms_calls == 2


def test_retriever_invalidates_cache_when_continuity_revision_changes() -> None:
    store = _CountingStore()
    store.add_candidate(_candidate(candidate_id="c1", text="Project alpha continuity plan.", source_id="conv_a"))
    continuity = ContinuityStore(snapshot=ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    retriever = MemoryRetriever(store)

    retriever.retrieve("project timeline", continuity_store=continuity)
    assert store.list_atoms_calls == 1

    retriever.retrieve("project timeline", continuity_store=continuity)
    assert store.list_atoms_calls == 1

    continuity.set_snapshot(ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    retriever.retrieve("project timeline", continuity_store=continuity)
    assert store.list_atoms_calls == 2


def test_retriever_bypasses_cache_when_continuity_token_is_uncertain() -> None:
    store = _CountingStore()
    store.add_candidate(_candidate(candidate_id="c1", text="Project alpha continuity plan.", source_id="conv_a"))
    retriever = MemoryRetriever(store)
    continuity = _BrokenContinuityStore(snapshot=ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))

    retriever.retrieve("project timeline", continuity_store=continuity)
    assert store.list_atoms_calls == 1

    retriever.retrieve("project timeline", continuity_store=continuity)
    assert store.list_atoms_calls == 2


def test_retriever_classifies_profiles_deterministically() -> None:
    retriever = MemoryRetriever(AtomStore())

    assert retriever._classify_profile("remember when we planned this", {"remember", "when", "planned"}) == "episode_heavy"
    assert retriever._classify_profile("what flavor do you prefer", {"what", "flavor", "prefer"}) == "preference_relational"
    assert retriever._classify_profile("how do we run this workflow", {"how", "run", "workflow"}) == "procedural"
    assert retriever._classify_profile("which fact did we record", {"which", "fact", "record"}) == "factual"
    assert retriever._classify_profile("ambient chat with no cue words", {"ambient", "chat", "cue", "words"}) == "mixed"


def test_retriever_detects_explicit_time_intent() -> None:
    retriever = MemoryRetriever(AtomStore())

    assert retriever._has_time_intent("when did we decide this", {"when", "did", "decide", "this"})
    assert retriever._has_time_intent("what happened yesterday", {"what", "happened", "yesterday"})
    assert not retriever._has_time_intent("how do we run this workflow", {"how", "run", "workflow"})


def test_retriever_profile_limits_keep_safety_floors() -> None:
    retriever = MemoryRetriever(AtomStore())

    lexical, semantic, temporal, graph = retriever._profile_channel_limits("procedural")

    assert 4 <= lexical <= retriever.config.retrieval.top_k_lexical
    assert 4 <= semantic <= retriever.config.retrieval.top_k_vector
    assert 2 <= temporal <= retriever.config.retrieval.top_k_temporal
    assert 2 <= graph <= retriever.config.retrieval.top_k_graph
    assert temporal < retriever.config.retrieval.top_k_temporal
    assert graph < retriever.config.retrieval.top_k_graph


def test_retriever_profile_limits_respect_typed_router_policy_override() -> None:
    cfg = default_config()
    cfg.retrieval.top_k_vector = 10
    cfg.retrieval.router.semantic_floor_min = 1
    cfg.retrieval.router.procedural.semantic_scale = 0.5
    retriever = MemoryRetriever(AtomStore(), config=cfg)

    _lexical, semantic, _temporal, _graph = retriever._profile_channel_limits("procedural")

    assert semantic == 5


def test_retriever_extracts_only_long_quoted_phrases_for_alignment() -> None:
    retriever = MemoryRetriever(AtomStore())

    assert retriever._quoted_phrase_tokens('quick note: "raccoon coded"') == []
    assert retriever._quoted_phrase_tokens('remember this: "she perks soft ears soft grin"') == [
        ["she", "perks", "soft", "ears", "soft", "grin"]
    ]


def test_retriever_misclassified_queries_still_return_fallback_candidates() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="c3",
            text="Deep continuity anchor around project constellation decisions.",
            source_id="conv_c",
        )
    )
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("how do we debug this workflow safely")

    assert result.ranked_atom_ids
    assert anchor.atom_id in result.ranked_atom_ids
    assert len(result.ranked_atom_ids) <= retriever.config.retrieval.rerank_limit


def test_retriever_bm25_rare_keyword_rescues_specific_atom() -> None:
    store = AtomStore()
    common = store.add_candidate(
        _candidate(candidate_id="c4", text="Project planning update and routine timeline notes.", source_id="conv_d")
    )
    rare = store.add_candidate(
        _candidate(candidate_id="c5", text="xylophonium calibration ritual and recall anchor.", source_id="conv_e")
    )
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("project xylophonium")

    assert rare.atom_id in result.ranked_atom_ids[:3]
    assert _rank_of(rare.atom_id, result.ranked_atom_ids) < _rank_of(common.atom_id, result.ranked_atom_ids)


def test_retriever_bm25_ignores_stopword_noise() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(candidate_id="c6", text="Continuity checkpoint around project rituals.", source_id="conv_f")
    )
    retriever = MemoryRetriever(store)
    cache = retriever._get_cache()

    bm25 = retriever._bm25_scores(cache, {"the", "and", "of", "in"})
    result = retriever.retrieve("the and of in")

    assert bm25 == {}
    assert anchor.atom_id in result.ranked_atom_ids
    assert len(result.ranked_atom_ids) <= retriever.config.retrieval.rerank_limit


def test_retriever_bm25_respects_typed_policy_override() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            candidate_id="c6bm25",
            text="xylophonium calibration ritual and recall anchor.",
            source_id="conv_bm25",
        )
    )
    cfg = default_config()
    cfg.retrieval.bm25.relevance_floor_min = 999.0
    retriever = MemoryRetriever(store, config=cfg)
    cache = retriever._get_cache()

    bm25 = retriever._bm25_scores(cache, {"xylophonium"})

    assert bm25 == {}


def test_retriever_top_ids_uses_deterministic_tie_break() -> None:
    retriever = MemoryRetriever(AtomStore())
    top = retriever._top_ids({"b": 1.0, "a": 1.0, "c": 0.4}, 2)
    assert top == ["a", "b"]


def test_retriever_rrf_rewards_multi_channel_agreement() -> None:
    retriever = MemoryRetriever(AtomStore())
    scores = retriever._rrf_fuse(
        {
            "lexical": ["a1", "a2"],
            "semantic": ["a2"],
            "bm25": ["a2"],
            "temporal": [],
            "graph": [],
            "continuity": [],
        }
    )
    assert scores["a2"] > scores["a1"]


def test_retriever_rrf_respects_typed_weights() -> None:
    cfg = default_config()
    cfg.retrieval.rrf.lexical_weight = 0.1
    cfg.retrieval.rrf.semantic_weight = 2.0
    retriever = MemoryRetriever(AtomStore(), config=cfg)

    scores = retriever._rrf_fuse({"lexical": ["a1"], "semantic": ["a2"]})

    assert scores["a2"] > scores["a1"]


def test_retriever_temporal_channel_does_not_inject_unrelated_recent_atom() -> None:
    store = AtomStore()
    relevant = store.add_candidate(
        _candidate(candidate_id="c7", text="Nebula signal protocol recall from planning session.", source_id="conv_g")
    )
    unrelated = store.add_candidate(
        _candidate(candidate_id="c8", text="Fresh weather log and local temperature notes.", source_id="conv_h")
    )
    relevant.updated_at = datetime.now(timezone.utc) - timedelta(days=400)
    unrelated.updated_at = datetime.now(timezone.utc)
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("nebula signal")

    assert _rank_of(relevant.atom_id, result.ranked_atom_ids) < _rank_of(unrelated.atom_id, result.ranked_atom_ids)


def test_retriever_time_intent_override_can_promote_older_time_matching_evidence() -> None:
    store = AtomStore()
    old_time_match = store.add_candidate(
        _candidate(
            candidate_id="c11",
            text="Nebula rollback happened last winter during the outage drill.",
            source_id="conv_k",
        )
    )
    newer_non_time_match = store.add_candidate(
        _candidate(
            candidate_id="c12",
            text="Nebula rollback checklist for the current sprint handoff.",
            source_id="conv_l",
        )
    )
    old_time_match.updated_at = datetime.now(timezone.utc) - timedelta(days=500)
    newer_non_time_match.updated_at = datetime.now(timezone.utc)
    retriever = MemoryRetriever(store)

    neutral = retriever.retrieve("nebula rollback checklist")
    with_time_intent = retriever.retrieve("when did nebula rollback happen last winter")

    assert _rank_of(old_time_match.atom_id, neutral.ranked_atom_ids) > _rank_of(
        newer_non_time_match.atom_id, neutral.ranked_atom_ids
    )
    assert _rank_of(old_time_match.atom_id, with_time_intent.ranked_atom_ids) < _rank_of(
        newer_non_time_match.atom_id, with_time_intent.ranked_atom_ids
    )


def test_retriever_quote_alignment_rescues_specific_anchor_from_dense_phrase_cluster() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="q1",
            text="She perks soft ears soft grin a little raccoon coded shuffle toward you before helping Sara.",
            source_id="conv_quote_anchor",
            confidence=0.58,
            salience=0.44,
        )
    )
    distractor = store.add_candidate(
        _candidate(
            candidate_id="q2",
            text="Raccoon coded continuity banter with no Sara context and no soft ears or grin event anchor.",
            source_id="conv_quote_noise",
            confidence=0.93,
            salience=0.92,
        )
    )
    for idx in range(4):
        store.add_candidate(
            _candidate(
                candidate_id=f"q2_reinforce_{idx}",
                text="Raccoon coded continuity banter with no Sara context and no soft ears or grin event anchor.",
                source_id=f"conv_quote_noise_reinforce_{idx}",
                confidence=0.93,
                salience=0.92,
            )
        )
    for idx in range(18):
        store.add_candidate(
            _candidate(
                candidate_id=f"q_noise_{idx}",
                text=f"Raccoon coded memory chatter variant {idx} with continuity jokes and banter.",
                source_id=f"conv_quote_dense_{idx}",
                confidence=0.86,
                salience=0.82,
            )
        )
    anchor.updated_at = datetime.now(timezone.utc) - timedelta(days=520)
    retriever = MemoryRetriever(store)

    without_quote = retriever.retrieve("what do you remember about Sara raccoon coded shuffle")
    with_quote = retriever.retrieve(
        'what do you remember about Sara around this event: "She perks soft ears soft grin a little raccoon coded shuffle toward"'
    )

    assert _rank_of(anchor.atom_id, without_quote.ranked_atom_ids) > _rank_of(distractor.atom_id, without_quote.ranked_atom_ids)
    assert _rank_of(anchor.atom_id, with_quote.ranked_atom_ids) < _rank_of(distractor.atom_id, with_quote.ranked_atom_ids)
    assert _rank_of(anchor.atom_id, with_quote.ranked_atom_ids) < _rank_of(anchor.atom_id, without_quote.ranked_atom_ids)
    assert anchor.atom_id in with_quote.ranked_atom_ids[:5]
    assert with_quote.memory_pack.pack_confidence >= 0.55


def test_retriever_sequence_alignment_rescues_anchor_when_quotes_are_stripped() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="s1",
            text="She perks soft ears soft grin a little raccoon coded shuffle toward you before helping Sara.",
            source_id="conv_sequence_anchor",
            confidence=0.58,
            salience=0.44,
        )
    )
    distractor = store.add_candidate(
        _candidate(
            candidate_id="s2",
            text="Sara asks for help while raccoon coded banter and shuffle jokes crowd the continuity chat.",
            source_id="conv_sequence_noise",
            confidence=0.94,
            salience=0.93,
        )
    )
    for idx in range(4):
        store.add_candidate(
            _candidate(
                candidate_id=f"s2_reinforce_{idx}",
                text="Sara asks for help while raccoon coded banter and shuffle jokes crowd the continuity chat.",
                source_id=f"conv_sequence_noise_reinforce_{idx}",
                confidence=0.94,
                salience=0.93,
            )
        )
    anchor.updated_at = datetime.now(timezone.utc) - timedelta(days=520)
    retriever = MemoryRetriever(store)

    ambiguous = retriever.retrieve("Sara raccoon coded shuffle continuity")
    sequence_query = retriever.retrieve(
        "Sara she perks soft ears soft grin a little raccoon coded shuffle toward you before helping"
    )

    assert _rank_of(anchor.atom_id, ambiguous.ranked_atom_ids) > _rank_of(distractor.atom_id, ambiguous.ranked_atom_ids)
    assert _rank_of(anchor.atom_id, sequence_query.ranked_atom_ids) < _rank_of(
        distractor.atom_id, sequence_query.ranked_atom_ids
    )
    assert _rank_of(anchor.atom_id, sequence_query.ranked_atom_ids) < _rank_of(anchor.atom_id, ambiguous.ranked_atom_ids)


def test_retriever_fails_closed_when_conflict_neighbor_is_missing() -> None:
    store = AtomStore()
    left = store.add_candidate(
        _candidate(candidate_id="c9", text="I prefer mornings for focused work.", source_id="conv_i")
    )
    right = store.add_candidate(
        _candidate(candidate_id="c10", text="I prefer nights for focused work.", source_id="conv_j")
    )
    filler = store.add_candidate(
        _candidate(candidate_id="c13", text="Continuity checklist notes for sprint planning.", source_id="conv_k")
    )
    store.mark_conflict(left.atom_id, right.atom_id, reason="preference_conflict")
    store.tombstone_atom(right.atom_id, reason="regression_test_missing_neighbor")
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("prefer mornings for focused work continuity checklist")

    assert result.memory_pack.core == []
    assert result.memory_pack.context == []
    assert result.memory_pack.conflict
    assert filler.atom_id in result.dropped_reasons
    assert right.atom_id in result.dropped_reasons
    assert result.dropped_reasons[filler.atom_id] == "CONFLICT_REQUIRED_BUT_DROPPED"
    assert result.dropped_reasons[right.atom_id] == "CONFLICT_REQUIRED_BUT_DROPPED"


def test_retriever_conflict_neighbor_dedupe_does_not_trigger_false_fail_closed() -> None:
    store = AtomStore()
    left = store.add_candidate(
        _candidate(candidate_id="c14", text="Alpha continuity preference remains mornings.", source_id="conv_m")
    )
    right = store.add_candidate(
        _candidate(candidate_id="c15", text="Beta continuity preference remains mornings.", source_id="conv_n")
    )
    shared = store.add_candidate(
        _candidate(candidate_id="c16", text="Conflicting note claims preference changed to nights.", source_id="conv_o")
    )
    store.add_candidate(
        _candidate(candidate_id="c17", text="Neutral continuity checklist for sprint planning.", source_id="conv_p")
    )
    store.mark_conflict(left.atom_id, shared.atom_id, reason="preference_conflict")
    store.mark_conflict(right.atom_id, shared.atom_id, reason="preference_conflict")

    retriever = MemoryRetriever(store)
    result = retriever.retrieve("alpha beta preference continuity mornings")

    conflict_ids = [item.atom_id for item in result.memory_pack.conflict]
    assert conflict_ids.count(shared.atom_id) == 1
    assert result.memory_pack.conflict
    assert "CONFLICT_REQUIRED_BUT_DROPPED" not in result.dropped_reasons.values()


def test_retriever_emits_stable_dropped_reason_codes() -> None:
    store = AtomStore()
    for idx in range(20):
        store.add_candidate(
            _candidate(
                candidate_id=f"d{idx}",
                text=f"continuity planning note {idx} with routine recall anchors",
                source_id=f"conv_{idx}",
            )
        )
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("continuity planning note")

    assert result.dropped_reasons
    allowed = {
        "LOW_RELEVANCE",
        "BUDGET",
        "BUDGET_CONFLICT",
        "CONFLICT_REQUIRED_BUT_DROPPED",
        "DUPLICATE",
    }
    assert set(result.dropped_reasons.values()).issubset(allowed)


def test_retriever_dedupes_identical_canonical_text_in_memory_pack() -> None:
    store = AtomStore()
    first = store.add_candidate(
        _candidate(candidate_id="dup_a", text="Continuity anchor for project helios launch prep.", source_id="conv_dup_a")
    )
    second = store.add_candidate(
        _candidate(
            candidate_id="dup_b",
            text="Continuity anchor for project helios launch prep!!!",
            source_id="conv_dup_b",
        )
    )
    unique = store.add_candidate(
        _candidate(candidate_id="dup_c", text="Distinct continuity note about fallback rollout windows.", source_id="conv_dup_c")
    )
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("helios continuity anchor launch prep")

    pack_ids = [item.atom_id for item in (result.memory_pack.core + result.memory_pack.context + result.memory_pack.continuity)]
    duplicate_ids = {first.atom_id, second.atom_id}
    assert len(duplicate_ids.intersection(pack_ids)) == 1
    dropped_duplicate_ids = [atom_id for atom_id in duplicate_ids if result.dropped_reasons.get(atom_id) == "DUPLICATE"]
    assert len(dropped_duplicate_ids) == 1
    assert unique.atom_id in result.ranked_atom_ids


def test_retriever_candidate_pool_floor_is_profile_aware() -> None:
    retriever = MemoryRetriever(AtomStore())

    episode_floor = retriever._candidate_pool_floor("episode_heavy")
    mixed_floor = retriever._candidate_pool_floor("mixed")
    procedural_floor = retriever._candidate_pool_floor("procedural")
    factual_floor = retriever._candidate_pool_floor("factual")
    preference_floor = retriever._candidate_pool_floor("preference_relational")

    assert episode_floor == mixed_floor
    assert episode_floor >= preference_floor >= procedural_floor
    assert episode_floor >= factual_floor >= procedural_floor
    assert procedural_floor <= 192


def test_retriever_candidate_cap_is_profile_aware() -> None:
    retriever = MemoryRetriever(AtomStore())

    rerank_limit = retriever.config.retrieval.rerank_limit
    episode_cap = retriever._profile_candidate_cap("episode_heavy")
    mixed_cap = retriever._profile_candidate_cap("mixed")
    preference_cap = retriever._profile_candidate_cap("preference_relational")
    procedural_cap = retriever._profile_candidate_cap("procedural")
    factual_cap = retriever._profile_candidate_cap("factual")

    assert episode_cap == rerank_limit
    assert mixed_cap == rerank_limit
    assert rerank_limit >= preference_cap >= procedural_cap
    assert rerank_limit >= factual_cap >= procedural_cap
    assert procedural_cap >= 16


def test_retriever_guarded_candidate_ids_preserves_required_conflict_neighbors_beyond_cap() -> None:
    retriever = MemoryRetriever(AtomStore())
    cap = retriever._profile_candidate_cap("procedural")
    candidate_ids = [f"a{idx}" for idx in range(cap + 20)]
    anchor = candidate_ids[1]
    required_neighbor = candidate_ids[cap + 5]

    guarded = retriever._guarded_candidate_ids(
        candidate_ids,
        profile="procedural",
        conflict_map={anchor: {required_neighbor}},
    )

    assert len(guarded) == cap + 1
    assert required_neighbor in guarded
    assert guarded.index(required_neighbor) >= cap


def test_retriever_guarded_candidate_ids_keeps_profile_cap_without_required_neighbors() -> None:
    retriever = MemoryRetriever(AtomStore())
    cap = retriever._profile_candidate_cap("procedural")
    candidate_ids = [f"b{idx}" for idx in range(cap + 20)]

    guarded = retriever._guarded_candidate_ids(
        candidate_ids,
        profile="procedural",
        conflict_map={},
    )

    assert guarded == candidate_ids[:cap]


def test_retriever_score_candidates_uses_profile_floor_instead_of_legacy_256() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="pool_anchor",
            text="nebulauniquetoken continuity anchor for profile floor test",
            source_id="conv_pool_anchor",
        )
    )
    for idx in range(399):
        store.add_candidate(
            _candidate(
                candidate_id=f"pool_noise_{idx}",
                text=f"continuity pool noise sample {idx}",
                source_id=f"conv_pool_noise_{idx}",
            )
        )
    retriever = MemoryRetriever(store)
    cache = retriever._get_cache()

    selected = retriever._score_candidates(cache, {"nebulauniquetoken"}, profile="procedural")
    selected_ids = {item.atom.atom_id for item in selected}
    expected_floor = retriever._candidate_pool_floor("procedural")

    assert anchor.atom_id in selected_ids
    assert len(selected) == expected_floor
    assert len(selected) < 256


def test_retriever_profile_candidate_cap_limits_ranked_ids_for_procedural_queries() -> None:
    store = AtomStore()
    for idx in range(320):
        store.add_candidate(
            _candidate(
                candidate_id=f"cap_noise_{idx}",
                text=f"workflow process plan continuity entry {idx}",
                source_id=f"conv_cap_{idx}",
            )
        )
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("how do we run this workflow process plan")

    assert len(result.ranked_atom_ids) <= retriever._profile_candidate_cap("procedural")
    assert len(result.ranked_atom_ids) < retriever.config.retrieval.rerank_limit
