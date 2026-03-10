from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "run_phase7_signoff.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_phase7_signoff", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load run_phase7_signoff module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _safe_limits(module) -> dict[str, float]:  # type: ignore[no-untyped-def]
    return dict(module.PROFILES["safe"])  # type: ignore[attr-defined]


def test_signoff_reasons_fail_closed_on_missing_metrics() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={"citation_hit_rate": 0.99},
        load_summary={},
        limits=_safe_limits(module),
    )
    assert any(reason.startswith("eval_summary_missing_metrics:") for reason in reasons)
    eval_missing = next(reason for reason in reasons if reason.startswith("eval_summary_missing_metrics:"))
    assert "decision_accuracy" in eval_missing
    assert "false_memory_rate" in eval_missing
    assert "episode_false_recall_rate" in eval_missing
    assert "episode_hit_rate" in eval_missing
    assert "episode_supported_cases" in eval_missing
    assert "routine_over_recall_rate" in eval_missing
    assert "p95_latency_ms" in eval_missing
    assert "cases" in eval_missing
    assert "load_summary_missing_metrics:atoms,failed_turns,latency_p95_ms,turns" in reasons


def test_signoff_reasons_thresholds_apply_when_metrics_present() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.03,
            "episode_false_recall_rate": 0.10,
            "episode_hit_rate": 0.25,
            "episode_supported_cases": 2,
            "citation_hit_rate": 0.97,
            "decision_accuracy": 0.79,
            "retrieval_hit_rate": 0.79,
            "abstain_precision": 0.59,
            "routine_over_recall_rate": 0.30,
            "p95_latency_ms": 7000.0,
            "cases": 6,
            "supported_cases": 3,
            "unsupported_cases": 3,
        },
        load_summary={"latency_p95_ms": 7000.0, "turns": 4, "failed_turns": 0, "atoms": 3},
        limits={**_safe_limits(module), "min_episode_hit_rate": 0.50},
    )
    assert "false_memory_rate_exceeded" in reasons
    assert "episode_false_recall_rate_exceeded" in reasons
    assert "routine_over_recall_rate_exceeded" in reasons
    assert "episode_hit_rate_below_floor" in reasons
    assert "citation_hit_rate_below_floor" in reasons
    assert "decision_accuracy_below_floor" in reasons
    assert "retrieval_hit_rate_below_floor" in reasons
    assert "abstain_precision_below_floor" in reasons
    assert "eval_p95_latency_exceeded" in reasons
    assert "load_p95_latency_exceeded" in reasons


def test_signoff_reasons_fail_when_load_turns_zero() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 1.0,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 1.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 6,
            "supported_cases": 3,
            "unsupported_cases": 3,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 0, "failed_turns": 0, "atoms": 3},
        limits=_safe_limits(module),
    )
    assert reasons == ["load_summary_no_turns"]


def test_signoff_reasons_fail_on_case_coverage() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 1.0,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 1.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 2,
            "supported_cases": 1,
            "unsupported_cases": 1,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 4, "failed_turns": 0, "atoms": 3},
        limits=_safe_limits(module),
    )
    assert "eval_case_coverage_insufficient" in reasons
    assert "eval_supported_case_coverage_insufficient" in reasons
    assert "eval_unsupported_case_coverage_insufficient" in reasons


def test_signoff_reasons_fail_on_failed_turn_rate() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 1.0,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 1.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 6,
            "supported_cases": 3,
            "unsupported_cases": 3,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 4, "failed_turns": 3, "atoms": 3},
        limits=_safe_limits(module),
    )
    assert reasons == ["load_failed_turn_rate_exceeded"]


def test_signoff_reasons_skip_abstain_precision_when_no_unsupported_cases() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 1.0,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 0.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 1,
            "supported_cases": 1,
            "unsupported_cases": 0,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 4, "failed_turns": 0, "atoms": 3},
        limits={
            **_safe_limits(module),
            "min_eval_cases": 1,
            "min_supported_cases": 1,
            "min_unsupported_cases": 0,
        },
    )
    assert reasons == []


def test_signoff_reasons_fail_on_continuity_thresholds() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 1.0,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 1.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 6,
            "supported_cases": 3,
            "unsupported_cases": 3,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 4, "failed_turns": 0, "atoms": 3},
        limits=_safe_limits(module),
        continuity_summary={"checks": 4, "recall_rate": 0.40, "citation_rate": 0.40},
    )
    assert "continuity_recall_rate_below_floor" in reasons
    assert "continuity_citation_rate_below_floor" in reasons


def test_signoff_reasons_fail_on_drift_regression() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 1.0,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 1.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 6,
            "supported_cases": 3,
            "unsupported_cases": 3,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 4, "failed_turns": 0, "atoms": 3},
        limits=_safe_limits(module),
        drift_decision="FAIL",
    )
    assert "eval_drift_regression" in reasons


def test_signoff_reasons_skip_episode_floor_without_episode_cases() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 1.0,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 1.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 6,
            "supported_cases": 3,
            "unsupported_cases": 3,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 4, "failed_turns": 0, "atoms": 3},
        limits={**_safe_limits(module), "min_episode_hit_rate": 0.95},
    )
    assert "episode_hit_rate_below_floor" not in reasons


def test_signoff_reasons_prefer_acceptance_gate_metrics_when_present() -> None:
    module = _load_module()
    reasons = module._signoff_reasons(  # type: ignore[attr-defined]
        eval_summary={
            "false_memory_rate": 0.0,
            "episode_false_recall_rate": 0.0,
            "episode_hit_rate": 0.0,
            "episode_supported_cases": 0,
            "citation_hit_rate": 0.20,
            "decision_accuracy": 1.0,
            "retrieval_hit_rate": 0.20,
            "abstain_precision": 1.0,
            "routine_over_recall_rate": 0.0,
            "p95_latency_ms": 1000.0,
            "cases": 24,
            "supported_cases": 17,
            "unsupported_cases": 7,
        },
        load_summary={"latency_p95_ms": 1000.0, "turns": 12, "failed_turns": 0, "atoms": 414},
        limits=_safe_limits(module),
        acceptance_gate={
            "decision": "PASS",
            "safety_verdict": "PASS",
            "human_quality_verdict": "PASS",
            "metrics": {
                "citation_hit_rate": 1.0,
                "decision_accuracy": 1.0,
                "retrieval_hit_rate": 1.0,
                "abstain_precision": 1.0,
                "false_memory_rate": 0.0,
                "routine_over_recall_rate": 0.0,
                "latency_p95_ms": 30.0,
            },
        },
    )
    assert "citation_hit_rate_below_floor" not in reasons
    assert "retrieval_hit_rate_below_floor" not in reasons
    assert "decision_accuracy_below_floor" not in reasons
    assert reasons == []


def test_acceptance_gate_reasons_fail_closed_on_missing_fields(tmp_path: Path) -> None:
    module = _load_module()
    reasons = module._acceptance_gate_reasons(  # type: ignore[attr-defined]
        {"decision": "PASS", "safety_verdict": "PASS"},
        readout_path=tmp_path / "missing.md",
    )
    assert reasons == ["acceptance_gate_missing_fields:human_quality_verdict"]


def test_acceptance_gate_reasons_surface_verdict_failures(tmp_path: Path) -> None:
    module = _load_module()
    readout = tmp_path / "human_readout.md"
    readout.write_text("# Human Readout\n", encoding="utf-8")
    reasons = module._acceptance_gate_reasons(  # type: ignore[attr-defined]
        {
            "decision": "FAIL",
            "safety_verdict": "PASS",
            "human_quality_verdict": "FAIL",
            "failures": ["blocking_defect_cases_exceeded"],
            "quality": {"defect_case_count": 2, "top_failure_examples": []},
        },
        readout_path=readout,
    )
    assert "human_quality_verdict_not_pass" in reasons
    assert "acceptance_gate_failure:blocking_defect_cases_exceeded" in reasons
