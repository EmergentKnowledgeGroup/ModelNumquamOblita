from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class GateThresholds:
    """Thresholds used by write and response gates."""

    min_trust: float = 0.35
    min_salience: float = 0.25
    min_identity_relevance: float = 0.20
    add_threshold: float = 0.60
    stage_a_add_floor: float = 0.62
    update_threshold: float = 0.50
    max_confidence_without_recurrence: float = 0.72
    abstain_threshold: float = 0.55


@dataclass(slots=True)
class RetrievalProfilePolicy:
    """Profile-specific router scales and candidate bounds."""

    lexical_scale: float = 1.0
    semantic_scale: float = 1.0
    temporal_scale: float = 1.0
    graph_scale: float = 1.0
    candidate_pool_floor: int = 128
    candidate_cap_ratio: float = 1.0
    candidate_cap_floor: int = 16


@dataclass(slots=True)
class RetrievalRouterPolicy:
    """Typed router knobs for profile shaping."""

    lexical_floor_min: int = 4
    semantic_floor_min: int = 4
    temporal_floor_min: int = 2
    graph_floor_min: int = 2
    lexical_floor_divisor: int = 3
    semantic_floor_divisor: int = 3
    temporal_floor_divisor: int = 4
    graph_floor_divisor: int = 4
    max_candidate_pool_floor: int = 192
    episode_heavy: RetrievalProfilePolicy = field(
        default_factory=lambda: RetrievalProfilePolicy(
            graph_scale=0.80,
            candidate_pool_floor=128,
            candidate_cap_ratio=1.0,
            candidate_cap_floor=16,
        )
    )
    preference_relational: RetrievalProfilePolicy = field(
        default_factory=lambda: RetrievalProfilePolicy(
            temporal_scale=0.60,
            candidate_pool_floor=112,
            candidate_cap_ratio=0.75,
            candidate_cap_floor=24,
        )
    )
    procedural: RetrievalProfilePolicy = field(
        default_factory=lambda: RetrievalProfilePolicy(
            semantic_scale=0.85,
            temporal_scale=0.55,
            graph_scale=0.55,
            candidate_pool_floor=96,
            candidate_cap_ratio=0.50,
            candidate_cap_floor=16,
        )
    )
    factual: RetrievalProfilePolicy = field(
        default_factory=lambda: RetrievalProfilePolicy(
            semantic_scale=0.90,
            temporal_scale=0.55,
            graph_scale=0.50,
            candidate_pool_floor=96,
            candidate_cap_ratio=0.50,
            candidate_cap_floor=16,
        )
    )
    mixed: RetrievalProfilePolicy = field(
        default_factory=lambda: RetrievalProfilePolicy(
            candidate_pool_floor=128,
            candidate_cap_ratio=1.0,
            candidate_cap_floor=16,
        )
    )


@dataclass(slots=True)
class RetrievalBm25Policy:
    """Typed BM25 admission and scoring knobs."""

    posting_cutoff_min: int = 64
    posting_cutoff_fraction: float = 0.35
    k1: float = 1.4
    b: float = 0.75
    relevance_floor_min: float = 0.05
    relevance_floor_fraction: float = 0.15


@dataclass(slots=True)
class RetrievalRrfPolicy:
    """Typed reciprocal-rank fusion weights."""

    rank_constant: float = 60.0
    lexical_weight: float = 1.00
    bm25_weight: float = 1.00
    semantic_weight: float = 0.95
    sequence_weight: float = 1.10
    quote_weight: float = 1.20
    temporal_weight: float = 0.60
    graph_weight: float = 0.75
    continuity_weight: float = 0.55
    fallback_channel_weight: float = 0.50


@dataclass(slots=True)
class RetrievalPackPolicy:
    """Typed evidence-pack quotas and fail-closed guards."""

    core_limit: int = 6
    context_limit: int = 8
    conflict_limit: int = 6
    continuity_limit: int = 6
    guarded_neighbor_scan_limit: int = 14
    guarded_extra_budget_min: int = 4
    guarded_extra_budget_max: int = 12
    guarded_extra_budget_ratio_divisor: int = 2


@dataclass(slots=True)
class RetrievalCachePolicy:
    """Fail-closed cache guard toggles."""

    fail_closed_on_uncertain_store_scope: bool = True
    fail_closed_on_uncertain_continuity_scope: bool = True


@dataclass(slots=True)
class RetrievalBudget:
    """Top-k and retrieval policy knobs used by retrieval."""

    top_k_lexical: int = 24
    top_k_vector: int = 24
    top_k_temporal: int = 16
    top_k_graph: int = 16
    rerank_limit: int = 48
    router: RetrievalRouterPolicy = field(default_factory=RetrievalRouterPolicy)
    bm25: RetrievalBm25Policy = field(default_factory=RetrievalBm25Policy)
    rrf: RetrievalRrfPolicy = field(default_factory=RetrievalRrfPolicy)
    pack: RetrievalPackPolicy = field(default_factory=RetrievalPackPolicy)
    cache: RetrievalCachePolicy = field(default_factory=RetrievalCachePolicy)


@dataclass(slots=True)
class DecayPolicy:
    """Controls salience decay and archival behavior."""

    half_life_days: int = 180
    minimum_salience: float = 0.05


@dataclass(slots=True)
class RuntimeRetrievalPolicy:
    """Typed runtime retrieval and routing thresholds."""

    ltm_multi_pass_enabled: bool = True
    ltm_max_passes: int = 2
    ltm_followup_min_match_max: float = 0.20
    ltm_followup_min_pack_confidence: float = 0.55
    ltm_followup_time_budget_ms: float = 450.0
    ltm_followup_max_query_tokens: int = 256
    episode_top_k: int = 2
    episode_min_score: float = 0.56
    episode_primary_min_score: float = 0.68
    episode_primary_min_cue_match: float = 0.24
    episode_primary_min_lexical: float = 0.34
    memory_signal_min_score: float = 0.34
    routine_hard_cap_enabled: bool = True
    min_query_match_max: float = 0.12
    min_query_match_mean: float = 0.08
    min_query_informative_overlap: float = 0.20
    min_query_token_hits: int = 2
    prewarm_caches: bool = True


@dataclass(slots=True)
class RuntimePolicy:
    """Safety and runtime behavior toggles."""

    require_uncertainty_citations: bool = True
    allow_autonomous_destructive_mutation: bool = False
    allow_raw_pii_storage: bool = True
    tombstone_retention_days: int = 30
    retrieval: RuntimeRetrievalPolicy = field(default_factory=RuntimeRetrievalPolicy)


@dataclass(slots=True)
class RuntimeEfficiencyPolicy:
    """Typed optimization knobs with fail-safe defaults."""

    enabled: bool = False
    fanout_hard_cap: int = 24
    fanout_p95_soft_cap: int = 24
    context_token_budget: int = 2800
    early_stop_min_evidence: int = 1
    cache_uncertainty_bypass: bool = True
    include_retry_tokens: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("efficiency.enabled must be bool")
        if not isinstance(self.cache_uncertainty_bypass, bool):
            raise TypeError("efficiency.cache_uncertainty_bypass must be bool")
        if not isinstance(self.include_retry_tokens, bool):
            raise TypeError("efficiency.include_retry_tokens must be bool")
        for key in ("fanout_hard_cap", "fanout_p95_soft_cap", "context_token_budget", "early_stop_min_evidence"):
            value = getattr(self, key)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"efficiency.{key} must be int")
        if self.fanout_hard_cap <= 0:
            raise ValueError("efficiency.fanout_hard_cap must be > 0")
        if self.fanout_hard_cap > 256:
            raise ValueError("efficiency.fanout_hard_cap must be <= 256")
        if self.fanout_p95_soft_cap <= 0:
            raise ValueError("efficiency.fanout_p95_soft_cap must be > 0")
        if self.fanout_p95_soft_cap > 512:
            raise ValueError("efficiency.fanout_p95_soft_cap must be <= 512")
        if self.fanout_p95_soft_cap < self.fanout_hard_cap:
            raise ValueError("efficiency.fanout_p95_soft_cap must be >= efficiency.fanout_hard_cap")
        if self.context_token_budget <= 0:
            raise ValueError("efficiency.context_token_budget must be > 0")
        if self.context_token_budget > 32000:
            raise ValueError("efficiency.context_token_budget must be <= 32000")
        if self.early_stop_min_evidence < 0:
            raise ValueError("efficiency.early_stop_min_evidence must be >= 0")
        if self.early_stop_min_evidence > 64:
            raise ValueError("efficiency.early_stop_min_evidence must be <= 64")


@dataclass(slots=True)
class NumquamOblitaConfig:
    """Top-level typed configuration model."""

    gate: GateThresholds = field(default_factory=GateThresholds)
    retrieval: RetrievalBudget = field(default_factory=RetrievalBudget)
    decay: DecayPolicy = field(default_factory=DecayPolicy)
    runtime: RuntimePolicy = field(default_factory=RuntimePolicy)
    efficiency: RuntimeEfficiencyPolicy = field(default_factory=RuntimeEfficiencyPolicy)

    def as_dict(self) -> dict[str, Any]:
        """Return config as a plain dictionary."""
        return asdict(self)


def default_config() -> NumquamOblitaConfig:
    """Return the baseline config with locked defaults."""

    cfg = NumquamOblitaConfig()
    _validate_config(cfg)
    return cfg


def active_efficiency_policy(cfg: NumquamOblitaConfig) -> RuntimeEfficiencyPolicy:
    """Return effective efficiency policy, with knob-off rollback to defaults."""

    effective = RuntimeEfficiencyPolicy(**asdict(cfg.efficiency))
    if not effective.enabled:
        return RuntimeEfficiencyPolicy()
    return effective


def _merge_dataclass(
    dc: Any,
    patch: dict[str, Any],
    *,
    strict: bool,
    path: str = "",
) -> Any:
    """Recursively merge dictionary values into nested dataclasses.

    When ``strict`` is true, unknown keys raise ``KeyError`` to catch typos.
    """

    for key, value in patch.items():
        if not hasattr(dc, key):
            if strict:
                full_key = f"{path}.{key}" if path else key
                raise KeyError(f"unknown config key: {full_key}")
            continue
        current = getattr(dc, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            child_path = f"{path}.{key}" if path else key
            _merge_dataclass(current, value, strict=strict, path=child_path)
        else:
            setattr(dc, key, value)
    return dc


def load_config(path: str | Path | None, *, strict: bool = False) -> NumquamOblitaConfig:
    """Load JSON config file and merge over defaults.

    Use ``strict=True`` to fail on unknown config keys.
    """

    cfg = default_config()
    if path is None:
        return cfg
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("config payload must be a JSON object")
    merged = _merge_dataclass(cfg, data, strict=strict)
    _validate_config(merged)
    return merged


def _validate_bool(name: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be bool")


def _validate_int(name: str, value: Any, *, min_value: int | None = None, max_value: int | None = None) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be int")
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}")


def _validate_float(name: str, value: Any, *, min_value: float | None = None, max_value: float | None = None) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be float")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be a finite float")
    if min_value is not None and numeric < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    if max_value is not None and numeric > max_value:
        raise ValueError(f"{name} must be <= {max_value}")


def _validate_profile_policy(name: str, profile: RetrievalProfilePolicy) -> None:
    if not isinstance(profile, RetrievalProfilePolicy):
        raise TypeError(f"{name} must be RetrievalProfilePolicy")
    _validate_float(f"{name}.lexical_scale", profile.lexical_scale, min_value=0.0, max_value=1.0)
    _validate_float(f"{name}.semantic_scale", profile.semantic_scale, min_value=0.0, max_value=1.0)
    _validate_float(f"{name}.temporal_scale", profile.temporal_scale, min_value=0.0, max_value=1.0)
    _validate_float(f"{name}.graph_scale", profile.graph_scale, min_value=0.0, max_value=1.0)
    _validate_int(f"{name}.candidate_pool_floor", profile.candidate_pool_floor, min_value=1, max_value=1024)
    _validate_float(f"{name}.candidate_cap_ratio", profile.candidate_cap_ratio, min_value=0.0, max_value=1.0)
    _validate_int(f"{name}.candidate_cap_floor", profile.candidate_cap_floor, min_value=1, max_value=1024)


def _validate_retrieval_config(retrieval: RetrievalBudget) -> None:
    if not isinstance(retrieval, RetrievalBudget):
        raise TypeError("retrieval must be RetrievalBudget")
    _validate_int("retrieval.top_k_lexical", retrieval.top_k_lexical, min_value=1, max_value=512)
    _validate_int("retrieval.top_k_vector", retrieval.top_k_vector, min_value=1, max_value=512)
    _validate_int("retrieval.top_k_temporal", retrieval.top_k_temporal, min_value=1, max_value=512)
    _validate_int("retrieval.top_k_graph", retrieval.top_k_graph, min_value=1, max_value=512)
    _validate_int("retrieval.rerank_limit", retrieval.rerank_limit, min_value=1, max_value=512)

    router = retrieval.router
    if not isinstance(router, RetrievalRouterPolicy):
        raise TypeError("retrieval.router must be RetrievalRouterPolicy")
    _validate_int("retrieval.router.lexical_floor_min", router.lexical_floor_min, min_value=1, max_value=256)
    _validate_int("retrieval.router.semantic_floor_min", router.semantic_floor_min, min_value=1, max_value=256)
    _validate_int("retrieval.router.temporal_floor_min", router.temporal_floor_min, min_value=1, max_value=256)
    _validate_int("retrieval.router.graph_floor_min", router.graph_floor_min, min_value=1, max_value=256)
    _validate_int("retrieval.router.lexical_floor_divisor", router.lexical_floor_divisor, min_value=1, max_value=64)
    _validate_int("retrieval.router.semantic_floor_divisor", router.semantic_floor_divisor, min_value=1, max_value=64)
    _validate_int("retrieval.router.temporal_floor_divisor", router.temporal_floor_divisor, min_value=1, max_value=64)
    _validate_int("retrieval.router.graph_floor_divisor", router.graph_floor_divisor, min_value=1, max_value=64)
    _validate_int("retrieval.router.max_candidate_pool_floor", router.max_candidate_pool_floor, min_value=1, max_value=2048)
    _validate_profile_policy("retrieval.router.episode_heavy", router.episode_heavy)
    _validate_profile_policy("retrieval.router.preference_relational", router.preference_relational)
    _validate_profile_policy("retrieval.router.procedural", router.procedural)
    _validate_profile_policy("retrieval.router.factual", router.factual)
    _validate_profile_policy("retrieval.router.mixed", router.mixed)

    bm25 = retrieval.bm25
    if not isinstance(bm25, RetrievalBm25Policy):
        raise TypeError("retrieval.bm25 must be RetrievalBm25Policy")
    _validate_int("retrieval.bm25.posting_cutoff_min", bm25.posting_cutoff_min, min_value=1, max_value=100000)
    _validate_float("retrieval.bm25.posting_cutoff_fraction", bm25.posting_cutoff_fraction, min_value=0.0, max_value=1.0)
    _validate_float("retrieval.bm25.k1", bm25.k1, min_value=0.0, max_value=4.0)
    _validate_float("retrieval.bm25.b", bm25.b, min_value=0.0, max_value=1.0)
    _validate_float("retrieval.bm25.relevance_floor_min", bm25.relevance_floor_min, min_value=0.0, max_value=1000.0)
    _validate_float(
        "retrieval.bm25.relevance_floor_fraction",
        bm25.relevance_floor_fraction,
        min_value=0.0,
        max_value=1.0,
    )

    rrf = retrieval.rrf
    if not isinstance(rrf, RetrievalRrfPolicy):
        raise TypeError("retrieval.rrf must be RetrievalRrfPolicy")
    _validate_float("retrieval.rrf.rank_constant", rrf.rank_constant, min_value=1.0, max_value=1000.0)
    for key in (
        "lexical_weight",
        "bm25_weight",
        "semantic_weight",
        "sequence_weight",
        "quote_weight",
        "temporal_weight",
        "graph_weight",
        "continuity_weight",
        "fallback_channel_weight",
    ):
        _validate_float(f"retrieval.rrf.{key}", getattr(rrf, key), min_value=0.0, max_value=8.0)

    pack = retrieval.pack
    if not isinstance(pack, RetrievalPackPolicy):
        raise TypeError("retrieval.pack must be RetrievalPackPolicy")
    _validate_int("retrieval.pack.core_limit", pack.core_limit, min_value=1, max_value=64)
    _validate_int("retrieval.pack.context_limit", pack.context_limit, min_value=0, max_value=64)
    _validate_int("retrieval.pack.conflict_limit", pack.conflict_limit, min_value=0, max_value=64)
    _validate_int("retrieval.pack.continuity_limit", pack.continuity_limit, min_value=0, max_value=64)
    _validate_int(
        "retrieval.pack.guarded_neighbor_scan_limit",
        pack.guarded_neighbor_scan_limit,
        min_value=1,
        max_value=128,
    )
    _validate_int(
        "retrieval.pack.guarded_extra_budget_min",
        pack.guarded_extra_budget_min,
        min_value=0,
        max_value=64,
    )
    _validate_int(
        "retrieval.pack.guarded_extra_budget_max",
        pack.guarded_extra_budget_max,
        min_value=0,
        max_value=64,
    )
    _validate_int(
        "retrieval.pack.guarded_extra_budget_ratio_divisor",
        pack.guarded_extra_budget_ratio_divisor,
        min_value=1,
        max_value=64,
    )
    if pack.guarded_extra_budget_min > pack.guarded_extra_budget_max:
        raise ValueError("retrieval.pack.guarded_extra_budget_min must be <= retrieval.pack.guarded_extra_budget_max")

    cache = retrieval.cache
    if not isinstance(cache, RetrievalCachePolicy):
        raise TypeError("retrieval.cache must be RetrievalCachePolicy")
    _validate_bool("retrieval.cache.fail_closed_on_uncertain_store_scope", cache.fail_closed_on_uncertain_store_scope)
    _validate_bool(
        "retrieval.cache.fail_closed_on_uncertain_continuity_scope",
        cache.fail_closed_on_uncertain_continuity_scope,
    )


def _validate_runtime_policy(runtime: RuntimePolicy) -> None:
    if not isinstance(runtime, RuntimePolicy):
        raise TypeError("runtime must be RuntimePolicy")
    _validate_bool("runtime.require_uncertainty_citations", runtime.require_uncertainty_citations)
    _validate_bool("runtime.allow_autonomous_destructive_mutation", runtime.allow_autonomous_destructive_mutation)
    _validate_bool("runtime.allow_raw_pii_storage", runtime.allow_raw_pii_storage)
    _validate_int("runtime.tombstone_retention_days", runtime.tombstone_retention_days, min_value=0, max_value=3650)

    retrieval = runtime.retrieval
    if not isinstance(retrieval, RuntimeRetrievalPolicy):
        raise TypeError("runtime.retrieval must be RuntimeRetrievalPolicy")
    _validate_bool("runtime.retrieval.ltm_multi_pass_enabled", retrieval.ltm_multi_pass_enabled)
    _validate_int("runtime.retrieval.ltm_max_passes", retrieval.ltm_max_passes, min_value=1, max_value=8)
    _validate_float(
        "runtime.retrieval.ltm_followup_min_match_max",
        retrieval.ltm_followup_min_match_max,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_float(
        "runtime.retrieval.ltm_followup_min_pack_confidence",
        retrieval.ltm_followup_min_pack_confidence,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_float(
        "runtime.retrieval.ltm_followup_time_budget_ms",
        retrieval.ltm_followup_time_budget_ms,
        min_value=1.0,
        max_value=60000.0,
    )
    _validate_int(
        "runtime.retrieval.ltm_followup_max_query_tokens",
        retrieval.ltm_followup_max_query_tokens,
        min_value=1,
        max_value=8192,
    )
    _validate_int("runtime.retrieval.episode_top_k", retrieval.episode_top_k, min_value=1, max_value=64)
    _validate_float("runtime.retrieval.episode_min_score", retrieval.episode_min_score, min_value=0.0, max_value=1.0)
    _validate_float(
        "runtime.retrieval.episode_primary_min_score",
        retrieval.episode_primary_min_score,
        min_value=0.0,
        max_value=1.0,
    )
    if float(retrieval.episode_primary_min_score) < float(retrieval.episode_min_score):
        raise ValueError("runtime.retrieval.episode_primary_min_score must be >= runtime.retrieval.episode_min_score")
    _validate_float(
        "runtime.retrieval.episode_primary_min_cue_match",
        retrieval.episode_primary_min_cue_match,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_float(
        "runtime.retrieval.episode_primary_min_lexical",
        retrieval.episode_primary_min_lexical,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_float(
        "runtime.retrieval.memory_signal_min_score",
        retrieval.memory_signal_min_score,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_bool("runtime.retrieval.routine_hard_cap_enabled", retrieval.routine_hard_cap_enabled)
    _validate_float("runtime.retrieval.min_query_match_max", retrieval.min_query_match_max, min_value=0.0, max_value=1.0)
    _validate_float(
        "runtime.retrieval.min_query_match_mean",
        retrieval.min_query_match_mean,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_float(
        "runtime.retrieval.min_query_informative_overlap",
        retrieval.min_query_informative_overlap,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_int(
        "runtime.retrieval.min_query_token_hits",
        retrieval.min_query_token_hits,
        min_value=1,
        max_value=64,
    )
    _validate_bool("runtime.retrieval.prewarm_caches", retrieval.prewarm_caches)


def _validate_config(cfg: NumquamOblitaConfig) -> None:
    """Validate cross-field bounds that must hold after merges."""

    _validate_retrieval_config(cfg.retrieval)
    _validate_runtime_policy(cfg.runtime)
    # Re-hydrate to trigger RuntimeEfficiencyPolicy.__post_init__ validations.
    cfg.efficiency = RuntimeEfficiencyPolicy(**asdict(cfg.efficiency))
