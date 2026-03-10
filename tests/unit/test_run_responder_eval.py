from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

from engine.config import default_config


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "run_responder_eval.py"
    spec = importlib.util.spec_from_file_location("run_responder_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_responder_eval"] = module
    spec.loader.exec_module(module)
    return module


def test_acceptance_gate_blocks_precision_junk_and_conflict_coverage() -> None:
    module = _load_module()
    try:
        args = SimpleNamespace(
            min_decision_accuracy=0.90,
            min_citation_hit_rate=0.50,
            min_retrieval_hit_rate=0.50,
            min_abstain_precision=0.60,
            max_false_memory_rate=0.0,
            max_routine_over_recall_rate=0.0,
            min_relevance_aligned_hit_rate=0.95,
            max_p95_retrieved_atoms=24.0,
            min_evidence_precision_at_k=0.70,
            max_junk_rate_at_k=0.25,
            min_conflict_coverage=1.0,
            max_memory_p95_ms=2000.0,
            max_model_p95_ms=15000.0,
            max_total_p95_ms=18000.0,
            max_blocking_defect_cases=0,
        )
        summary = {
            "decision_accuracy": 1.0,
            "citation_hit_rate": 1.0,
            "retrieval_hit_rate": 1.0,
            "abstain_precision": 1.0,
            "false_memory_rate": 0.0,
            "routine_over_recall_rate": 0.0,
            "latency_ms": {"memory_p95": 1.0, "model_p95": 1.0, "total_p95": 1.0},
            "retrieval": {
                "supported_non_routine_alignment_missing_cases": 0,
                "supported_non_routine_relevance_aligned_hit_rate": 1.0,
                "supported_non_routine_p95_retrieved_atoms": 1.0,
                "evidence_precision_at_k": 0.4,
                "junk_rate_at_k": 0.6,
                "conflict_coverage": 0.0,
            },
        }

        gate = module._build_acceptance_gate(summary, [], args)

        assert str(gate.get("safety_verdict") or "") == "PASS"
        assert str(gate.get("human_quality_verdict") or "") == "FAIL"
        failures = set(gate.get("human_quality_failures") or [])
        assert "evidence_precision_at_k_below_floor" in failures
        assert "junk_rate_at_k_exceeded" in failures
        assert "conflict_coverage_below_floor" in failures

        metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
        assert float(metrics.get("evidence_precision_at_k") or 0.0) == 0.4
        assert float(metrics.get("junk_rate_at_k") or 0.0) == 0.6
        assert float(metrics.get("conflict_coverage") or 0.0) == 0.0
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_required_efficiency_metrics_detect_missing_and_non_finite() -> None:
    module = _load_module()
    try:
        metrics, failures = module._required_efficiency_metrics(
            {
                "latency_p50_ms": 120.0,
                "latency_p95_ms": float("nan"),
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
                    # conflict_coverage intentionally omitted
                },
            }
        )
        assert float(metrics.get("tokens_total_avg") or 0.0) == 15.0
        assert "latency_p95_ms_non_finite" in failures
        assert "conflict_coverage_missing" in failures
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_required_efficiency_metrics_rejects_present_non_numeric() -> None:
    module = _load_module()
    try:
        _metrics, failures = module._required_efficiency_metrics(
            {
                "latency_p50_ms": "bad",
                "latency_p95_ms": 200.0,
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
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_apply_efficiency_fanout_cap_rolls_back_when_disabled() -> None:
    module = _load_module()
    try:
        capped = module._apply_efficiency_fanout_cap(
            ["a1", "a2", "a3"],
            enabled=False,
            hard_cap=1,
        )
        assert capped == ["a1", "a2", "a3"]
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_apply_efficiency_fanout_cap_enforces_cap_when_enabled() -> None:
    module = _load_module()
    try:
        capped = module._apply_efficiency_fanout_cap(
            ["a1", "a2", "a3"],
            enabled=True,
            hard_cap=2,
        )
        assert capped == ["a1", "a2"]
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_apply_efficiency_fanout_cap_disabled_is_true_noop_on_raw_ids() -> None:
    module = _load_module()
    try:
        raw_ids = ["  a1  ", "", None, "a2"]
        capped = module._apply_efficiency_fanout_cap(
            raw_ids,
            enabled=False,
            hard_cap=1,
        )
        assert capped == raw_ids
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_sanitize_retrieval_diagnostics_tolerates_malformed_payloads() -> None:
    module = _load_module()
    try:
        payload = module._sanitize_retrieval_diagnostics(
            {
                "selected": 1,
                "dropped": "bad",
                "dropped_reason_counts": "oops",
                "selected_count": "nan",
                "dropped_count": None,
            }
        )
        assert payload["selected"] == []
        assert payload["dropped"] == []
        assert payload["dropped_reason_counts"] == {}
        assert payload["selected_count"] == 0
        assert payload["dropped_count"] == 0
        assert payload["raw_text_included"] is False
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_sanitize_retrieval_diagnostics_clamps_non_finite_and_negative_values() -> None:
    module = _load_module()
    try:
        payload = module._sanitize_retrieval_diagnostics(
            {
                "selected": [{"atom_id": "a1", "section": "core", "score": "nan"}],
                "dropped": [{"atom_id": "a2", "reason_code": "BUDGET", "score": -5}],
                "dropped_reason_counts": {" BUDGET ": -3, "BUDGET": 4, "OTHER": "2"},
                "selected_count": -1,
                "dropped_count": 1,
            }
        )
        assert payload["selected"] == [{"atom_id": "a1", "section": "core", "score": 0.0}]
        assert payload["dropped"] == [{"atom_id": "a2", "reason_code": "BUDGET"}]
        assert payload["dropped_reason_counts"] == {"BUDGET": 4, "OTHER": 2}
        assert payload["selected_count"] == 1
        assert payload["dropped_count"] == 1
    finally:
        sys.modules.pop("run_responder_eval", None)


def test_main_passes_loaded_config_to_retriever_and_runtime(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    try:
        cfg = default_config()
        captured: dict[str, object] = {}
        memories_path = tmp_path / "memories.json"
        config_path = tmp_path / "config.json"
        out_dir = tmp_path / "out"
        memories_path.write_text("{}", encoding="utf-8")
        config_path.write_text("{}", encoding="utf-8")

        class FakeStore:
            def list_atoms(self) -> list[object]:
                return []

        class FakeRetriever:
            def __init__(self, store, *, config=None) -> None:
                captured["retriever_store"] = store
                captured["retriever_config"] = config
                self.store = store
                self.config = config

        class FakeRuntime:
            def __init__(self, *, retriever, verifier, continuity_store, config=None, **kwargs) -> None:
                _ = verifier, continuity_store, kwargs
                captured["runtime_retriever"] = retriever
                captured["runtime_config"] = config

            def close(self) -> None:
                return None

        monkeypatch.setattr(module, "_open_store", lambda path: (FakeStore(), False))
        monkeypatch.setattr(module, "load_config", lambda path: cfg)
        monkeypatch.setattr(module, "active_efficiency_policy", lambda loaded: loaded.efficiency)
        monkeypatch.setattr(module, "plan_live_eval_workload", lambda **kwargs: SimpleNamespace(effective_cases=0))
        monkeypatch.setattr(module, "generate_truthset", lambda *args, **kwargs: [])
        monkeypatch.setattr(module, "write_truthset_jsonl", lambda *args, **kwargs: None)
        monkeypatch.setattr(module, "build_provider", lambda *args, **kwargs: SimpleNamespace())
        monkeypatch.setattr(module, "MemoryRetriever", FakeRetriever)
        monkeypatch.setattr(module, "RuntimeSession", FakeRuntime)
        monkeypatch.setattr(
            module.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_responder_eval.py",
                "--memories",
                str(memories_path),
                "--config",
                str(config_path),
                "--out-dir",
                str(out_dir),
                "--requested-cases",
                "0",
                "--scan-budget",
                "0",
            ],
        )

        assert module.main() == 0
        assert captured["retriever_config"] is cfg
        assert captured["runtime_config"] is cfg
    finally:
        sys.modules.pop("run_responder_eval", None)
