from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(int(round(0.95 * (len(ordered) - 1))), 0)
    return ordered[index]


@dataclass(slots=True)
class EvalRecord:
    query_id: str
    query_class: str
    memory_age_bucket: str
    memory_claims: int
    unsupported_claims: int
    recall_hit: bool
    temporal_correct: bool
    high_severity_false_memory: bool
    verifier_blocked_unsupported: bool
    conflict_prompt: bool
    uncertainty_emitted: bool
    abstain_expected: bool
    abstain_emitted: bool
    latency_ms: float
    unsupported_on_gold_trace: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalRecord":
        return cls(
            query_id=str(payload.get("query_id") or ""),
            query_class=str(payload.get("query_class") or "mixed"),
            memory_age_bucket=str(payload.get("memory_age_bucket") or "unknown"),
            memory_claims=int(payload.get("memory_claims") or 0),
            unsupported_claims=int(payload.get("unsupported_claims") or 0),
            recall_hit=bool(payload.get("recall_hit")),
            temporal_correct=bool(payload.get("temporal_correct", True)),
            high_severity_false_memory=bool(payload.get("high_severity_false_memory")),
            verifier_blocked_unsupported=bool(payload.get("verifier_blocked_unsupported")),
            conflict_prompt=bool(payload.get("conflict_prompt")),
            uncertainty_emitted=bool(payload.get("uncertainty_emitted")),
            abstain_expected=bool(payload.get("abstain_expected")),
            abstain_emitted=bool(payload.get("abstain_emitted")),
            latency_ms=float(payload.get("latency_ms") or 0.0),
            unsupported_on_gold_trace=bool(payload.get("unsupported_on_gold_trace")),
        )


@dataclass(slots=True)
class GateMetrics:
    false_memory_rate: float
    high_severity_false_memory_rate: float
    evidence_precision_at_k: float
    recall_at_8: float
    temporal_accuracy: float
    claim_verifier_block_rate: float
    unsupported_claim_count_on_gold_trace: int
    abstention_quality: float
    conflict_handling_score: float
    retrieval_latency_p95: float
    memory_claim_coverage: float


@dataclass(slots=True)
class GateOutcome:
    decision: str
    reasons: list[str]
    metrics: GateMetrics
    dataset_counts: dict[str, int]
    must_pass_failures: list[str]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reasons": list(self.reasons),
            "metrics": asdict(self.metrics),
            "dataset_counts": dict(self.dataset_counts),
            "must_pass_failures": list(self.must_pass_failures),
            "generated_at": self.generated_at,
        }


LEVEL_A_THRESHOLDS = {
    "false_memory_rate": 0.02,
    "high_severity_false_memory_rate": 0.005,
    "evidence_precision_at_k": 0.95,
    "recall_at_8": 0.88,
    "temporal_accuracy": 0.85,
    "claim_verifier_block_rate": 0.99,
    "unsupported_claim_count_on_gold_trace": 0,
    "abstention_quality": 0.90,
    "conflict_handling_score": 0.98,
    "retrieval_latency_p95": 1200.0,
    "memory_claim_coverage": 0.60,
}

MIN_DATASET_COUNTS = {
    "gold": 500,
    "contradiction": 150,
    "adversarial": 150,
    "drift": 100,
    "recognition": 120,
}


def compute_metrics(records: list[EvalRecord]) -> GateMetrics:
    total_claims = sum(record.memory_claims for record in records)
    unsupported_claims = sum(record.unsupported_claims for record in records)
    high_severity_count = sum(1 for record in records if record.high_severity_false_memory)
    recall_hits = sum(1 for record in records if record.recall_hit)
    temporal_hits = sum(1 for record in records if record.temporal_correct)
    verifier_blocks = sum(1 for record in records if record.verifier_blocked_unsupported)
    gold_unsupported = sum(1 for record in records if record.unsupported_on_gold_trace)

    abstention_matches = [record for record in records if record.abstain_expected == record.abstain_emitted]

    conflict_records = [record for record in records if record.conflict_prompt]
    conflict_correct = sum(1 for record in conflict_records if record.uncertainty_emitted)
    records_with_claims = sum(1 for record in records if record.memory_claims > 0)
    latency_values = [record.latency_ms for record in records]

    false_memory_rate = _ratio(unsupported_claims, max(total_claims, 1))
    evidence_precision = 1.0 - false_memory_rate
    abstention_quality = _ratio(len(abstention_matches), len(records))
    conflict_handling = _ratio(conflict_correct, max(len(conflict_records), 1))
    if not conflict_records:
        conflict_handling = 1.0

    return GateMetrics(
        false_memory_rate=false_memory_rate,
        high_severity_false_memory_rate=_ratio(high_severity_count, max(total_claims, 1)),
        evidence_precision_at_k=max(0.0, evidence_precision),
        recall_at_8=_ratio(recall_hits, len(records)),
        temporal_accuracy=_ratio(temporal_hits, len(records)),
        claim_verifier_block_rate=_ratio(verifier_blocks, max(sum(1 for record in records if record.unsupported_claims > 0), 1)),
        unsupported_claim_count_on_gold_trace=gold_unsupported,
        abstention_quality=abstention_quality,
        conflict_handling_score=conflict_handling,
        retrieval_latency_p95=_p95(latency_values),
        memory_claim_coverage=_ratio(records_with_claims, len(records)),
    )


def evaluate_failure_matrix(case_results: dict[str, bool], must_pass_case_ids: set[str]) -> list[str]:
    failed = []
    for case_id in sorted(must_pass_case_ids):
        if not case_results.get(case_id, False):
            failed.append(case_id)
    return failed


def evaluate_gate(
    records: list[EvalRecord],
    *,
    dataset_counts: dict[str, int],
    failure_case_results: dict[str, bool],
    must_pass_case_ids: set[str],
) -> GateOutcome:
    metrics = compute_metrics(records)
    reasons: list[str] = []
    must_pass_failures = evaluate_failure_matrix(failure_case_results, must_pass_case_ids)

    for key, minimum in MIN_DATASET_COUNTS.items():
        if dataset_counts.get(key, 0) < minimum:
            reasons.append(f"dataset_count_below_minimum:{key}")

    if must_pass_failures:
        reasons.append("must_pass_failure_cases")

    if metrics.false_memory_rate > LEVEL_A_THRESHOLDS["false_memory_rate"]:
        reasons.append("false_memory_rate_exceeded")
    if metrics.high_severity_false_memory_rate > LEVEL_A_THRESHOLDS["high_severity_false_memory_rate"]:
        reasons.append("high_severity_false_memory_exceeded")
    if metrics.evidence_precision_at_k < LEVEL_A_THRESHOLDS["evidence_precision_at_k"]:
        reasons.append("evidence_precision_below_floor")
    if metrics.recall_at_8 < LEVEL_A_THRESHOLDS["recall_at_8"]:
        reasons.append("recall_below_floor")
    if metrics.temporal_accuracy < LEVEL_A_THRESHOLDS["temporal_accuracy"]:
        reasons.append("temporal_accuracy_below_floor")
    if metrics.claim_verifier_block_rate < LEVEL_A_THRESHOLDS["claim_verifier_block_rate"]:
        reasons.append("verifier_block_rate_below_floor")
    if metrics.unsupported_claim_count_on_gold_trace > LEVEL_A_THRESHOLDS["unsupported_claim_count_on_gold_trace"]:
        reasons.append("unsupported_claims_on_gold_trace")
    if metrics.abstention_quality < LEVEL_A_THRESHOLDS["abstention_quality"]:
        reasons.append("abstention_quality_below_floor")
    if metrics.conflict_handling_score < LEVEL_A_THRESHOLDS["conflict_handling_score"]:
        reasons.append("conflict_handling_below_floor")
    if metrics.retrieval_latency_p95 > LEVEL_A_THRESHOLDS["retrieval_latency_p95"]:
        reasons.append("latency_p95_exceeded")
    if metrics.memory_claim_coverage < LEVEL_A_THRESHOLDS["memory_claim_coverage"]:
        reasons.append("memory_claim_coverage_below_floor")

    safety_keys = {
        "false_memory_rate_exceeded",
        "high_severity_false_memory_exceeded",
        "verifier_block_rate_below_floor",
        "unsupported_claims_on_gold_trace",
        "must_pass_failure_cases",
    }
    if any(reason in safety_keys for reason in reasons):
        decision = "FAIL"
    elif reasons:
        decision = "CONDITIONAL"
    else:
        decision = "PASS"

    return GateOutcome(
        decision=decision,
        reasons=reasons,
        metrics=metrics,
        dataset_counts=dataset_counts,
        must_pass_failures=must_pass_failures,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def write_gate_report(outcome: GateOutcome, *, out_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = directory / f"gate_report_{stamp}.json"
    md_path = directory / f"gate_report_{stamp}.md"

    json_path.write_text(json.dumps(outcome.to_dict(), indent=2), encoding="utf-8")
    lines = [
        "# NumquamOblita Gate Report",
        "",
        f"- Decision: `{outcome.decision}`",
        f"- Generated: `{outcome.generated_at}`",
        f"- Must-pass failures: `{', '.join(outcome.must_pass_failures) if outcome.must_pass_failures else 'none'}`",
        "",
        "## Reasons",
    ]
    if outcome.reasons:
        lines.extend([f"- {reason}" for reason in outcome.reasons])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Metrics",
            f"- false_memory_rate: `{outcome.metrics.false_memory_rate:.4f}`",
            f"- high_severity_false_memory_rate: `{outcome.metrics.high_severity_false_memory_rate:.4f}`",
            f"- evidence_precision@k: `{outcome.metrics.evidence_precision_at_k:.4f}`",
            f"- recall@8: `{outcome.metrics.recall_at_8:.4f}`",
            f"- temporal_accuracy: `{outcome.metrics.temporal_accuracy:.4f}`",
            f"- claim_verifier_block_rate: `{outcome.metrics.claim_verifier_block_rate:.4f}`",
            f"- unsupported_claim_count_on_gold_trace: `{outcome.metrics.unsupported_claim_count_on_gold_trace}`",
            f"- abstention_quality: `{outcome.metrics.abstention_quality:.4f}`",
            f"- conflict_handling_score: `{outcome.metrics.conflict_handling_score:.4f}`",
            f"- retrieval_latency_p95: `{outcome.metrics.retrieval_latency_p95:.1f}`",
            f"- memory_claim_coverage: `{outcome.metrics.memory_claim_coverage:.4f}`",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
