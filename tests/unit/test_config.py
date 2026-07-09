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
    assert cfg.provisional_memory.enabled is False
    assert cfg.provisional_memory.proposal_capture_enabled is False
    assert cfg.provisional_memory.default_sensitivity == "balanced"
    assert cfg.provisional_memory.inactivity_gap_seconds == 300
    assert cfg.provisional_memory.review_worthiness.fact_min_score > 0.0
    assert cfg.provisional_memory.near_duplicate.enabled is True
    assert cfg.retrieval_feedback.enabled is True
    assert cfg.retrieval_feedback.max_entries == 2000
    assert cfg.history_surfaces.enabled is True
    assert cfg.history_surfaces.max_episode_entries == 40
    assert cfg.continuity_adds.enabled is True
    assert cfg.continuity_adds.action_log_max_entries == 500
    assert cfg.retrieval.ann_sidecar.enabled is False
    assert cfg.retrieval.raw_context_sidecar.write_enabled is True
    assert cfg.retrieval.raw_context_sidecar.read_enabled is True
    assert cfg.retrieval.raw_context_sidecar.max_turns == 3
    assert cfg.retrieval.ann_sidecar.embedding_backend == "hashed-simhash-sqlite"
    assert cfg.retrieval.derived_helpers.source_projection.enabled is False
    assert cfg.retrieval.derived_helpers.temporal_lift.enabled is False
    assert cfg.retrieval.derived_helpers.cross_encoder_reranker.enabled is False
    assert cfg.retrieval.derived_helpers.update_family_resolver.enabled is False
    assert cfg.retrieval.derived_helpers.observation_projection.enabled is False
    assert cfg.efficiency.enabled is False
    assert cfg.efficiency.fanout_hard_cap == 24
    assert cfg.efficiency.fanout_p95_soft_cap == 24
    assert cfg.work_session_scratchpad.enabled is True
    assert cfg.work_session_scratchpad.inject_enabled is True
    assert cfg.work_session_scratchpad.resume_injection_enabled is True
    assert cfg.work_session_scratchpad.diagnostics_enabled is False
    assert cfg.work_session_scratchpad.max_entries_per_scope == 200
    assert cfg.work_session_scratchpad.max_injected_items == 8
    assert cfg.work_session_scratchpad.max_injected_chars == 2400
    assert cfg.work_session_scratchpad.max_raw_ref_bytes == 2_000_000
    assert cfg.work_session_scratchpad.retention_days == 14
    assert cfg.work_session_scratchpad.min_replaceability_score == pytest.approx(0.70)


def test_load_config_overrides_nested_values(tmp_path: Path) -> None:
    """Nested JSON values should override corresponding default fields."""

    payload = {
        "retrieval": {
            "top_k_lexical": 12,
            "rerank_limit": 20,
            "router": {"procedural": {"semantic_scale": 0.7}},
            "ann_sidecar": {
                "enabled": True,
                "top_k_ann": 12,
                "candidate_cap_ratio": 0.25,
                "candidate_cap_floor": 3,
                "max_latency_ms": 35.0,
                "embedding_store_path": "/tmp/mno.ann.sqlite3",
            },
            "raw_context_sidecar": {
                "write_enabled": False,
                "read_enabled": True,
                "neighbor_turns": 2,
                "max_turns": 5,
                "max_chars": 900,
            },
            "derived_helpers": {
                "source_projection": {
                    "enabled": True,
                    "per_source_fanout_cap": 5,
                    "per_query_contribution_cap": 10,
                },
                "temporal_lift": {
                    "enabled": True,
                    "score_cap": 0.18,
                },
                "cross_encoder_reranker": {
                    "enabled": True,
                    "top_n": 20,
                    "top_m": 8,
                    "max_latency_ms": 80.0,
                },
                "update_family_resolver": {
                    "enabled": True,
                    "family_scan_limit": 18,
                },
                "observation_projection": {
                    "enabled": True,
                    "per_source_fanout_cap": 3,
                    "per_query_contribution_cap": 6,
                },
            },
            "bm25": {"k1": 1.8},
            "rrf": {"semantic_weight": 1.2},
            "pack": {"core_limit": 4},
            "cache": {"fail_closed_on_uncertain_continuity_scope": False},
        },
        "gate": {"abstain_threshold": 0.7},
        "runtime": {"retrieval": {"ltm_max_passes": 3, "prewarm_caches": False}},
        "provisional_memory": {
            "enabled": True,
            "retrieval_enabled": True,
            "stm_sweep_enabled": True,
            "proposal_capture_enabled": True,
            "default_sensitivity": "eager",
            "inactivity_gap_seconds": 420,
            "review_worthiness": {"fact_min_score": 0.44},
            "near_duplicate": {"similarity_threshold": 0.58},
            "balanced": {"max_auto_writes_per_turn": 3},
        },
        "retrieval_feedback": {
            "enabled": True,
            "max_entries": 128,
            "max_query_chars": 96,
        },
        "history_surfaces": {
            "enabled": False,
            "max_episode_entries": 12,
            "max_provisional_events": 24,
        },
        "continuity_adds": {
            "enabled": True,
            "action_log_enabled": True,
            "action_log_max_entries": 64,
            "wake_up_pack_enabled": True,
            "resume_pack_enabled": False,
            "pinned_preferences_enabled": True,
        },
        "efficiency": {
            "enabled": True,
            "fanout_hard_cap": 16,
            "fanout_p95_soft_cap": 32,
            "context_token_budget": 2200,
            "early_stop_min_evidence": 2,
        },
        "work_session_scratchpad": {
            "enabled": True,
            "inject_enabled": True,
            "resume_injection_enabled": True,
            "diagnostics_enabled": True,
            "max_entries_per_scope": 64,
            "max_injected_items": 4,
            "max_injected_chars": 1200,
            "max_raw_ref_bytes": 4096,
            "retention_days": 7,
            "min_replaceability_score": 0.82,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.retrieval.top_k_lexical == 12
    assert cfg.retrieval.rerank_limit == 20
    assert cfg.retrieval.router.procedural.semantic_scale == pytest.approx(0.7)
    assert cfg.retrieval.ann_sidecar.enabled is True
    assert cfg.retrieval.ann_sidecar.top_k_ann == 12
    assert cfg.retrieval.ann_sidecar.candidate_cap_ratio == pytest.approx(0.25)
    assert cfg.retrieval.ann_sidecar.candidate_cap_floor == 3
    assert cfg.retrieval.ann_sidecar.max_latency_ms == pytest.approx(35.0)
    assert cfg.retrieval.ann_sidecar.embedding_store_path == "/tmp/mno.ann.sqlite3"
    assert cfg.retrieval.raw_context_sidecar.write_enabled is False
    assert cfg.retrieval.raw_context_sidecar.read_enabled is True
    assert cfg.retrieval.raw_context_sidecar.neighbor_turns == 2
    assert cfg.retrieval.raw_context_sidecar.max_turns == 5
    assert cfg.retrieval.raw_context_sidecar.max_chars == 900
    assert cfg.retrieval.derived_helpers.source_projection.enabled is True
    assert cfg.retrieval.derived_helpers.source_projection.per_source_fanout_cap == 5
    assert cfg.retrieval.derived_helpers.source_projection.per_query_contribution_cap == 10
    assert cfg.retrieval.derived_helpers.temporal_lift.enabled is True
    assert cfg.retrieval.derived_helpers.temporal_lift.score_cap == pytest.approx(0.18)
    assert cfg.retrieval.derived_helpers.cross_encoder_reranker.enabled is True
    assert cfg.retrieval.derived_helpers.cross_encoder_reranker.top_n == 20
    assert cfg.retrieval.derived_helpers.cross_encoder_reranker.top_m == 8
    assert cfg.retrieval.derived_helpers.cross_encoder_reranker.max_latency_ms == pytest.approx(80.0)
    assert cfg.retrieval.derived_helpers.update_family_resolver.enabled is True
    assert cfg.retrieval.derived_helpers.update_family_resolver.family_scan_limit == 18
    assert cfg.retrieval.derived_helpers.observation_projection.enabled is True
    assert cfg.retrieval.derived_helpers.observation_projection.per_source_fanout_cap == 3
    assert cfg.retrieval.derived_helpers.observation_projection.per_query_contribution_cap == 6
    assert cfg.retrieval.bm25.k1 == pytest.approx(1.8)
    assert cfg.retrieval.rrf.semantic_weight == pytest.approx(1.2)
    assert cfg.retrieval.pack.core_limit == 4
    assert cfg.retrieval.cache.fail_closed_on_uncertain_continuity_scope is False
    assert cfg.gate.abstain_threshold == pytest.approx(0.7)
    assert cfg.runtime.retrieval.ltm_max_passes == 3
    assert cfg.runtime.retrieval.prewarm_caches is False
    assert cfg.provisional_memory.enabled is True
    assert cfg.provisional_memory.retrieval_enabled is True
    assert cfg.provisional_memory.stm_sweep_enabled is True
    assert cfg.provisional_memory.proposal_capture_enabled is True
    assert cfg.provisional_memory.default_sensitivity == "eager"
    assert cfg.provisional_memory.inactivity_gap_seconds == 420
    assert cfg.provisional_memory.review_worthiness.fact_min_score == pytest.approx(0.44)
    assert cfg.provisional_memory.near_duplicate.similarity_threshold == pytest.approx(0.58)
    assert cfg.provisional_memory.balanced.max_auto_writes_per_turn == 3
    assert cfg.retrieval_feedback.enabled is True
    assert cfg.retrieval_feedback.max_entries == 128
    assert cfg.retrieval_feedback.max_query_chars == 96
    assert cfg.history_surfaces.enabled is False
    assert cfg.history_surfaces.max_episode_entries == 12
    assert cfg.history_surfaces.max_provisional_events == 24
    assert cfg.continuity_adds.enabled is True
    assert cfg.continuity_adds.action_log_max_entries == 64
    assert cfg.continuity_adds.resume_pack_enabled is False
    assert cfg.efficiency.enabled is True
    assert cfg.efficiency.fanout_hard_cap == 16
    assert cfg.efficiency.fanout_p95_soft_cap == 32
    assert cfg.efficiency.context_token_budget == 2200
    assert cfg.efficiency.early_stop_min_evidence == 2
    assert cfg.work_session_scratchpad.enabled is True
    assert cfg.work_session_scratchpad.inject_enabled is True
    assert cfg.work_session_scratchpad.resume_injection_enabled is True
    assert cfg.work_session_scratchpad.diagnostics_enabled is True
    assert cfg.work_session_scratchpad.max_entries_per_scope == 64
    assert cfg.work_session_scratchpad.max_injected_items == 4
    assert cfg.work_session_scratchpad.max_injected_chars == 1200
    assert cfg.work_session_scratchpad.max_raw_ref_bytes == 4096
    assert cfg.work_session_scratchpad.retention_days == 7
    assert cfg.work_session_scratchpad.min_replaceability_score == pytest.approx(0.82)


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


def test_load_config_validates_derived_helper_bounds(tmp_path: Path) -> None:
    payload = {
        "retrieval": {
            "bm25": {"posting_cutoff_fraction": 0.35},
            "derived_helpers": {
                "cross_encoder_reranker": {
                    "enabled": True,
                    "top_n": 8,
                    "top_m": 12,
                }
            }
        }
    }
    path = tmp_path / "bad_helpers.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match=r"retrieval\.derived_helpers\.cross_encoder_reranker\.top_m must be <= retrieval\.derived_helpers\.cross_encoder_reranker\.top_n",
    ):
        load_config(path)

    payload["retrieval"]["derived_helpers"]["cross_encoder_reranker"]["top_m"] = 6
    payload["retrieval"]["derived_helpers"]["temporal_lift"] = {"score_cap": 1.2}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"retrieval\.derived_helpers\.temporal_lift\.score_cap must be <= 1.0"):
        load_config(path)

    payload["retrieval"]["bm25"]["posting_cutoff_fraction"] = 0.35
    payload["retrieval"]["router"] = "bad"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TypeError, match=r"retrieval\.router must be RetrievalRouterPolicy"):
        load_config(path)

    payload["retrieval"]["router"] = {"mixed": {"candidate_cap_ratio": 1.0}}
    payload["retrieval"]["ann_sidecar"] = {"candidate_cap_ratio": 1.2}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"retrieval\.ann_sidecar\.candidate_cap_ratio must be <= 1.0"):
        load_config(path)


def test_load_config_validates_provisional_memory_bounds(tmp_path: Path) -> None:
    payload = {
        "provisional_memory": {
            "default_sensitivity": "wild",
        }
    }
    path = tmp_path / "bad_provisional.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"provisional_memory\.default_sensitivity must be one of"):
        load_config(path)

    payload["provisional_memory"]["default_sensitivity"] = "balanced"
    payload["provisional_memory"]["inactivity_gap_seconds"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"provisional_memory\.inactivity_gap_seconds must be >= 1"):
        load_config(path)

    payload["provisional_memory"]["inactivity_gap_seconds"] = 300
    payload["provisional_memory"]["balanced"] = {"max_auto_writes_per_turn": 0}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"provisional_memory\.balanced\.max_auto_writes_per_turn must be >= 1"):
        load_config(path)

    payload["provisional_memory"]["balanced"] = {"max_auto_writes_per_turn": 2}
    payload["provisional_memory"]["review_worthiness"] = {"fact_min_score": 1.2}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"provisional_memory\.review_worthiness\.fact_min_score must be <= 1.0"):
        load_config(path)

    payload["provisional_memory"]["review_worthiness"] = {"fact_min_score": 0.7}
    payload["provisional_memory"]["near_duplicate"] = {"similarity_threshold": 0.0}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"provisional_memory\.near_duplicate\.similarity_threshold must be > 0.0"):
        load_config(path)


def test_load_config_validates_retrieval_feedback_bounds(tmp_path: Path) -> None:
    payload = {
        "retrieval_feedback": {
            "enabled": True,
            "max_entries": 0,
        }
    }
    path = tmp_path / "bad_feedback.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"retrieval_feedback\.max_entries must be >= 1"):
        load_config(path)

    payload["retrieval_feedback"]["max_entries"] = 64
    payload["retrieval_feedback"]["max_query_chars"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"retrieval_feedback\.max_query_chars must be >= 1"):
        load_config(path)


def test_load_config_validates_history_surface_bounds(tmp_path: Path) -> None:
    payload = {
        "history_surfaces": {
            "enabled": True,
            "max_episode_entries": 0,
        }
    }
    path = tmp_path / "bad_history_surfaces.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"history_surfaces\.max_episode_entries must be >= 1"):
        load_config(path)

    payload["history_surfaces"]["max_episode_entries"] = 12
    payload["history_surfaces"]["max_provisional_events"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"history_surfaces\.max_provisional_events must be >= 1"):
        load_config(path)


def test_load_config_validates_continuity_adds_bounds(tmp_path: Path) -> None:
    payload = {
        "continuity_adds": {
            "enabled": True,
            "action_log_max_entries": 0,
        }
    }
    path = tmp_path / "bad_continuity_adds.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"continuity_adds\.action_log_max_entries must be >= 1"):
        load_config(path)


def test_load_config_validates_work_session_scratchpad_bounds(tmp_path: Path) -> None:
    payload = {
        "work_session_scratchpad": {
            "enabled": "false",
        }
    }
    path = tmp_path / "bad_scratchpad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TypeError, match=r"work_session_scratchpad\.enabled must be bool"):
        load_config(path)

    payload["work_session_scratchpad"] = {
        "enabled": False,
        "max_injected_items": 0,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"work_session_scratchpad\.max_injected_items must be >= 1"):
        load_config(path)

    payload["work_session_scratchpad"] = {
        "min_replaceability_score": 1.2,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"work_session_scratchpad\.min_replaceability_score must be <= 1.0"):
        load_config(path)
