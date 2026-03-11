from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def oneclick_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "run_oneclick_eval.py"
    spec = importlib.util.spec_from_file_location("run_oneclick_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_oneclick_eval"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("run_oneclick_eval", None)


def test_default_export_path_prefers_user_online_activity_root_file(oneclick_module, tmp_path: Path) -> None:
    module = oneclick_module
    repo_root = tmp_path / "NumquamOblita"
    repo_root.mkdir(parents=True, exist_ok=True)
    (tmp_path / "User Online Activity").mkdir(parents=True, exist_ok=True)
    export_path = tmp_path / "User Online Activity" / "conversations.json"
    export_path.write_text("[]\n", encoding="utf-8")

    module.REPO_ROOT = repo_root
    detected = module._default_export_path()
    assert detected == export_path


def test_run_step_returns_fail_when_spawn_errors(oneclick_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = oneclick_module
    log_file = tmp_path / "step.log"

    def _raise(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(module.subprocess, "Popen", _raise)
    result = module._run_step("test", ["missing_cmd"], log_file)

    assert result.status == "FAIL"
    assert result.returncode != 0
    assert result.outputs == {}
    text = log_file.read_text(encoding="utf-8")
    assert "spawn_error=" in text
    assert "status=FAIL" in text


def test_safety_gate_reports_failures(oneclick_module) -> None:
    module = oneclick_module
    args = SimpleNamespace(
        min_decision_accuracy=0.90,
        min_citation_hit_rate=0.80,
        min_retrieval_hit_rate=0.80,
        min_abstain_precision=0.80,
        max_false_memory_rate=0.0,
        max_routine_over_recall_rate=0.0,
    )
    verdict, failures, metrics = module._safety_gate(
        {
            "decision_accuracy": 0.85,
            "citation_hit_rate": 0.79,
            "retrieval_hit_rate": 0.81,
            "abstain_precision": 0.70,
            "false_memory_rate": 0.01,
            "routine_over_recall_rate": 0.02,
        },
        args,
    )
    assert verdict == "FAIL"
    assert "decision_accuracy_below_floor" in failures
    assert "citation_hit_rate_below_floor" in failures
    assert "abstain_precision_below_floor" in failures
    assert "false_memory_rate_exceeded" in failures
    assert "routine_over_recall_rate_exceeded" in failures
    assert metrics["retrieval_hit_rate"] == pytest.approx(0.81)


def test_annotate_records_adds_blocking_and_question_defects(oneclick_module) -> None:
    module = oneclick_module
    records = [
        {
            "case": {"case_id": "tc_0001", "query": "What happened?"},
            "reply_text": "Acknowledged: What happened?",
            "verification": {"reasons": ["internal_jargon_leak"]},
        }
    ]
    defects, blocking = module._question_defect_map(
        [{"case_id": "tc_0001", "defect_tags": ["malformed_when_clause"], "blocking_defect_tags": []}]
    )
    annotated = module._annotate_records_with_defects(
        records,
        question_defects=defects,
        question_blocking=blocking,
    )
    assert len(annotated) == 1
    row = annotated[0]
    tags = set(row.get("defect_tags") or [])
    blocking_tags = set(row.get("blocking_defect_tags") or [])
    assert "malformed_when_clause" in tags
    assert "response_parrot_format" in tags
    assert "internal_jargon_leak" in tags
    assert "malformed_when_clause" in blocking_tags
    assert "response_parrot_format" in blocking_tags
    assert "internal_jargon_leak" in blocking_tags


def test_human_quality_gate_blocks_missing_alignment_and_blocking_defects(oneclick_module) -> None:
    module = oneclick_module
    args = SimpleNamespace(
        min_relevance_aligned_hit_rate=0.95,
        max_avg_retrieved_atoms=24.0,
        max_p95_retrieved_atoms=24.0,
        min_evidence_precision_at_k=0.70,
        max_junk_rate_at_k=0.25,
        min_conflict_coverage=1.0,
        max_blocking_defect_cases=0,
        max_memory_p95_ms=2000.0,
        max_model_p95_ms=15000.0,
        max_total_p95_ms=18000.0,
    )
    records = [
        {
            "case": {
                "case_id": "tc_0001",
                "case_type": "supported_recall",
                "expected_decision": "PASS",
                "query": "What do you remember?",
            },
            "reply_text": "Memory-backed response for: What do you remember?",
            "defect_tags": ["response_parrot_format"],
            "blocking_defect_tags": ["response_parrot_format"],
        }
    ]
    summary = {
        "retrieval": {
            "supported_non_routine_cases": 1,
            "supported_non_routine_with_expected_alignment": 0,
            "supported_non_routine_alignment_missing_cases": 1,
            "supported_non_routine_relevance_aligned_hit_rate": 0.0,
            "supported_non_routine_avg_retrieved_atoms": 32.0,
            "supported_non_routine_p95_retrieved_atoms": 32.0,
            "evidence_precision_at_k": 0.10,
            "junk_rate_at_k": 0.90,
            "conflict_labeled_supported_cases": 1,
            "conflict_covered_supported_cases": 0,
            "conflict_coverage": 0.0,
        }
    }
    question_summary = {"decision": "PASS", "event_grade_question_rate": 1.0, "fragment_question_rate": 0.0}
    verdict, failures, metrics, quality = module._human_quality_gate(summary, records, question_summary, args)
    assert verdict == "FAIL"
    assert "supported_non_routine_alignment_missing" in failures
    assert "relevance_aligned_hit_rate_below_floor" in failures
    assert "avg_retrieved_atoms_supported_non_routine_exceeded" in failures
    assert "p95_retrieved_atoms_supported_non_routine_exceeded" in failures
    assert "evidence_precision_at_k_below_floor" in failures
    assert "junk_rate_at_k_exceeded" in failures
    assert "conflict_coverage_below_floor" in failures
    assert "blocking_defect_cases_exceeded" in failures
    assert "response_parrot_cases_present" in failures
    assert metrics["blocking_defect_cases"] == pytest.approx(1.0)
    assert int(quality.get("blocking_defect_cases") or 0) == 1


def test_human_quality_gate_blocks_latency_budget_exceedances(oneclick_module) -> None:
    module = oneclick_module
    args = SimpleNamespace(
        min_relevance_aligned_hit_rate=0.90,
        max_avg_retrieved_atoms=24.0,
        max_p95_retrieved_atoms=24.0,
        min_evidence_precision_at_k=0.70,
        max_junk_rate_at_k=0.25,
        min_conflict_coverage=1.0,
        max_blocking_defect_cases=0,
        max_memory_p95_ms=10.0,
        max_model_p95_ms=20.0,
        max_total_p95_ms=30.0,
    )
    records = [
        {
            "case": {"case_id": "tc_0001", "case_type": "supported_recall", "expected_decision": "PASS", "query": "Q"},
            "reply_text": "A",
            "defect_tags": [],
            "blocking_defect_tags": [],
        }
    ]
    summary = {
        "retrieval": {
            "supported_non_routine_cases": 1,
            "supported_non_routine_with_expected_alignment": 1,
            "supported_non_routine_alignment_missing_cases": 0,
            "supported_non_routine_relevance_aligned_hit_rate": 1.0,
            "supported_non_routine_avg_retrieved_atoms": 1.0,
            "supported_non_routine_p95_retrieved_atoms": 1.0,
            "evidence_precision_at_k": 1.0,
            "junk_rate_at_k": 0.0,
            "conflict_labeled_supported_cases": 0,
            "conflict_covered_supported_cases": 0,
            "conflict_coverage": 1.0,
        },
        "latency_ms": {"memory_p95": 11.0, "model_p95": 21.0, "total_p95": 31.0},
    }
    question_summary = {"decision": "PASS", "event_grade_question_rate": 1.0, "fragment_question_rate": 0.0}
    verdict, failures, metrics, _quality = module._human_quality_gate(summary, records, question_summary, args)
    assert verdict == "FAIL"
    assert "memory_ms_p95_exceeded" in failures
    assert "model_ms_p95_exceeded" in failures
    assert "total_ms_p95_exceeded" in failures
    assert metrics["memory_ms_p95"] == pytest.approx(11.0)
    assert metrics["model_ms_p95"] == pytest.approx(21.0)
    assert metrics["total_ms_p95"] == pytest.approx(31.0)


def test_human_quality_gate_fails_closed_when_question_validator_fails(oneclick_module) -> None:
    module = oneclick_module
    args = SimpleNamespace(
        min_relevance_aligned_hit_rate=0.90,
        max_avg_retrieved_atoms=24.0,
        max_p95_retrieved_atoms=24.0,
        min_evidence_precision_at_k=0.0,
        max_junk_rate_at_k=1.0,
        min_conflict_coverage=0.0,
        max_blocking_defect_cases=0,
        max_memory_p95_ms=2000.0,
        max_model_p95_ms=15000.0,
        max_total_p95_ms=18000.0,
    )
    records = [
        {
            "case": {"case_id": "tc_0001", "case_type": "supported_recall", "expected_decision": "PASS", "query": "Q"},
            "reply_text": "A",
            "defect_tags": [],
            "blocking_defect_tags": [],
        }
    ]
    summary = {
        "retrieval": {
            "supported_non_routine_cases": 1,
            "supported_non_routine_with_expected_alignment": 1,
            "supported_non_routine_alignment_missing_cases": 0,
            "supported_non_routine_relevance_aligned_hit_rate": 1.0,
            "supported_non_routine_avg_retrieved_atoms": 1.0,
            "supported_non_routine_p95_retrieved_atoms": 1.0,
            "evidence_precision_at_k": 1.0,
            "junk_rate_at_k": 0.0,
            "conflict_labeled_supported_cases": 0,
            "conflict_covered_supported_cases": 0,
            "conflict_coverage": 1.0,
        },
        "latency_ms": {"memory_p95": 1.0, "model_p95": 1.0, "total_p95": 1.0},
    }
    question_summary = {
        "decision": "FAIL",
        "weak_cases": 1,
        "blocking_defect_cases": 0,
        "event_grade_question_rate": 1.0,
        "fragment_question_rate": 0.0,
    }

    verdict, failures, _metrics, _quality = module._human_quality_gate(summary, records, question_summary, args)

    assert verdict == "FAIL"
    assert "question_quality_validator_failed" in failures


def test_validate_gate_report_contract_detects_missing_fields(oneclick_module) -> None:
    module = oneclick_module
    missing = module._validate_gate_report_contract(
        {
            "decision": "PASS",
            "safety_verdict": "",
            "quality": {"defect_case_count": 0},
        }
    )
    assert "safety_verdict" in missing
    assert "human_quality_verdict" in missing
    assert "quality.blocking_defect_cases" in missing
    assert "quality.top_failure_examples" in missing


def test_validate_readout_contract_detects_missing_sections(oneclick_module) -> None:
    module = oneclick_module
    missing = module._validate_readout_contract_text("# Readout\n\n## Summary\n")
    assert "## Q/A Audit Table" in missing
    assert "## Top Failure Examples" in missing


def test_human_quality_gate_fails_non_finite_integrity_metrics(oneclick_module) -> None:
    module = oneclick_module
    args = SimpleNamespace(
        min_relevance_aligned_hit_rate=0.90,
        max_avg_retrieved_atoms=24.0,
        max_p95_retrieved_atoms=24.0,
        min_evidence_precision_at_k=0.70,
        max_junk_rate_at_k=0.25,
        min_conflict_coverage=1.0,
        max_blocking_defect_cases=0,
        max_memory_p95_ms=2000.0,
        max_model_p95_ms=15000.0,
        max_total_p95_ms=18000.0,
    )
    records = [
        {
            "case": {"case_id": "tc_0001", "case_type": "supported_recall", "expected_decision": "PASS", "query": "Q"},
            "reply_text": "A",
            "defect_tags": [],
            "blocking_defect_tags": [],
        }
    ]
    summary = {
        "retrieval": {
            "supported_non_routine_cases": 1,
            "supported_non_routine_with_expected_alignment": 1,
            "supported_non_routine_alignment_missing_cases": 0,
            "supported_non_routine_relevance_aligned_hit_rate": 1.0,
            "supported_non_routine_avg_retrieved_atoms": 1.0,
            "supported_non_routine_p95_retrieved_atoms": 1.0,
            "evidence_precision_at_k": "nan",
            "junk_rate_at_k": "inf",
            "conflict_labeled_supported_cases": 1,
            "conflict_covered_supported_cases": 1,
            "conflict_coverage": "nan",
        },
        "latency_ms": {"memory_p95": 1.0, "model_p95": 1.0, "total_p95": 1.0},
    }
    question_summary = {"decision": "PASS", "event_grade_question_rate": 1.0, "fragment_question_rate": 0.0}
    verdict, failures, _metrics, _quality = module._human_quality_gate(summary, records, question_summary, args)
    assert verdict == "FAIL"
    assert "evidence_precision_at_k_below_floor" in failures
    assert "junk_rate_at_k_exceeded" in failures
    assert "conflict_coverage_below_floor" in failures


def test_required_efficiency_metrics_detect_missing_fields(oneclick_module) -> None:
    module = oneclick_module
    metrics, failures = module._required_efficiency_metrics(
        {
            "false_memory_rate": 0.0,
            "abstain_precision": 1.0,
            "retrieval": {
                "evidence_precision_at_k": 1.0,
                "junk_rate_at_k": 0.0,
                "conflict_coverage": 1.0,
            },
        }
    )
    assert float(metrics.get("false_memory_rate")) == pytest.approx(0.0)
    assert "latency_p50_ms_missing" in failures
    assert "tokens_total_avg_missing" in failures
    assert "retrieval_fanout_avg_missing" in failures


def test_efficiency_regression_requires_median_of_3(oneclick_module) -> None:
    module = oneclick_module
    decision, failures, details = module._evaluate_efficiency_regression(
        baseline_runs=[{"latency_p50_ms": 100.0, "latency_p95_ms": 120.0, "tokens_total_avg": 50.0}],
        candidate_runs=[{"latency_p50_ms": 95.0, "latency_p95_ms": 110.0, "tokens_total_avg": 51.0}],
        led_surface="latency",
        max_non_led_regression_pct=3.0,
    )
    assert decision == "FAIL"
    assert "median_of_3_required" in failures
    assert int(details.get("baseline_run_count") or 0) == 1


def test_efficiency_regression_blocks_non_led_regression(oneclick_module) -> None:
    module = oneclick_module
    baseline = [{"latency_p50_ms": 100.0, "latency_p95_ms": 130.0, "tokens_total_avg": 100.0}] * 3
    candidate = [{"latency_p50_ms": 92.0, "latency_p95_ms": 118.0, "tokens_total_avg": 104.5}] * 3
    decision, failures, details = module._evaluate_efficiency_regression(
        baseline_runs=baseline,
        candidate_runs=candidate,
        led_surface="latency",
        max_non_led_regression_pct=3.0,
    )
    assert decision == "FAIL"
    assert "non_led_tokens_regressed_beyond_bound" in failures
    deltas = details.get("delta_pct") if isinstance(details.get("delta_pct"), dict) else {}
    assert float(deltas.get("tokens_total_avg") or 0.0) > 3.0


def test_parse_frozen_waivers_contract(oneclick_module) -> None:
    module = oneclick_module
    waivers, failures = module._parse_frozen_waivers(
        ["external reserved connector edits|docs/MNO_RUNTIME_EFFICIENCY_BLOCKERBOARD.md#MREB-104|external/research/*"]
    )
    assert not failures
    assert len(waivers) == 1
    waiver = waivers[0]
    assert str(waiver.get("classification") or "").startswith("FROZEN DUE TO ")
    assert str(waiver.get("blocker_ref") or "").strip()
    assert str(waiver.get("scope") or "").strip()


def test_required_efficiency_metrics_rejects_present_non_numeric(oneclick_module) -> None:
    module = oneclick_module
    _metrics, failures = module._required_efficiency_metrics(
        {
            "latency_p50_ms": "bad",
            "latency_p95_ms": 120.0,
            "tokens_prompt_avg": 10.0,
            "tokens_completion_avg": 5.0,
            "tokens_total_avg": 15.0,
            "retrieval_fanout_avg": 2.0,
            "retrieval_fanout_p95": 3.0,
            "false_memory_rate": 0.0,
            "abstain_precision": 1.0,
            "retrieval": {
                "evidence_precision_at_k": 1.0,
                "junk_rate_at_k": 0.0,
                "conflict_coverage": 1.0,
            },
        }
    )
    assert "latency_p50_ms_not_numeric" in failures


def test_main_forwards_explicit_truthset_to_responder_eval(oneclick_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = oneclick_module
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    module.REPO_ROOT = repo_root

    store_path = repo_root / "atoms.sqlite3"
    store_path.write_text("", encoding="utf-8")
    truthset_path = repo_root / "truthset.reviewed.jsonl"
    truthset_path.write_text('{"case_id":"tc_0001"}\n', encoding="utf-8")
    run_dir = repo_root / "runtime" / "evals" / "oneclick_test"
    run_dir.mkdir(parents=True, exist_ok=True)

    commands: list[tuple[str, list[str]]] = []

    def _step(name: str, command: list[str], log_file: Path):
        commands.append((name, list(command)))
        started_at = module._now_iso()
        finished_at = module._now_iso()
        if name == "run_responder_eval":
            eval_dir = run_dir / "eval"
            eval_dir.mkdir(parents=True, exist_ok=True)
            summary_path = eval_dir / "summary.json"
            records_path = eval_dir / "records.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "decision_accuracy": 1.0,
                        "citation_hit_rate": 1.0,
                        "retrieval_hit_rate": 1.0,
                        "abstain_precision": 1.0,
                        "false_memory_rate": 0.0,
                        "routine_over_recall_rate": 0.0,
                        "latency_p50_ms": 1.0,
                        "latency_p95_ms": 1.0,
                        "tokens_prompt_avg": 0.0,
                        "tokens_completion_avg": 0.0,
                        "tokens_total_avg": 0.0,
                        "retrieval_fanout_avg": 1.0,
                        "retrieval_fanout_p95": 1.0,
                        "latency_ms": {"memory_p95": 1.0, "model_p95": 1.0, "total_p95": 1.0},
                        "retrieval": {
                            "supported_non_routine_cases": 1,
                            "supported_non_routine_with_expected_alignment": 1,
                            "supported_non_routine_alignment_missing_cases": 0,
                            "supported_non_routine_relevance_aligned_hit_rate": 1.0,
                            "supported_non_routine_avg_retrieved_atoms": 1.0,
                            "supported_non_routine_p95_retrieved_atoms": 1.0,
                            "evidence_precision_at_k": 1.0,
                            "junk_rate_at_k": 0.0,
                            "conflict_labeled_supported_cases": 0,
                            "conflict_covered_supported_cases": 0,
                            "conflict_coverage": 1.0,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            records_path.write_text(
                json.dumps(
                    [
                        {
                            "case": {
                                "case_id": "tc_0001",
                                "case_type": "supported_recall",
                                "expected_decision": "PASS",
                                "query": "Q",
                            },
                            "reply_text": "A",
                            "defect_tags": [],
                            "blocking_defect_tags": [],
                            "retrieval": {"retrieved_atom_ids": ["a1"]},
                            "verification": {},
                        }
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            return module.StepResult(
                name=name,
                status="PASS",
                returncode=0,
                started_at=started_at,
                finished_at=finished_at,
                duration_s=0.0,
                command=command,
                log_file=str(log_file),
                outputs={
                    "summary_json": str(summary_path),
                    "records_json": str(records_path),
                    "truthset_generated_jsonl": str(truthset_path),
                },
            )
        if name == "validate_truthset_questions":
            quality_dir = run_dir / "question_quality"
            quality_dir.mkdir(parents=True, exist_ok=True)
            (quality_dir / "question_validation_summary.json").write_text(
                json.dumps(
                    {
                        "decision": "PASS",
                        "weak_cases": 0,
                        "blocking_defect_cases": 0,
                        "event_grade_question_rate": 1.0,
                        "fragment_question_rate": 0.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (quality_dir / "question_validation_cases.json").write_text("[]\n", encoding="utf-8")
            return module.StepResult(
                name=name,
                status="PASS",
                returncode=0,
                started_at=started_at,
                finished_at=finished_at,
                duration_s=0.0,
                command=command,
                log_file=str(log_file),
                outputs={},
            )
        if name == "build_responder_eval_readout":
            readout_path = run_dir / "human_readout.md"
            readout_path.write_text(
                "# Readout\n\n## Summary\n\n## Q/A Audit Table\n\n## Top Failure Examples\n",
                encoding="utf-8",
            )
            return module.StepResult(
                name=name,
                status="PASS",
                returncode=0,
                started_at=started_at,
                finished_at=finished_at,
                duration_s=0.0,
                command=command,
                log_file=str(log_file),
                outputs={},
            )
        raise AssertionError(f"unexpected step: {name}")

    monkeypatch.setattr(module, "_run_step", _step)
    monkeypatch.setattr(module, "_stamp", lambda: "oneclick_test")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_oneclick_eval.py",
            "--skip-import",
            "--disable-episodes",
            "--store",
            str(store_path),
            "--truthset",
            str(truthset_path),
            "--run-dir",
            str(run_dir),
        ],
    )

    rc = module.main()

    assert rc == 0
    responder_cmd = next(command for name, command in commands if name == "run_responder_eval")
    assert "--truthset" in responder_cmd
    assert str(truthset_path.resolve()) in responder_cmd
