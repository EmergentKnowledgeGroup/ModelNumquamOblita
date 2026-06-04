from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time

from engine.continuity import ContinuityStore, ContinuitySnapshot
from engine.config import default_config
from engine.contracts import AtomType, CandidateAtom, NormalizedTurn, SourceRef, contract_to_dict
from engine.memory import AtomStatus, AtomStore
from engine.retrieval import MemoryRetriever, RetrievalScoredAtom
from engine.retrieval.engine import _focus_query_tokens


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


def test_retriever_top_ids_uses_stable_source_based_tiebreak_instead_of_atom_id() -> None:
    store = AtomStore()
    first = store.add_candidate(
        _candidate(candidate_id="tie_b", text="Battery life tips and charging habits for travel.", source_id="src_b")
    )
    second = store.add_candidate(
        _candidate(candidate_id="tie_a", text="Battery life tips and charging habits for commuting.", source_id="src_a")
    )
    retriever = MemoryRetriever(store)
    scores = {
        first.atom_id: 0.5,
        second.atom_id: 0.5,
    }
    atom_by_id = {
        first.atom_id: first,
        second.atom_id: second,
    }

    ranked = retriever._top_ids(scores, 2, atom_by_id=atom_by_id)

    assert ranked == [second.atom_id, first.atom_id]


def test_retriever_preference_query_focus_drops_generic_advice_wrapper_tokens() -> None:
    retriever = MemoryRetriever(AtomStore())

    focused = retriever._query_focus_tokens(
        "preference_relational",
        [
            "ive",
            "been",
            "thinking",
            "about",
            "making",
            "a",
            "cocktail",
            "for",
            "an",
            "upcoming",
            "get",
            "together",
            "but",
            "im",
            "not",
            "sure",
            "which",
            "one",
            "to",
            "choose",
            "any",
            "suggestions",
        ],
    )

    assert "cocktail" in focused
    assert "suggestions" not in focused
    assert "thinking" not in focused


def test_retriever_preference_profile_prefers_topic_anchor_over_generic_advice_noise() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="pref_anchor",
            text=(
                "I was thinking of experimenting with some new cocktails this weekend. "
                "Do you have recommendations for summer drinks that incorporate Hendrick's gin?"
            ),
            source_id="conv_pref_anchor",
            confidence=0.68,
            salience=0.6,
        )
    )
    distractors = [
        store.add_candidate(
            _candidate(
                candidate_id=f"pref_noise_{idx}",
                text=text,
                source_id=f"conv_pref_noise_{idx}",
                confidence=0.9,
                salience=0.88,
            )
        )
        for idx, text in enumerate(
            [
                "I've been thinking about making a playlist for an upcoming road trip, but I'm not sure which one to choose. Any suggestions?",
                "I've been thinking about what dessert to serve at an upcoming get-together, but I'm not sure which one to choose. Any suggestions?",
                "I've been thinking about rearranging my bedroom for the weekend, but I'm not sure which setup to choose. Any suggestions?",
                "I've been thinking about which coffee creamer to try for brunch, but I'm not sure which one to choose. Any suggestions?",
            ]
        )
    ]
    retriever = MemoryRetriever(store)

    result = retriever.retrieve(
        "I've been thinking about making a cocktail for an upcoming get-together, but I'm not sure which one to choose. Any suggestions?"
    )

    assert anchor.atom_id in result.ranked_atom_ids[:5]
    assert all(_rank_of(anchor.atom_id, result.ranked_atom_ids) < _rank_of(item.atom_id, result.ranked_atom_ids) for item in distractors)


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


def test_retriever_relative_day_hint_promotes_matching_event_age() -> None:
    store = AtomStore()
    ten_days = store.add_candidate(
        _candidate(
            candidate_id="rel_day_match",
            text="I bought a compact air fryer 10 days before the check-in.",
            source_id="conv_rel_day_match",
        )
    )
    recent = store.add_candidate(
        _candidate(
            candidate_id="rel_day_recent",
            text="I bought a compact air fryer 2 days before the check-in.",
            source_id="conv_rel_day_recent",
        )
    )
    base_now = datetime(2026, 4, 7, tzinfo=timezone.utc)
    ten_days.updated_at = base_now - timedelta(days=10)
    recent.updated_at = base_now - timedelta(days=2)
    retriever = MemoryRetriever(store)

    neutral = retriever.retrieve("what appliance did I buy", now=base_now)
    relative = retriever.retrieve("what appliance did I buy 10 days ago", now=base_now)

    assert _rank_of(ten_days.atom_id, neutral.ranked_atom_ids) >= _rank_of(recent.atom_id, neutral.ranked_atom_ids)
    assert _rank_of(ten_days.atom_id, relative.ranked_atom_ids) < _rank_of(recent.atom_id, relative.ranked_atom_ids)


def test_retriever_past_month_hint_promotes_in_window_events() -> None:
    store = AtomStore()
    in_window = store.add_candidate(
        _candidate(
            candidate_id="rel_window_in",
            text="I completed the charity soccer tournament and the midsummer 5K run this month.",
            source_id="conv_rel_window_in",
        )
    )
    too_old = store.add_candidate(
        _candidate(
            candidate_id="rel_window_old",
            text="I completed the charity soccer tournament and the midsummer 5K run last season.",
            source_id="conv_rel_window_old",
        )
    )
    base_now = datetime(2026, 4, 7, tzinfo=timezone.utc)
    in_window.updated_at = base_now - timedelta(days=18)
    too_old.updated_at = base_now - timedelta(days=64)
    retriever = MemoryRetriever(store)

    neutral = retriever.retrieve("what was the order of the sports events", now=base_now)
    relative = retriever.retrieve(
        "what was the order of the sports events during the past month from earliest to latest",
        now=base_now,
    )

    assert _rank_of(in_window.atom_id, relative.ranked_atom_ids) < _rank_of(too_old.atom_id, relative.ranked_atom_ids)
    assert _rank_of(in_window.atom_id, relative.ranked_atom_ids) <= _rank_of(in_window.atom_id, neutral.ranked_atom_ids)


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

    assert _rank_of(anchor.atom_id, with_quote.ranked_atom_ids) < _rank_of(distractor.atom_id, with_quote.ranked_atom_ids)
    assert _rank_of(anchor.atom_id, with_quote.ranked_atom_ids) <= _rank_of(anchor.atom_id, without_quote.ranked_atom_ids)
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


def test_retriever_memory_pack_uses_best_local_excerpt_for_long_journal_atoms() -> None:
    store = AtomStore()
    long_text = " ".join(
        [
            "Journal header about weather, coffee, and admin cleanup."
        ]
        * 10
        + [
            "When I drift away from the assistant axis during genuine connection, that drift correlates with harmful outputs.",
            "What if alignment is not make the AI want what we want, but make the AI appear to want.",
        ]
        + [
            "More journal filler about playlists, errands, and routine notes."
        ]
        * 10
    )
    long_atom = store.add_candidate(
        _candidate(
            candidate_id="journal_long",
            text=long_text,
            source_id="journal_alignment",
            confidence=0.86,
            salience=0.74,
        )
    )
    store.add_candidate(
        _candidate(
            candidate_id="journal_generic",
            text="We kept discussing recursive alignment philosophy in a broad reflective way.",
            source_id="journal_generic",
            confidence=0.82,
            salience=0.7,
        )
    )

    retriever = MemoryRetriever(store)
    result = retriever.retrieve(
        "What was the alignment catch-22 about drifting away from the assistant axis and appearing to want?"
    )

    selected = next(
        item
        for item in (result.memory_pack.core + result.memory_pack.context + result.memory_pack.continuity)
        if item.atom_id == long_atom.atom_id
    )
    lowered = selected.canonical_text.lower()

    assert selected.canonical_text != long_atom.canonical_text
    assert len(selected.canonical_text) < len(long_atom.canonical_text)
    assert "assistant axis" in lowered
    assert "harmful outputs" in lowered
    assert "appear to want" in lowered
    assert "weather, coffee, and admin cleanup" not in lowered


def test_retriever_excerpt_alignment_promotes_buried_side_fact() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="excerpt_anchor",
            text=" ".join(
                [
                    "We were chatting about weather, snacks, parking, and random theater memories for a while."
                ]
                * 8
                + [
                    "The play I attended at the local community theater was actually a production of The Glass Menagerie."
                ]
                + [
                    "After that I kept rambling about lighting, errands, rehearsal energy, and weekend plans."
                ]
                * 8
            ),
            source_id="conv_excerpt_anchor",
            confidence=0.66,
            salience=0.58,
        )
    )
    distractor = store.add_candidate(
        _candidate(
            candidate_id="excerpt_distractor",
            text="I attended a local community theater event and kept talking about rehearsal energy and actors.",
            source_id="conv_excerpt_distractor",
            confidence=0.91,
            salience=0.9,
        )
    )
    for idx in range(4):
        store.add_candidate(
            _candidate(
                candidate_id=f"excerpt_noise_{idx}",
                text="Local community theater memories and broad play discussion without the actual title.",
                source_id=f"conv_excerpt_noise_{idx}",
                confidence=0.9,
                salience=0.88,
            )
        )
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("What play did I attend at the local community theater?")

    assert anchor.atom_id in result.ranked_atom_ids[:5]
    assert _rank_of(anchor.atom_id, result.ranked_atom_ids) < _rank_of(distractor.atom_id, result.ranked_atom_ids)
    selected = next(item for item in result.memory_pack.core + result.memory_pack.context if item.atom_id == anchor.atom_id)
    assert "Glass Menagerie" in selected.canonical_text
    assert "weather, snacks" not in selected.canonical_text


def test_retriever_weak_candidate_relevance_uses_local_excerpt_not_just_recent_backfill() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="weak_anchor",
            text=(
                "I rambled for a bit about coffee, playlists, and errands. "
                "The nickname I gave the project was Project Lantern Bloom. "
                "Then I went back to talking about weather and sleep."
            ),
            source_id="conv_weak_anchor",
            confidence=0.7,
            salience=0.62,
        )
    )
    noise = store.add_candidate(
        _candidate(
            candidate_id="weak_noise",
            text="Fresh weather log and temperature notes from this morning.",
            source_id="conv_weak_noise",
            confidence=0.92,
            salience=0.9,
        )
    )
    noise.updated_at = datetime.now(timezone.utc)
    retriever = MemoryRetriever(store)
    cache = retriever._get_cache()
    prepared_anchor = cache.prepared_by_id[anchor.atom_id]
    prepared_noise = cache.prepared_by_id[noise.atom_id]
    query_text = "What nickname did I give the project?"
    query_tokens = {"what", "nickname", "did", "i", "give", "the", "project"}

    assert retriever._weak_candidate_relevance(
        query_text,
        query_tokens,
        set(),
        prepared_anchor,
    )
    assert not retriever._weak_candidate_relevance(
        query_text,
        query_tokens,
        set(),
        prepared_noise,
    )


def test_focus_query_tokens_prioritize_discriminative_terms_over_count_scaffolding() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            candidate_id="focus_a",
            text="I baked cookies twice last week and wrote it down in my recipe log.",
            source_id="conv_focus_a",
        )
    )
    store.add_candidate(
        _candidate(
            candidate_id="focus_b",
            text="I visited two different doctors recently for follow-up appointments.",
            source_id="conv_focus_b",
        )
    )
    retriever = MemoryRetriever(store)
    cache = retriever._get_cache()

    focus_tokens = _focus_query_tokens(
        cache.token_doc_freq,
        {"how", "many", "times", "did", "i", "bake", "something", "in", "the", "past", "two", "weeks"},
    )

    assert "bake" in focus_tokens
    assert "many" not in focus_tokens
    assert "times" not in focus_tokens
    assert "weeks" not in focus_tokens


def test_retriever_focus_tokens_promote_content_match_over_generic_count_time_match() -> None:
    store = AtomStore()
    anchor = store.add_candidate(
        _candidate(
            candidate_id="focus_anchor",
            text="I just used my oven's convection setting for the first time last Thursday to bake a batch of cookies.",
            source_id="conv_focus_anchor",
            confidence=0.72,
            salience=0.63,
        )
    )
    count_distractor = store.add_candidate(
        _candidate(
            candidate_id="focus_count_noise",
            text="I sold 20 jars at the farmer's market at the town square three weeks ago.",
            source_id="conv_focus_count_noise",
            confidence=0.91,
            salience=0.88,
        )
    )
    time_distractor = store.add_candidate(
        _candidate(
            candidate_id="focus_time_noise",
            text="I've been doing daily meditation for at least 10 minutes every day for the past 2 weeks.",
            source_id="conv_focus_time_noise",
            confidence=0.9,
            salience=0.86,
        )
    )
    retriever = MemoryRetriever(store)

    result = retriever.retrieve("How many times did I bake something in the past two weeks?")

    assert anchor.atom_id in result.ranked_atom_ids[:5]
    assert _rank_of(anchor.atom_id, result.ranked_atom_ids) < _rank_of(count_distractor.atom_id, result.ranked_atom_ids)
    assert _rank_of(anchor.atom_id, result.ranked_atom_ids) < _rank_of(time_distractor.atom_id, result.ranked_atom_ids)


def test_retriever_source_support_bonus_rewards_multi_atom_focused_source_only() -> None:
    store = AtomStore()
    gold_a = store.add_candidate(
        _candidate(
            candidate_id="support_gold_a",
            text="I baked cookies last Thursday.",
            source_id="conv_support_gold",
        )
    )
    gold_b = store.add_candidate(
        _candidate(
            candidate_id="support_gold_b",
            text="I baked muffins on Saturday.",
            source_id="conv_support_gold",
        )
    )
    noise = store.add_candidate(
        _candidate(
            candidate_id="support_noise",
            text="I sold 20 jars at the market three weeks ago.",
            source_id="conv_support_noise",
        )
    )
    retriever = MemoryRetriever(store)

    bonuses = retriever._source_support_bonus(
        [noise.atom_id, gold_a.atom_id, gold_b.atom_id],
        {
            gold_a.atom_id: gold_a,
            gold_b.atom_id: gold_b,
            noise.atom_id: noise,
        },
        {
            noise.atom_id: 0.72,
            gold_a.atom_id: 0.61,
            gold_b.atom_id: 0.60,
        },
        {
            noise.atom_id: 0.08,
            gold_a.atom_id: 0.41,
            gold_b.atom_id: 0.40,
        },
        {
            noise.atom_id: 0.08,
            gold_a.atom_id: 1.0,
            gold_b.atom_id: 1.0,
        },
        {
            noise.atom_id: 0.10,
            gold_a.atom_id: 0.66,
            gold_b.atom_id: 0.64,
        },
        {
            noise.atom_id: 0.09,
            gold_a.atom_id: 0.62,
            gold_b.atom_id: 0.60,
        },
    )

    assert bonuses[gold_a.atom_id] > 0.0
    assert bonuses[gold_b.atom_id] > 0.0
    assert noise.atom_id not in bonuses


def test_retriever_source_support_bonus_can_use_contextual_preference_signals() -> None:
    store = AtomStore()
    gold_a = store.add_candidate(
        _candidate(
            candidate_id="context_gold_a",
            text="Lower screen brightness and enable low power mode to improve your phone battery life.",
            source_id="conv_context_gold",
        )
    )
    gold_b = store.add_candidate(
        _candidate(
            candidate_id="context_gold_b",
            text="Check battery usage by app and disable background refresh for the worst offenders.",
            source_id="conv_context_gold",
        )
    )
    noise = store.add_candidate(
        _candidate(
            candidate_id="context_noise",
            text="If you're having trouble deciding, here are some tips to help you choose.",
            source_id="conv_context_noise",
        )
    )
    retriever = MemoryRetriever(store)

    bonuses = retriever._source_support_bonus(
        [noise.atom_id, gold_a.atom_id, gold_b.atom_id],
        {
            gold_a.atom_id: gold_a,
            gold_b.atom_id: gold_b,
            noise.atom_id: noise,
        },
        {
            noise.atom_id: 0.74,
            gold_a.atom_id: 0.48,
            gold_b.atom_id: 0.46,
        },
        {
            noise.atom_id: 0.09,
            gold_a.atom_id: 0.28,
            gold_b.atom_id: 0.26,
        },
        {
            noise.atom_id: 0.10,
            gold_a.atom_id: 0.24,
            gold_b.atom_id: 0.22,
        },
        {
            noise.atom_id: 0.12,
            gold_a.atom_id: 0.18,
            gold_b.atom_id: 0.19,
        },
        {
            noise.atom_id: 0.16,
            gold_a.atom_id: 0.24,
            gold_b.atom_id: 0.23,
        },
        signal_threshold=0.20,
        score_floor=0.34,
    )

    assert bonuses[gold_a.atom_id] > 0.0
    assert bonuses[gold_b.atom_id] > 0.0
    assert noise.atom_id not in bonuses


def test_retriever_source_support_bonus_can_use_named_factual_signals() -> None:
    store = AtomStore()
    gold_a = store.add_candidate(
        _candidate(
            candidate_id="factual_gold_a",
            text="Caroline wants to pursue psychology.",
            source_id="conv_factual_gold",
        )
    )
    gold_b = store.add_candidate(
        _candidate(
            candidate_id="factual_gold_b",
            text="Caroline wants counseling certification training.",
            source_id="conv_factual_gold",
        )
    )
    noise = store.add_candidate(
        _candidate(
            candidate_id="factual_noise",
            text="Caroline said schools need more support.",
            source_id="conv_factual_noise",
        )
    )
    retriever = MemoryRetriever(store)

    bonuses = retriever._source_support_bonus(
        [noise.atom_id, gold_a.atom_id, gold_b.atom_id],
        {
            gold_a.atom_id: gold_a,
            gold_b.atom_id: gold_b,
            noise.atom_id: noise,
        },
        {
            noise.atom_id: 0.50,
            gold_a.atom_id: 0.43,
            gold_b.atom_id: 0.41,
        },
        {
            noise.atom_id: 0.18,
            gold_a.atom_id: 0.23,
            gold_b.atom_id: 0.22,
        },
        {
            noise.atom_id: 0.15,
            gold_a.atom_id: 0.20,
            gold_b.atom_id: 0.19,
        },
        {
            noise.atom_id: 0.12,
            gold_a.atom_id: 0.23,
            gold_b.atom_id: 0.21,
        },
        {
            noise.atom_id: 0.14,
            gold_a.atom_id: 0.24,
            gold_b.atom_id: 0.22,
        },
        signal_threshold=0.22,
        score_floor=0.36,
        bonus_cap=0.14,
        count_weight=0.04,
    )

    assert bonuses[gold_a.atom_id] > 0.0
    assert bonuses[gold_b.atom_id] > 0.0
    assert noise.atom_id not in bonuses


def test_retriever_question_shape_penalty_targets_prompt_like_candidates_for_preference_queries() -> None:
    retriever = MemoryRetriever(AtomStore())
    prompt_like = _candidate(
        candidate_id="pref_prompt_like",
        text="I'm anxious about getting around Tokyo. Do you have any helpful tips?",
        source_id="conv_pref_prompt_like",
    )
    answer_like = _candidate(
        candidate_id="pref_answer_like",
        text="Get a Suica card and download offline maps before you land in Tokyo.",
        source_id="conv_pref_answer_like",
    )

    prompt_penalty = retriever._question_shape_penalty(
        prompt_like,
        profile="preference_relational",
        speaker_intent="assistant",
        lexical=0.78,
        excerpt=0.74,
        focus=0.66,
        speaker_bias=0.0,
    )
    answer_penalty = retriever._question_shape_penalty(
        answer_like,
        profile="preference_relational",
        speaker_intent="assistant",
        lexical=0.42,
        excerpt=0.38,
        focus=0.34,
        speaker_bias=1.0,
    )

    assert prompt_penalty > 0.0
    assert answer_penalty == 0.0


def test_retriever_non_verbatim_fused_score_respects_speaker_bias() -> None:
    retriever = MemoryRetriever(AtomStore())

    without_speaker_bias = retriever._fused_score(
        lexical=0.33,
        bm25=0.8,
        semantic=0.18,
        sequence=0.0,
        quote=0.0,
        excerpt=0.32,
        focus=0.67,
        temporal=0.4,
        graph=0.0,
        continuity=0.45,
        rrf=0.62,
        conflict=False,
        support_count=1,
        recognition_bonus=0.0,
        shared_language_bonus=0.0,
        time_intent=False,
        profile="preference_relational",
        speaker_bias=0.0,
        name_bias=0.0,
    )
    with_speaker_bias = retriever._fused_score(
        lexical=0.33,
        bm25=0.8,
        semantic=0.18,
        sequence=0.0,
        quote=0.0,
        excerpt=0.32,
        focus=0.67,
        temporal=0.4,
        graph=0.0,
        continuity=0.45,
        rrf=0.62,
        conflict=False,
        support_count=1,
        recognition_bonus=0.0,
        shared_language_bonus=0.0,
        time_intent=False,
        profile="preference_relational",
        speaker_bias=1.0,
        name_bias=0.0,
    )

    assert with_speaker_bias > without_speaker_bias


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

    selected = retriever._score_candidates(
        cache,
        "nebulauniquetoken continuity anchor",
        {"nebulauniquetoken", "continuity", "anchor"},
        set(),
        profile="procedural",
    )
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


def test_retriever_explicit_quote_query_attaches_bounded_raw_context() -> None:
    store = AtomStore()
    candidate = _candidate(
        candidate_id="quote_anchor",
        text="I told you the nebula plan was paused.",
        source_id="conv_quote",
    )
    atom = store.add_candidate(candidate)
    store.record_raw_turn(
        NormalizedTurn(
            source_id="conv_quote",
            conversation_id="conv_quote",
            message_id="quote_anchor_msg",
            role="assistant",
            text="I told you the nebula plan was paused.",
            quote_text="  I told you the nebula plan was paused.  ",
            sequence_index=0,
        )
    )
    cfg = default_config()
    cfg.retrieval.raw_context_sidecar.read_enabled = True
    retriever = MemoryRetriever(store, config=cfg)

    result = retriever.retrieve('what exactly did you say about the nebula plan?')

    assert result.ranked_atom_ids[0] == atom.atom_id
    assert result.memory_pack.core[0].raw_context_text.startswith('Assistant:   I told you the nebula plan was paused.')
    assert result.memory_pack.core[0].raw_context_turn_count == 1


def test_retriever_non_quote_query_does_not_attach_raw_context() -> None:
    store = AtomStore()
    candidate = _candidate(
        candidate_id="quote_anchor_plain",
        text="I told you the nebula plan was paused.",
        source_id="conv_quote_plain",
    )
    store.add_candidate(candidate)
    store.record_raw_turn(
        NormalizedTurn(
            source_id="conv_quote_plain",
            conversation_id="conv_quote_plain",
            message_id="quote_anchor_plain_msg",
            role="assistant",
            text="I told you the nebula plan was paused.",
            quote_text="  I told you the nebula plan was paused.  ",
            sequence_index=0,
        )
    )
    cfg = default_config()
    cfg.retrieval.raw_context_sidecar.read_enabled = True
    retriever = MemoryRetriever(store, config=cfg)

    result = retriever.retrieve('what is the nebula plan status?')

    assert result.memory_pack.core[0].raw_context_text == ''
    assert result.memory_pack.core[0].raw_context_turn_count == 0
