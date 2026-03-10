from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "build_responder_eval_readout.py"
    spec = importlib.util.spec_from_file_location("build_responder_eval_readout", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_responder_eval_readout"] = module
    spec.loader.exec_module(module)
    return module


def test_readout_always_emits_qa_table_and_top_failure_section(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    try:
        records_path = tmp_path / "records.json"
        summary_path = tmp_path / "summary.json"
        gate_path = tmp_path / "acceptance_gate.json"
        out_path = tmp_path / "human_readout.md"

        records_path.write_text(
            json.dumps(
                [
                    {
                        "case": {
                            "case_id": "tc_0001",
                            "case_type": "supported_recall",
                            "fixture_family": "supported_recall",
                            "query": "What did we decide?",
                            "expected_decision": "PASS",
                        },
                        "service_decision": "PASS",
                        "verification": {"ok": True, "reasons": []},
                        "latency_ms": {"memory_ms": 1.0, "model_ms": 1.0, "total_ms": 2.0},
                        "retrieval": {
                            "retrieval_diagnostics": {
                                "selected": [
                                    {
                                        "atom_id": "mem_selected_1",
                                        "section": "core",
                                        "score": 0.91,
                                        "canonical_text": "secret selected text must stay redacted",
                                    }
                                ],
                                "dropped": [
                                    {
                                        "atom_id": "mem_dropped_1",
                                        "reason_code": "BUDGET",
                                        "score": 0.44,
                                        "canonical_text": "secret dropped text must stay redacted",
                                    }
                                ],
                                "dropped_reason_counts": {"BUDGET": 1},
                                "selected_count": 1,
                                "dropped_count": 1,
                                "raw_text_included": False,
                            }
                        },
                        "evidence": [],
                        "reply_text": "We decided to ship Friday.",
                        "defect_tags": [],
                        "blocking_defect_tags": [],
                    }
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        summary_path.write_text(
            json.dumps(
                {
                    "cases": 1,
                    "service_decision_accuracy": 1.0,
                    "model_verified_ok_rate": 1.0,
                    "model_decision_accuracy": 1.0,
                    "latency_ms": {"memory_p95": 1.0, "model_p95": 1.0, "total_p95": 2.0},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        gate_path.write_text(
            json.dumps(
                {
                    "safety_verdict": "PASS",
                    "human_quality_verdict": "PASS",
                    "decision": "PASS",
                    "quality": {
                        "defect_case_count": 0,
                        "blocking_defect_cases": 0,
                        "top_failure_examples": [],
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "build_responder_eval_readout.py",
                "--records",
                str(records_path),
                "--summary",
                str(summary_path),
                "--acceptance-gate",
                str(gate_path),
                "--out",
                str(out_path),
                "--max-cases",
                "4",
            ],
        )
        assert module.main() == 0

        text = out_path.read_text(encoding="utf-8")
        assert "## Q/A Audit Table" in text
        assert "## Top Failure Examples" in text
        assert "## Retrieval Diagnostics Summary" in text
        assert "selected_evidence" in text
        assert "mem_selected_1 [core, 0.91]" in text
        assert "dropped_reason_counts: `BUDGET=1`" in text
        assert "mem_dropped_1 [BUDGET, 0.44]" in text
        assert "- none" in text
        assert "secret selected text must stay redacted" not in text
        assert "secret dropped text must stay redacted" not in text
    finally:
        sys.modules.pop("build_responder_eval_readout", None)


def test_retrieval_diagnostics_summary_tolerates_malformed_counters() -> None:
    module = _load_module()
    try:
        cases, selected_total, dropped_total, reason_counts = module._retrieval_diagnostics_summary(
            [
                {
                    "retrieval": {
                        "retrieval_diagnostics": {
                            "selected": "bad",
                            "dropped": 7,
                            "selected_count": "oops",
                            "dropped_count": None,
                            "dropped_reason_counts": {" BUDGET ": "4", "OTHER": -2, "": 5},
                        }
                    }
                },
                {
                    "retrieval": {
                        "retrieval_diagnostics": {
                            "selected": [{"atom_id": "a1", "section": "core"}],
                            "dropped": [{"atom_id": "a2", "reason_code": "BUDGET"}],
                            "selected_count": 0,
                            "dropped_count": "3",
                            "dropped_reason_counts": {"BUDGET": "nan"},
                        }
                    }
                },
            ]
        )
        assert cases == 2
        assert selected_total == 1
        assert dropped_total == 3
        assert reason_counts == {"BUDGET": 4, "OTHER": 0}
    finally:
        sys.modules.pop("build_responder_eval_readout", None)


def test_readout_case_audit_tolerates_malformed_diagnostics_arrays(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    try:
        records_path = tmp_path / "records.json"
        summary_path = tmp_path / "summary.json"
        out_path = tmp_path / "human_readout.md"

        records_path.write_text(
            json.dumps(
                [
                    {
                        "case": {
                            "case_id": "tc_malformed",
                            "case_type": "supported_recall",
                            "fixture_family": "supported_recall",
                            "query": "What did we decide about the blocker?",
                            "expected_decision": "PASS",
                        },
                        "service_decision": "PASS",
                        "verification": {"ok": True, "reasons": []},
                        "latency_ms": {"memory_ms": 1.0, "model_ms": 1.0, "total_ms": 2.0},
                        "retrieval": {
                            "retrieval_diagnostics": {
                                "selected": 1,
                                "dropped": {"bad": "shape"},
                                "dropped_reason_counts": {"BUDGET": 2},
                            }
                        },
                        "evidence": [],
                        "reply_text": "We kept the blocker in the first milestone.",
                        "defect_tags": [],
                        "blocking_defect_tags": [],
                    }
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        summary_path.write_text(
            json.dumps(
                {
                    "cases": 1,
                    "service_decision_accuracy": 1.0,
                    "model_verified_ok_rate": 1.0,
                    "model_decision_accuracy": 1.0,
                    "latency_ms": {"memory_p95": 1.0, "model_p95": 1.0, "total_p95": 2.0},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "build_responder_eval_readout.py",
                "--records",
                str(records_path),
                "--summary",
                str(summary_path),
                "--out",
                str(out_path),
                "--max-cases",
                "4",
            ],
        )
        assert module.main() == 0

        text = out_path.read_text(encoding="utf-8")
        assert "### tc_malformed" in text
        assert "- selected_evidence: `(none)`" in text
        assert "- dropped_reason_counts: `BUDGET=2`" in text
        assert "- dropped_examples: `(none)`" in text
    finally:
        sys.modules.pop("build_responder_eval_readout", None)
