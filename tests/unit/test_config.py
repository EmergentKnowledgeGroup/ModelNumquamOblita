from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.config import active_efficiency_policy, default_config, load_config


def test_default_config_matches_locked_policy() -> None:
    """Defaults must reflect locked architecture decisions."""

    cfg = default_config()
    assert cfg.decay.half_life_days == 180
    assert cfg.runtime.allow_autonomous_destructive_mutation is False
    assert cfg.runtime.require_uncertainty_citations is True
    assert cfg.efficiency.enabled is False
    assert cfg.efficiency.fanout_hard_cap == 24
    assert cfg.efficiency.fanout_p95_soft_cap == 24


def test_load_config_overrides_nested_values(tmp_path: Path) -> None:
    """Nested JSON values should override corresponding default fields."""

    payload = {
        "retrieval": {
            "top_k_lexical": 12,
            "rerank_limit": 20,
            "router": {"procedural": {"semantic_scale": 0.7}},
            "bm25": {"k1": 1.8},
            "rrf": {"semantic_weight": 1.2},
            "pack": {"core_limit": 4},
            "cache": {"fail_closed_on_uncertain_continuity_scope": False},
        },
        "gate": {"abstain_threshold": 0.7},
        "runtime": {"retrieval": {"ltm_max_passes": 3, "prewarm_caches": False}},
        "efficiency": {
            "enabled": True,
            "fanout_hard_cap": 16,
            "fanout_p95_soft_cap": 32,
            "context_token_budget": 2200,
            "early_stop_min_evidence": 2,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.retrieval.top_k_lexical == 12
    assert cfg.retrieval.rerank_limit == 20
    assert cfg.retrieval.router.procedural.semantic_scale == pytest.approx(0.7)
    assert cfg.retrieval.bm25.k1 == pytest.approx(1.8)
    assert cfg.retrieval.rrf.semantic_weight == pytest.approx(1.2)
    assert cfg.retrieval.pack.core_limit == 4
    assert cfg.retrieval.cache.fail_closed_on_uncertain_continuity_scope is False
    assert cfg.gate.abstain_threshold == pytest.approx(0.7)
    assert cfg.runtime.retrieval.ltm_max_passes == 3
    assert cfg.runtime.retrieval.prewarm_caches is False
    assert cfg.efficiency.enabled is True
    assert cfg.efficiency.fanout_hard_cap == 16
    assert cfg.efficiency.fanout_p95_soft_cap == 32
    assert cfg.efficiency.context_token_budget == 2200
    assert cfg.efficiency.early_stop_min_evidence == 2


def test_load_config_validation_errors(tmp_path: Path) -> None:
    """Invalid payload shapes and missing files should fail with clear errors."""

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="config payload must be a JSON object"):
        load_config(bad)
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.json")


def test_load_config_strict_rejects_unknown_keys(tmp_path: Path) -> None:
    """Strict mode should reject unknown keys to catch typoed config fields."""

    payload = {"retrieval": {"top_k_lexical": 12}, "retreival": {"rerank_limit": 20}}
    path = tmp_path / "strict.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(KeyError, match="unknown config key: retreival"):
        load_config(path, strict=True)


def test_load_config_validates_efficiency_bounds(tmp_path: Path) -> None:
    """Efficiency knobs should fail closed on invalid bounds."""

    payload = {
        "efficiency": {
            "fanout_hard_cap": 64,
            "fanout_p95_soft_cap": 16,
        }
    }
    path = tmp_path / "invalid_efficiency.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"fanout_p95_soft_cap must be >= efficiency\.fanout_hard_cap"):
        load_config(path)


def test_active_efficiency_policy_rolls_back_to_defaults_when_disabled(tmp_path: Path) -> None:
    payload = {
        "efficiency": {
            "enabled": False,
            "fanout_hard_cap": 8,
            "fanout_p95_soft_cap": 12,
            "context_token_budget": 1000,
            "early_stop_min_evidence": 4,
        }
    }
    path = tmp_path / "rollback.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    cfg = load_config(path)
    effective = active_efficiency_policy(cfg)
    defaults = default_config().efficiency
    assert effective.enabled is defaults.enabled
    assert effective.fanout_hard_cap == defaults.fanout_hard_cap
    assert effective.fanout_p95_soft_cap == defaults.fanout_p95_soft_cap
    assert effective.context_token_budget == defaults.context_token_budget
    assert effective.early_stop_min_evidence == defaults.early_stop_min_evidence


def test_load_config_rejects_non_typed_efficiency_values(tmp_path: Path) -> None:
    payload = {
        "efficiency": {
            "enabled": "false",
            "fanout_hard_cap": "24",
        }
    }
    path = tmp_path / "bad_types.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TypeError, match="efficiency.enabled must be bool"):
        load_config(path)


def test_load_config_validates_nested_retrieval_and_runtime_bounds(tmp_path: Path) -> None:
    payload = {
        "retrieval": {
            "bm25": {"posting_cutoff_fraction": 1.2},
        },
        "runtime": {
            "retrieval": {"prewarm_caches": "false"},
        },
    }
    path = tmp_path / "bad_nested.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"retrieval\.bm25\.posting_cutoff_fraction must be <= 1.0"):
        load_config(path)

    payload["retrieval"]["bm25"]["posting_cutoff_fraction"] = 0.35
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TypeError, match=r"runtime\.retrieval\.prewarm_caches must be bool"):
        load_config(path)

    payload["runtime"]["retrieval"]["prewarm_caches"] = False
    payload["retrieval"]["bm25"]["posting_cutoff_fraction"] = float("nan")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"retrieval\.bm25\.posting_cutoff_fraction must be a finite float"):
        load_config(path)

    payload["retrieval"]["bm25"]["posting_cutoff_fraction"] = float("inf")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"retrieval\.bm25\.posting_cutoff_fraction must be a finite float"):
        load_config(path)

    payload["retrieval"]["bm25"]["posting_cutoff_fraction"] = 0.35
    payload["retrieval"]["router"] = "bad"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TypeError, match=r"retrieval\.router must be RetrievalRouterPolicy"):
        load_config(path)
