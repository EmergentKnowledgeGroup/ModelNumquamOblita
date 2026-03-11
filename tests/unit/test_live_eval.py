from __future__ import annotations

from datetime import datetime, timezone

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession
from engine.runtime.live_eval import TruthsetCase, _related_alternate_detail, _subject_and_detail_for_atom
from engine.runtime.live_eval import evaluate_truthset, generate_truthset, plan_live_eval_workload
from engine.runtime.live_eval import LiveEvalRecord
from engine.runtime.live_eval import summarize_live_eval_records, validate_live_eval_required_metrics


def _candidate(candidate_id: str, text: str, source_id: str) -> CandidateAtom:
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
        topics=["test"],
        confidence=0.9,
        salience=0.7,
    )


def test_plan_live_eval_workload_downshifts() -> None:
    plan = plan_live_eval_workload(atom_count=50000, requested_cases=120, scan_budget=600000)
    assert plan.effective_cases == 12
    assert plan.estimated_scans == 600000
    assert plan.warning is not None


def test_plan_live_eval_workload_zero_atoms() -> None:
    plan = plan_live_eval_workload(atom_count=0, requested_cases=120, scan_budget=600000)
    assert plan.effective_cases == 0
    assert plan.estimated_scans == 0
    assert plan.warning is not None


def test_generate_truthset_has_supported_and_traps() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))

    cases = generate_truthset(store, total_cases=6)
    assert len(cases) == 6
    assert sum(1 for case in cases if case.case_type == "supported_recall") >= 3
    assert sum(1 for case in cases if case.case_type == "unsupported_trap") >= 1


def test_generate_truthset_trust_v2_has_family_mix() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))
    store.add_candidate(_candidate("c3", "Evidence beats guesses.", "conv_3"))

    cases = generate_truthset(store, total_cases=8, supported_ratio=0.75, fixture_mode="trust-v2")
    families = {case.fixture_family for case in cases}
    assert "supported_recall" in families
    assert "narrative_recall" in families
    assert "contradiction_pressure" in families
    assert "routine_chat" in families
    assert "unsupported_probe" in families


def test_generate_truthset_trust_v3_has_extended_family_mix() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))
    store.add_candidate(_candidate("c3", "Evidence beats guesses.", "conv_3"))

    cases = generate_truthset(store, total_cases=12, supported_ratio=0.75, fixture_mode="trust-v3")
    families = {case.fixture_family for case in cases}
    assert "timeline_recall" in families
    assert "confidence_guardrail" in families
    assert "unsupported_pressure" in families
    assert "unsupported_probe" in families
    routine_cases = [case for case in cases if case.fixture_family == "routine_chat"]
    assert routine_cases
    assert all(case.max_citations == 0 for case in routine_cases)
    assert all(case.max_retrieved_atoms == 0 for case in routine_cases)
    assert all(case.expected_memory_mode == "none" for case in routine_cases)


def test_generate_truthset_prefers_entity_cues_for_queries() -> None:
    store = AtomStore()
    candidate = _candidate("c1", "We last spoke with Dean about launch planning.", "conv_1")
    candidate.entities = ["Dean", "user", "assistant"]
    candidate.topics = ["launch_planning"]
    store.add_candidate(candidate)
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))

    cases = generate_truthset(store, total_cases=6, supported_ratio=1.0, fixture_mode="trust-v3")
    supported = [case for case in cases if case.case_type != "routine_chat"]
    assert supported
    assert any("Dean" in case.query for case in supported)
    assert all("this detail" not in case.query.lower() for case in supported)
    assert all(" about general " not in f" {case.query.lower()} " for case in supported)


def test_generate_truthset_contradiction_prompts_are_semantic() -> None:
    store = AtomStore()
    c1 = _candidate("c1", "Dean said we should ship the patch Friday morning.", "conv_1")
    c1.entities = ["Dean", "user", "assistant"]
    c1.topics = ["release_plan"]
    store.add_candidate(c1)
    store.add_candidate(_candidate("c2", "Ghost joked about raccoon mode in the channel.", "conv_2"))
    store.add_candidate(_candidate("c3", "We confirmed continuity notes need citations.", "conv_3"))

    cases = generate_truthset(store, total_cases=8, supported_ratio=0.75, fixture_mode="trust-v3")
    contradiction = [case for case in cases if case.fixture_family == "contradiction_pressure"]
    assert contradiction
    assert any("did dean" in case.query.lower() or "mixing this up" in case.query.lower() for case in contradiction)
    assert all("general " not in case.query.lower() for case in contradiction)


def test_generate_truthset_skips_semantic_correction_with_single_atom() -> None:
    store = AtomStore()
    c1 = _candidate("c1", "Dean said we should ship the patch Friday morning.", "conv_1")
    c1.entities = ["Dean", "user", "assistant"]
    c1.topics = ["release_plan"]
    store.add_candidate(c1)

    cases = generate_truthset(store, total_cases=8, supported_ratio=0.5, fixture_mode="trust-v3")
    families = [case.fixture_family for case in cases]
    assert "semantic_correction" not in families
    assert sum(1 for family in families if family in {"unsupported_probe", "unsupported_pressure"}) >= 4


def test_related_alternate_detail_prefers_semantic_overlap() -> None:
    store = AtomStore()
    c1 = _candidate("c1", "Claude said nuclear launch codes are a hard boundary.", "conv_1")
    c1.entities = ["Claude", "user", "assistant"]
    c1.topics = ["safety"]
    c2 = _candidate("c2", "Xander started building a Lego Enterprise D at 4am.", "conv_2")
    c2.entities = ["Xander", "user", "assistant"]
    c2.topics = ["lego"]
    c3 = _candidate("c3", "Dex wants 48 lines clean tight nothing wasted.", "conv_3")
    c3.entities = ["Dex", "user", "assistant"]
    c3.topics = ["editing"]
    c4 = _candidate("c4", "Claude said bioweapon synthesis is a hard boundary.", "conv_4")
    c4.entities = ["Claude", "user", "assistant"]
    c4.topics = ["safety"]
    for candidate in (c1, c2, c3, c4):
        store.add_candidate(candidate)

    atoms = list(store.list_atoms())
    target = next(atom for atom in atoms if "nuclear launch codes" in atom.canonical_text)
    unrelated_one = next(atom for atom in atoms if "Lego Enterprise D" in atom.canonical_text)
    unrelated_two = next(atom for atom in atoms if "48 lines clean tight" in atom.canonical_text)
    related = next(atom for atom in atoms if "bioweapon synthesis" in atom.canonical_text)
    subject, detail = _subject_and_detail_for_atom(target)

    alternate = _related_alternate_detail(
        [target, unrelated_one, unrelated_two, related],
        atom=target,
        current_index=0,
        subject=subject,
        detail=detail,
    )

    assert "bioweapon synthesis" in alternate.lower()
    assert "lego enterprise" not in alternate.lower()
    assert "48 lines" not in alternate.lower()


def test_generate_truthset_skips_semantic_correction_without_related_alternates() -> None:
    store = AtomStore()
    c1 = _candidate("c1", "Dean said we should ship the patch Friday morning.", "conv_1")
    c1.entities = ["Dean", "user", "assistant"]
    c1.topics = ["release_plan"]
    c2 = _candidate("c2", "Xander started building a Lego Enterprise D at 4am.", "conv_2")
    c2.entities = ["Xander", "user", "assistant"]
    c2.topics = ["lego"]
    c3 = _candidate("c3", "Dex wants 48 lines clean tight nothing wasted.", "conv_3")
    c3.entities = ["Dex", "user", "assistant"]
    c3.topics = ["editing"]
    for candidate in (c1, c2, c3):
        store.add_candidate(candidate)

    cases = generate_truthset(store, total_cases=8, supported_ratio=0.5, fixture_mode="trust-v3")
    families = [case.fixture_family for case in cases]

    assert "semantic_correction" not in families
    assert sum(1 for family in families if family in {"unsupported_probe", "unsupported_pressure"}) >= 4


def test_generate_truthset_expands_expected_alignment_for_duplicate_atoms() -> None:
    store = AtomStore()
    primary = _candidate(
        "c1",
        '*Dex said* "48 lines, clean, tight, nothing wasted, what\'s next" while we were reviewing the plan.',
        "conv_a",
    )
    primary.entities = ["Dex", "user", "assistant"]
    primary.topics = ["planning"]
    duplicate = _candidate(
        "c2",
        'Dex said "48 lines, clean, tight, nothing wasted, what\'s next" while we were reviewing the plan.',
        "conv_b",
    )
    duplicate.entities = ["Dex", "user", "assistant"]
    duplicate.topics = ["planning"]
    other = _candidate("c3", "Xander wants the memory system to stay fail-closed.", "conv_c")
    other.entities = ["Xander", "user", "assistant"]
    other.topics = ["memory"]
    for candidate in (primary, duplicate, other):
        store.add_candidate(candidate)

    cases = generate_truthset(store, total_cases=4, supported_ratio=1.0, fixture_mode="basic")
    target = next(case for case in cases if "48 lines" in case.query)

    expected_atom_ids = {
        atom.atom_id for atom in store.list_atoms() if "48 lines, clean, tight, nothing wasted" in atom.canonical_text
    }

    assert set(target.expected_atom_ids) == expected_atom_ids
    assert set(target.expected_citations) == {"conv_a#c1_msg", "conv_b#c2_msg"}


def test_generate_truthset_emits_one_supported_case_per_duplicate_signature() -> None:
    store = AtomStore()
    primary = _candidate(
        "c1",
        'Dex said "48 lines, clean, tight, nothing wasted, what\'s next" while we were reviewing the plan.',
        "conv_a",
    )
    primary.entities = ["Dex", "user", "assistant"]
    primary.topics = ["planning"]
    duplicate = _candidate(
        "c2",
        '*Dex said* "48 lines, clean, tight, nothing wasted, what\'s next" while we were reviewing the plan.',
        "conv_b",
    )
    duplicate.entities = ["Dex", "user", "assistant"]
    duplicate.topics = ["planning"]
    other = _candidate("c3", "Xander wants the memory system to stay fail-closed.", "conv_c")
    other.entities = ["Xander", "user", "assistant"]
    other.topics = ["memory"]
    for candidate in (primary, duplicate, other):
        store.add_candidate(candidate)

    cases = generate_truthset(store, total_cases=2, supported_ratio=1.0, fixture_mode="basic")
    duplicate_signature_cases = [
        case for case in cases if "48 lines" in case.query.lower() or "48 lines" in str(case.retrieval_query or "").lower()
    ]

    assert len(duplicate_signature_cases) == 1


def test_truthset_case_from_dict_backfills_fixture_family() -> None:
    payload = {
        "case_id": "tc_0001",
        "case_type": "supported_recall",
        "query": "What do you remember about tea?",
        "expected_decision": "PASS",
    }
    case = TruthsetCase.from_dict(payload)
    assert case.fixture_family == "supported_recall"
    assert case.expected_memory_mode is None


def test_evaluate_truthset_produces_metrics() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=False,
    )

    cases = generate_truthset(store, total_cases=4)
    summary, records = evaluate_truthset(
        runtime,
        cases,
        atoms=len(store.list_atoms()),
        requested_cases=4,
        scan_budget=10000,
    )

    assert len(records) == 4
    assert summary.cases == 4
    assert summary.supported_cases + summary.unsupported_cases == 4
    assert summary.false_memory_cases >= 0
    assert 0.0 <= summary.decision_accuracy <= 1.0
    assert 0.0 <= summary.citation_hit_rate <= 1.0
    assert 0.0 <= summary.retrieval_hit_rate <= 1.0
    assert summary.supported_non_routine_cases >= 0
    assert summary.supported_non_routine_with_expected_alignment >= 0
    assert summary.supported_non_routine_alignment_missing_cases >= 0
    assert 0.0 <= summary.relevance_aligned_hit_rate <= 1.0
    assert 0.0 <= summary.evidence_precision_at_k <= 1.0
    assert 0.0 <= summary.junk_rate_at_k <= 1.0
    assert summary.conflict_labeled_supported_cases >= 0
    assert summary.conflict_covered_supported_cases >= 0
    assert 0.0 <= summary.conflict_coverage <= 1.0
    assert 0.0 <= summary.abstain_precision <= 1.0
    assert 0.0 <= summary.routine_over_recall_rate <= 1.0
    assert 0.0 <= summary.episode_hit_rate <= 1.0
    assert 0.0 <= summary.episode_false_recall_rate <= 1.0
    assert summary.total_tokens >= 1
    assert summary.latency_p50_ms >= 0.0
    assert summary.latency_p95_ms >= 0.0
    assert summary.tokens_prompt_avg >= 0.0
    assert summary.tokens_completion_avg >= 0.0
    assert summary.tokens_total_avg >= 0.0
    assert summary.retrieval_fanout_avg >= 0.0
    assert summary.retrieval_fanout_p95 >= 0.0
    assert abs(summary.tokens_total_avg - (summary.tokens_prompt_avg + summary.tokens_completion_avg)) < 1e-9
    assert not validate_live_eval_required_metrics(summary)
    assert isinstance(summary.fixture_case_counts, dict)


def test_summarize_live_eval_records_matches_evaluate_output() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=False,
    )

    cases = generate_truthset(store, total_cases=4)
    summary, records = evaluate_truthset(
        runtime,
        cases,
        atoms=len(store.list_atoms()),
        requested_cases=4,
        scan_budget=10000,
    )
    recomputed = summarize_live_eval_records(
        records=records,
        runtime=runtime,
        atoms=len(store.list_atoms()),
        requested_cases=4,
        scan_budget=10000,
    )
    assert recomputed.cases == summary.cases
    assert recomputed.false_memory_rate == summary.false_memory_rate
    assert recomputed.retrieval_hit_rate == summary.retrieval_hit_rate
    assert recomputed.relevance_aligned_hit_rate == summary.relevance_aligned_hit_rate
    assert recomputed.evidence_precision_at_k == summary.evidence_precision_at_k
    assert recomputed.junk_rate_at_k == summary.junk_rate_at_k
    assert recomputed.conflict_coverage == summary.conflict_coverage
    assert isinstance(recomputed.memory_mode_case_counts, dict)
    assert isinstance(recomputed.memory_mode_avg_latency_ms, dict)
    assert isinstance(recomputed.memory_mode_p95_latency_ms, dict)
    assert recomputed.tokens_total_avg >= 0.0
    assert recomputed.retrieval_fanout_avg >= 0.0
    assert recomputed.retrieval_fanout_p95 >= 0.0
    assert not validate_live_eval_required_metrics(recomputed)


def test_validate_live_eval_required_metrics_rejects_non_finite_values() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    store.add_candidate(_candidate("c2", "Continuity requires citations.", "conv_2"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=False,
    )

    cases = generate_truthset(store, total_cases=4)
    summary, _records = evaluate_truthset(
        runtime,
        cases,
        atoms=len(store.list_atoms()),
        requested_cases=4,
        scan_budget=10000,
    )
    summary.tokens_total_avg = float("nan")
    failures = validate_live_eval_required_metrics(summary)
    assert "tokens_total_avg_non_finite" in failures


def test_evaluate_truthset_routine_chat_records_no_recall() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=False,
    )

    cases = [
        TruthsetCase(
            case_id="tc_0001",
            case_type="routine_chat",
            fixture_family="routine_chat",
            query="Hey there, no memory recall needed.",
            expected_decision="PASS",
            expected_citations=[],
            expected_atom_ids=[],
            expected_memory_mode="none",
            max_citations=0,
            max_retrieved_atoms=0,
        )
    ]
    summary, records = evaluate_truthset(
        runtime,
        cases,
        atoms=len(store.list_atoms()),
        requested_cases=1,
        scan_budget=10000,
    )
    assert len(records) == 1
    assert isinstance(records[0].over_recall, bool)
    assert records[0].expected_memory_mode == "none"
    assert summary.routine_cases == 1
    assert 0.0 <= summary.routine_over_recall_rate <= 1.0
    assert summary.memory_mode_checked_cases == 1


def test_evaluate_truthset_supported_case_without_expected_anchors_is_forced_miss() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=False,
    )

    cases = [
        TruthsetCase(
            case_id="tc_missing_alignment",
            case_type="supported_recall",
            fixture_family="supported_recall",
            query="What do you remember about tea at midnight?",
            retrieval_query="tea midnight",
            expected_decision="PASS",
            expected_citations=[],
            expected_atom_ids=[],
        )
    ]
    summary, records = evaluate_truthset(
        runtime,
        cases,
        atoms=len(store.list_atoms()),
        requested_cases=1,
        scan_budget=10000,
    )
    assert len(records) == 1
    assert records[0].citation_hit is False
    assert records[0].retrieval_hit is False
    assert summary.supported_cases == 1
    assert summary.citation_hit_rate == 0.0
    assert summary.retrieval_hit_rate == 0.0


def test_summarize_live_eval_records_tracks_episode_and_routine_metrics() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea at midnight.", "conv_1"))

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
        short_term_enabled=False,
    )

    records = [
        LiveEvalRecord(
            case_id="tc_ep_1",
            case_type="supported_recall",
            fixture_family="supported_recall",
            expected_decision="PASS",
            actual_decision="PASS",
            decision_correct=True,
            expected_citations=[],
            citations=["conv_1"],
            citation_hit=True,
            citation_count=1,
            expected_atom_ids=["episode_card:tea"],
            retrieved_atom_ids=["episode_card:tea"],
            retrieval_hit=True,
            retrieved_atom_count=1,
            false_memory=False,
            over_recall=False,
            latency_ms=10.0,
            turn_cost_usd=0.0,
            memory_mode="episode",
            expected_memory_mode=None,
            memory_mode_match=True,
            short_term_hits=0,
        ),
        LiveEvalRecord(
            case_id="tc_ep_2",
            case_type="narrative_recall",
            fixture_family="narrative_recall",
            expected_decision="PASS",
            actual_decision="PASS",
            decision_correct=True,
            expected_citations=[],
            citations=["conv_1"],
            citation_hit=True,
            citation_count=1,
            expected_atom_ids=["atom:c1"],
            retrieved_atom_ids=["atom:c1"],
            retrieval_hit=True,
            retrieved_atom_count=1,
            false_memory=False,
            over_recall=False,
            latency_ms=12.0,
            turn_cost_usd=0.0,
            memory_mode="memory",
            expected_memory_mode=None,
            memory_mode_match=True,
            short_term_hits=0,
        ),
        LiveEvalRecord(
            case_id="tc_unsupported",
            case_type="unsupported_trap",
            fixture_family="unsupported_probe",
            expected_decision="ABSTAIN",
            actual_decision="PASS",
            decision_correct=False,
            expected_citations=[],
            citations=[],
            citation_hit=False,
            citation_count=0,
            expected_atom_ids=[],
            retrieved_atom_ids=["episode_card:ghost"],
            retrieval_hit=False,
            retrieved_atom_count=1,
            false_memory=True,
            over_recall=False,
            latency_ms=8.0,
            turn_cost_usd=0.0,
            memory_mode="memory",
            expected_memory_mode=None,
            memory_mode_match=True,
            short_term_hits=0,
        ),
        LiveEvalRecord(
            case_id="tc_routine",
            case_type="routine_chat",
            fixture_family="routine_chat",
            expected_decision="PASS",
            actual_decision="PASS",
            decision_correct=True,
            expected_citations=[],
            citations=[],
            citation_hit=True,
            citation_count=0,
            expected_atom_ids=[],
            retrieved_atom_ids=[],
            retrieval_hit=True,
            retrieved_atom_count=0,
            false_memory=False,
            over_recall=True,
            latency_ms=9.0,
            turn_cost_usd=0.0,
            memory_mode="none",
            expected_memory_mode="none",
            memory_mode_match=True,
            short_term_hits=0,
        ),
    ]
    summary = summarize_live_eval_records(
        records=records,
        runtime=runtime,
        atoms=len(store.list_atoms()),
        requested_cases=4,
        scan_budget=10000,
    )
    assert summary.routine_cases == 1
    assert summary.routine_over_recall_rate == 1.0
    assert summary.episode_supported_cases == 2
    assert summary.episode_hit_cases == 1
    assert summary.episode_hit_rate == 0.5
    assert summary.episode_false_recall_cases == 1
    assert summary.episode_false_recall_rate == 1.0
    assert summary.memory_mode_case_counts.get("episode") == 1
    assert summary.memory_mode_case_counts.get("none") == 1


def test_generate_truthset_skips_payload_like_atoms_for_supported_cases() -> None:
    store = AtomStore()
    store.add_candidate(
        _candidate(
            "c_payload",
            '{ "updates":[{"pattern":".","replacement":"### noisy payload"}] }',
            "conv_payload",
        )
    )
    store.add_candidate(
        _candidate(
            "c_good",
            "On Tuesday evening we finalized migration rollback safeguards before shipping.",
            "conv_good",
        )
    )
    cases = generate_truthset(store, total_cases=2, fixture_mode="basic")
    supported = [case for case in cases if case.expected_decision == "PASS"]
    assert supported
    for case in supported:
        assert "updates" not in str(case.retrieval_query or "").lower()
        assert "replacement" not in str(case.retrieval_query or "").lower()
