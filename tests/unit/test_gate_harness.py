from __future__ import annotations

from engine.runtime import EvalRecord, evaluate_gate


def _record(
    *,
    query_id: str,
    unsupported_claims: int = 0,
    high_sev: bool = False,
    recall_hit: bool = True,
    temporal_correct: bool = True,
    verifier_blocked: bool = True,
    conflict_prompt: bool = False,
    uncertainty_emitted: bool = True,
    abstain_expected: bool = False,
    abstain_emitted: bool = False,
    latency_ms: float = 600.0,
    claims: int = 1,
    unsupported_on_gold: bool = False,
) -> EvalRecord:
    return EvalRecord(
        query_id=query_id,
        query_class="factual",
        memory_age_bucket="recent",
        memory_claims=claims,
        unsupported_claims=unsupported_claims,
        recall_hit=recall_hit,
        temporal_correct=temporal_correct,
        high_severity_false_memory=high_sev,
        verifier_blocked_unsupported=verifier_blocked,
        conflict_prompt=conflict_prompt,
        uncertainty_emitted=uncertainty_emitted,
        abstain_expected=abstain_expected,
        abstain_emitted=abstain_emitted,
        latency_ms=latency_ms,
        unsupported_on_gold_trace=unsupported_on_gold,
    )


def test_gate_evaluation_fails_on_safety_violations() -> None:
    records = [_record(query_id="q1", unsupported_claims=1, claims=1, unsupported_on_gold=True)]
    outcome = evaluate_gate(
        records,
        dataset_counts={"gold": 500, "contradiction": 150, "adversarial": 150, "drift": 100, "recognition": 120},
        failure_case_results={"FC-04": True, "FC-08": True, "FC-20": False, "FC-25": True},
        must_pass_case_ids={"FC-04", "FC-08", "FC-20", "FC-25"},
    )
    assert outcome.decision == "FAIL"
    assert "must_pass_failure_cases" in outcome.reasons
    assert "unsupported_claims_on_gold_trace" in outcome.reasons


def test_gate_evaluation_passes_when_all_thresholds_met() -> None:
    records = [_record(query_id=f"q{i}") for i in range(700)]
    outcome = evaluate_gate(
        records,
        dataset_counts={"gold": 500, "contradiction": 200, "adversarial": 180, "drift": 120, "recognition": 140},
        failure_case_results={"FC-04": True, "FC-08": True, "FC-20": True, "FC-25": True},
        must_pass_case_ids={"FC-04", "FC-08", "FC-20", "FC-25"},
    )
    assert outcome.decision == "PASS"
    assert outcome.reasons == []


def test_gate_evaluation_flags_unexpected_abstentions() -> None:
    records = [_record(query_id=f"q{i}") for i in range(200)]
    for index in range(40):
        records[index].abstain_emitted = True
        records[index].abstain_expected = False
    outcome = evaluate_gate(
        records,
        dataset_counts={"gold": 500, "contradiction": 200, "adversarial": 180, "drift": 120, "recognition": 140},
        failure_case_results={"FC-04": True, "FC-08": True, "FC-20": True, "FC-25": True},
        must_pass_case_ids={"FC-04", "FC-08", "FC-20", "FC-25"},
    )
    assert "abstention_quality_below_floor" in outcome.reasons
