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
    min_recommendation_relevance: float = 0.45
    min_assistant_detail_relevance: float = 0.56
    min_answer_specificity: float = 0.50
    min_self_fact_relevance: float = 0.58
    min_self_fact_specificity: float = 0.60
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
    verbatim_session_recall: RetrievalProfilePolicy = field(
        default_factory=lambda: RetrievalProfilePolicy(
            temporal_scale=0.45,
            graph_scale=0.40,
            candidate_pool_floor=160,
            candidate_cap_ratio=1.0,
            candidate_cap_floor=32,
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
class RetrievalAnnSidecarPolicy:
    """Bounded local vector sidecar for additive candidate generation only."""

    enabled: bool = False
    top_k_ann: int = 16
    candidate_cap_ratio: float = 0.25
    candidate_cap_floor: int = 4
    max_latency_ms: float = 35.0
    embedding_backend: str = "hashed-simhash-sqlite"
    embedding_store_path: str = ""
    rebuild_mode: str = "lazy"


@dataclass(slots=True)
class RetrievalRawContextSidecarPolicy:
    """Read-only raw-context helper for explicit quote/provenance recall."""

    write_enabled: bool = True
    read_enabled: bool = True
    neighbor_turns: int = 1
    max_turns: int = 3
    max_chars: int = 1200


@dataclass(slots=True)
class RetrievalSourceProjectionPolicy:
    """Read-only source/round projection helper caps."""

    enabled: bool = False
    per_source_fanout_cap: int = 4
    per_query_contribution_cap: int = 12


@dataclass(slots=True)
class RetrievalTemporalLiftPolicy:
    """Bounded temporal ranking helper policy."""

    enabled: bool = False
    score_cap: float = 0.18


@dataclass(slots=True)
class RetrievalCrossEncoderRerankerPolicy:
    """Optional bounded reranker policy."""

    enabled: bool = False
    top_n: int = 24
    top_m: int = 8
    max_latency_ms: float = 75.0


@dataclass(slots=True)
class RetrievalUpdateFamilyResolverPolicy:
    """Read-only rank-time resolver for correction/update families."""

    enabled: bool = False
    family_scan_limit: int = 24


@dataclass(slots=True)
class RetrievalObservationProjectionPolicy:
    """Read-only observation/assertion projection helper caps."""

    enabled: bool = False
    per_source_fanout_cap: int = 4
    per_query_contribution_cap: int = 8


@dataclass(slots=True)
class RetrievalDerivedHelpersPolicy:
    """Config gates for bounded helper lanes imported under the truth contract."""

    source_projection: RetrievalSourceProjectionPolicy = field(default_factory=RetrievalSourceProjectionPolicy)
    temporal_lift: RetrievalTemporalLiftPolicy = field(default_factory=RetrievalTemporalLiftPolicy)
    cross_encoder_reranker: RetrievalCrossEncoderRerankerPolicy = field(
        default_factory=RetrievalCrossEncoderRerankerPolicy
    )
    update_family_resolver: RetrievalUpdateFamilyResolverPolicy = field(
        default_factory=RetrievalUpdateFamilyResolverPolicy
    )
    observation_projection: RetrievalObservationProjectionPolicy = field(
        default_factory=RetrievalObservationProjectionPolicy
    )


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
    ann_sidecar: RetrievalAnnSidecarPolicy = field(default_factory=RetrievalAnnSidecarPolicy)
    raw_context_sidecar: RetrievalRawContextSidecarPolicy = field(default_factory=RetrievalRawContextSidecarPolicy)
    derived_helpers: RetrievalDerivedHelpersPolicy = field(default_factory=RetrievalDerivedHelpersPolicy)


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
class WorkSessionScratchpadPolicy:
    """Built-in helper-state lane for work-session context packages."""

    enabled: bool = True
    inject_enabled: bool = True
    resume_injection_enabled: bool = True
    diagnostics_enabled: bool = False
    max_entries_per_scope: int = 200
    max_injected_items: int = 8
    max_injected_chars: int = 2400
    max_raw_ref_bytes: int = 2_000_000
    retention_days: int = 14
    min_replaceability_score: float = 0.70


@dataclass(slots=True)
class ProvisionalSensitivityProfile:
    """Configurable caps and floors for provisional auto-write sensitivity."""

    worthiness_threshold: float = 0.64
    self_claim_threshold: float = 0.70
    max_auto_writes_per_turn: int = 2
    max_auto_writes_per_session: int = 24


@dataclass(slots=True)
class ProvisionalReviewWorthinessPolicy:
    """Config-driven scoring thresholds for review-worthiness flagging."""

    enabled: bool = True
    fact_min_score: float = 0.68
    preference_min_score: float = 0.64
    plan_min_score: float = 0.62
    event_note_min_score: float = 0.70
    self_claim_min_score: float = 0.88
    correction_min_score: float = 0.92
    reinforcement_weight: float = 0.25
    distinct_session_weight: float = 0.15
    stability_weight: float = 0.35
    salience_weight: float = 0.25
    conflict_penalty: float = 0.35
    self_claim_penalty: float = 0.20


@dataclass(slots=True)
class ProvisionalNearDuplicatePolicy:
    """Detect/log-only controls for provisional near-duplicate suspicions."""

    enabled: bool = True
    similarity_threshold: float = 0.72
    max_pairs_per_record: int = 2


@dataclass(slots=True)
class ProvisionalMemoryPolicy:
    """Feature flags and tunable policies for agent-owned provisional memory."""

    enabled: bool = True
    retrieval_enabled: bool = True
    stm_sweep_enabled: bool = True
    proposal_capture_enabled: bool = False
    allow_self_claim_auto_write: bool = True
    default_sensitivity: str = "balanced"
    inactivity_gap_seconds: int = 300
    review_worthiness: ProvisionalReviewWorthinessPolicy = field(default_factory=ProvisionalReviewWorthinessPolicy)
    near_duplicate: ProvisionalNearDuplicatePolicy = field(default_factory=ProvisionalNearDuplicatePolicy)
    conservative: ProvisionalSensitivityProfile = field(
        default_factory=lambda: ProvisionalSensitivityProfile(
            worthiness_threshold=0.72,
            self_claim_threshold=0.80,
            max_auto_writes_per_turn=1,
            max_auto_writes_per_session=12,
        )
    )
    balanced: ProvisionalSensitivityProfile = field(
        default_factory=lambda: ProvisionalSensitivityProfile(
            worthiness_threshold=0.64,
            self_claim_threshold=0.70,
            max_auto_writes_per_turn=2,
            max_auto_writes_per_session=24,
        )
    )
    eager: ProvisionalSensitivityProfile = field(
        default_factory=lambda: ProvisionalSensitivityProfile(
            worthiness_threshold=0.56,
            self_claim_threshold=0.62,
            max_auto_writes_per_turn=4,
            max_auto_writes_per_session=48,
        )
    )
    consolidation_enabled: bool = True
    maintenance_enabled: bool = True
    high_risk_proposal_capture_enabled: bool = False
    dormant_days: int = 90
    archive_days: int = 365
    plan_currentness_days: int = 30
    source_registration_ttl_seconds: int = 604800
    maintenance_max_records: int = 25
    policy_version: str = "v0.2"
    policy_source: str = "fresh_standard"


@dataclass(slots=True)
class RetrievalFeedbackPolicy:
    """Local-only capture controls for retrieval feedback signals."""

    enabled: bool = True
    max_entries: int = 2000
    max_query_chars: int = 200


@dataclass(slots=True)
class HistorySurfacesPolicy:
    """Read-only inspectability limits for lineage/history surfaces."""

    enabled: bool = True
    max_episode_entries: int = 40
    max_provisional_events: int = 80


@dataclass(slots=True)
class ContinuityAddsPolicy:
    """Low-risk continuity surfaces layered above existing runtime reads."""

    enabled: bool = True
    action_log_enabled: bool = True
    action_log_max_entries: int = 500
    wake_up_pack_enabled: bool = True
    resume_pack_enabled: bool = True
    pinned_preferences_enabled: bool = True


@dataclass(slots=True)
class NumquamOblitaConfig:
    """Top-level typed configuration model."""

    gate: GateThresholds = field(default_factory=GateThresholds)
    retrieval: RetrievalBudget = field(default_factory=RetrievalBudget)
    decay: DecayPolicy = field(default_factory=DecayPolicy)
    runtime: RuntimePolicy = field(default_factory=RuntimePolicy)
    provisional_memory: ProvisionalMemoryPolicy = field(default_factory=ProvisionalMemoryPolicy)
    retrieval_feedback: RetrievalFeedbackPolicy = field(default_factory=RetrievalFeedbackPolicy)
    history_surfaces: HistorySurfacesPolicy = field(default_factory=HistorySurfacesPolicy)
    continuity_adds: ContinuityAddsPolicy = field(default_factory=ContinuityAddsPolicy)
    efficiency: RuntimeEfficiencyPolicy = field(default_factory=RuntimeEfficiencyPolicy)
    work_session_scratchpad: WorkSessionScratchpadPolicy = field(default_factory=WorkSessionScratchpadPolicy)

    def as_dict(self) -> dict[str, Any]:
        """Return config as a plain dictionary."""
        return asdict(self)


def default_config() -> NumquamOblitaConfig:
    """Return the baseline config with locked defaults."""

    cfg = NumquamOblitaConfig()
    _validate_config(cfg)
    return cfg


def upgrade_preserved_config() -> NumquamOblitaConfig:
    """Return the explicit v0.1-compatible posture for omitted upgrade fields."""
    cfg = NumquamOblitaConfig()
    cfg.provisional_memory.enabled = False
    cfg.provisional_memory.retrieval_enabled = False
    cfg.provisional_memory.stm_sweep_enabled = False
    cfg.provisional_memory.consolidation_enabled = False
    cfg.provisional_memory.maintenance_enabled = False
    cfg.provisional_memory.policy_source = "upgrade_preserved"
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


def load_config(path: str | Path | None, *, strict: bool = False, upgrade: bool = False) -> NumquamOblitaConfig:
    """Load JSON config file and merge over defaults.

    Use ``strict=True`` to fail on unknown config keys.
    """

    cfg = upgrade_preserved_config() if upgrade else default_config()
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
    if data.get("provisional_memory"):
        merged.provisional_memory.policy_source = "custom"
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
    _validate_profile_policy("retrieval.router.verbatim_session_recall", router.verbatim_session_recall)

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

    raw_context = retrieval.raw_context_sidecar
    if not isinstance(raw_context, RetrievalRawContextSidecarPolicy):
        raise TypeError("retrieval.raw_context_sidecar must be RetrievalRawContextSidecarPolicy")
    _validate_bool("retrieval.raw_context_sidecar.write_enabled", raw_context.write_enabled)
    _validate_bool("retrieval.raw_context_sidecar.read_enabled", raw_context.read_enabled)
    _validate_int("retrieval.raw_context_sidecar.neighbor_turns", raw_context.neighbor_turns, min_value=0, max_value=4)
    _validate_int("retrieval.raw_context_sidecar.max_turns", raw_context.max_turns, min_value=1, max_value=8)
    _validate_int("retrieval.raw_context_sidecar.max_chars", raw_context.max_chars, min_value=64, max_value=4000)

    ann = retrieval.ann_sidecar
    if not isinstance(ann, RetrievalAnnSidecarPolicy):
        raise TypeError("retrieval.ann_sidecar must be RetrievalAnnSidecarPolicy")
    _validate_bool("retrieval.ann_sidecar.enabled", ann.enabled)
    _validate_int("retrieval.ann_sidecar.top_k_ann", ann.top_k_ann, min_value=1, max_value=256)
    _validate_float(
        "retrieval.ann_sidecar.candidate_cap_ratio",
        ann.candidate_cap_ratio,
        min_value=0.0,
        max_value=1.0,
    )
    _validate_int("retrieval.ann_sidecar.candidate_cap_floor", ann.candidate_cap_floor, min_value=1, max_value=256)
    _validate_float("retrieval.ann_sidecar.max_latency_ms", ann.max_latency_ms, min_value=1.0, max_value=60_000.0)
    if not isinstance(ann.embedding_backend, str):
        raise TypeError("retrieval.ann_sidecar.embedding_backend must be str")
    if ann.embedding_backend.strip() != "hashed-simhash-sqlite":
        raise ValueError("retrieval.ann_sidecar.embedding_backend must be 'hashed-simhash-sqlite'")
    if not isinstance(ann.embedding_store_path, str):
        raise TypeError("retrieval.ann_sidecar.embedding_store_path must be str")
    if not isinstance(ann.rebuild_mode, str):
        raise TypeError("retrieval.ann_sidecar.rebuild_mode must be str")
    if ann.rebuild_mode.strip() not in {"lazy", "manual"}:
        raise ValueError("retrieval.ann_sidecar.rebuild_mode must be one of: lazy, manual")

    derived = retrieval.derived_helpers
    if not isinstance(derived, RetrievalDerivedHelpersPolicy):
        raise TypeError("retrieval.derived_helpers must be RetrievalDerivedHelpersPolicy")

    source_projection = derived.source_projection
    if not isinstance(source_projection, RetrievalSourceProjectionPolicy):
        raise TypeError("retrieval.derived_helpers.source_projection must be RetrievalSourceProjectionPolicy")
    _validate_bool("retrieval.derived_helpers.source_projection.enabled", source_projection.enabled)
    _validate_int(
        "retrieval.derived_helpers.source_projection.per_source_fanout_cap",
        source_projection.per_source_fanout_cap,
        min_value=1,
        max_value=128,
    )
    _validate_int(
        "retrieval.derived_helpers.source_projection.per_query_contribution_cap",
        source_projection.per_query_contribution_cap,
        min_value=1,
        max_value=256,
    )

    temporal_lift = derived.temporal_lift
    if not isinstance(temporal_lift, RetrievalTemporalLiftPolicy):
        raise TypeError("retrieval.derived_helpers.temporal_lift must be RetrievalTemporalLiftPolicy")
    _validate_bool("retrieval.derived_helpers.temporal_lift.enabled", temporal_lift.enabled)
    _validate_float("retrieval.derived_helpers.temporal_lift.score_cap", temporal_lift.score_cap, min_value=0.0, max_value=1.0)

    reranker = derived.cross_encoder_reranker
    if not isinstance(reranker, RetrievalCrossEncoderRerankerPolicy):
        raise TypeError(
            "retrieval.derived_helpers.cross_encoder_reranker must be RetrievalCrossEncoderRerankerPolicy"
        )
    _validate_bool("retrieval.derived_helpers.cross_encoder_reranker.enabled", reranker.enabled)
    _validate_int("retrieval.derived_helpers.cross_encoder_reranker.top_n", reranker.top_n, min_value=1, max_value=256)
    _validate_int("retrieval.derived_helpers.cross_encoder_reranker.top_m", reranker.top_m, min_value=1, max_value=256)
    _validate_float(
        "retrieval.derived_helpers.cross_encoder_reranker.max_latency_ms",
        reranker.max_latency_ms,
        min_value=1.0,
        max_value=60_000.0,
    )
    if reranker.top_m > reranker.top_n:
        raise ValueError(
            "retrieval.derived_helpers.cross_encoder_reranker.top_m must be <= "
            "retrieval.derived_helpers.cross_encoder_reranker.top_n"
        )

    resolver = derived.update_family_resolver
    if not isinstance(resolver, RetrievalUpdateFamilyResolverPolicy):
        raise TypeError(
            "retrieval.derived_helpers.update_family_resolver must be RetrievalUpdateFamilyResolverPolicy"
        )
    _validate_bool("retrieval.derived_helpers.update_family_resolver.enabled", resolver.enabled)
    _validate_int(
        "retrieval.derived_helpers.update_family_resolver.family_scan_limit",
        resolver.family_scan_limit,
        min_value=1,
        max_value=256,
    )

    observation = derived.observation_projection
    if not isinstance(observation, RetrievalObservationProjectionPolicy):
        raise TypeError(
            "retrieval.derived_helpers.observation_projection must be RetrievalObservationProjectionPolicy"
        )
    _validate_bool("retrieval.derived_helpers.observation_projection.enabled", observation.enabled)
    _validate_int(
        "retrieval.derived_helpers.observation_projection.per_source_fanout_cap",
        observation.per_source_fanout_cap,
        min_value=1,
        max_value=128,
    )
    _validate_int(
        "retrieval.derived_helpers.observation_projection.per_query_contribution_cap",
        observation.per_query_contribution_cap,
        min_value=1,
        max_value=256,
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


def _validate_provisional_sensitivity(name: str, profile: ProvisionalSensitivityProfile) -> None:
    if not isinstance(profile, ProvisionalSensitivityProfile):
        raise TypeError(f"{name} must be ProvisionalSensitivityProfile")
    _validate_float(f"{name}.worthiness_threshold", profile.worthiness_threshold, min_value=0.0, max_value=1.0)
    _validate_float(f"{name}.self_claim_threshold", profile.self_claim_threshold, min_value=0.0, max_value=1.0)
    _validate_int(f"{name}.max_auto_writes_per_turn", profile.max_auto_writes_per_turn, min_value=1, max_value=64)
    _validate_int(f"{name}.max_auto_writes_per_session", profile.max_auto_writes_per_session, min_value=1, max_value=1024)
    if profile.max_auto_writes_per_session < profile.max_auto_writes_per_turn:
        raise ValueError(f"{name}.max_auto_writes_per_session must be >= {name}.max_auto_writes_per_turn")


def _validate_provisional_memory_policy(policy: ProvisionalMemoryPolicy) -> None:
    if not isinstance(policy, ProvisionalMemoryPolicy):
        raise TypeError("provisional_memory must be ProvisionalMemoryPolicy")
    _validate_bool("provisional_memory.enabled", policy.enabled)
    _validate_bool("provisional_memory.retrieval_enabled", policy.retrieval_enabled)
    _validate_bool("provisional_memory.stm_sweep_enabled", policy.stm_sweep_enabled)
    _validate_bool("provisional_memory.proposal_capture_enabled", policy.proposal_capture_enabled)
    _validate_bool("provisional_memory.allow_self_claim_auto_write", policy.allow_self_claim_auto_write)
    _validate_bool("provisional_memory.consolidation_enabled", policy.consolidation_enabled)
    _validate_bool("provisional_memory.maintenance_enabled", policy.maintenance_enabled)
    _validate_bool("provisional_memory.high_risk_proposal_capture_enabled", policy.high_risk_proposal_capture_enabled)
    if str(policy.default_sensitivity) not in {"conservative", "balanced", "eager"}:
        raise ValueError("provisional_memory.default_sensitivity must be one of: conservative, balanced, eager")
    _validate_int("provisional_memory.inactivity_gap_seconds", policy.inactivity_gap_seconds, min_value=1, max_value=86400)
    if not isinstance(policy.review_worthiness, ProvisionalReviewWorthinessPolicy):
        raise TypeError("provisional_memory.review_worthiness must be ProvisionalReviewWorthinessPolicy")
    _validate_bool("provisional_memory.review_worthiness.enabled", policy.review_worthiness.enabled)
    for key in (
        "fact_min_score",
        "preference_min_score",
        "plan_min_score",
        "event_note_min_score",
        "self_claim_min_score",
        "correction_min_score",
        "reinforcement_weight",
        "distinct_session_weight",
        "stability_weight",
        "salience_weight",
        "conflict_penalty",
        "self_claim_penalty",
    ):
        _validate_float(
            f"provisional_memory.review_worthiness.{key}",
            getattr(policy.review_worthiness, key),
            min_value=0.0,
            max_value=1.0,
        )
    if not isinstance(policy.near_duplicate, ProvisionalNearDuplicatePolicy):
        raise TypeError("provisional_memory.near_duplicate must be ProvisionalNearDuplicatePolicy")
    _validate_bool("provisional_memory.near_duplicate.enabled", policy.near_duplicate.enabled)
    _validate_float(
        "provisional_memory.near_duplicate.similarity_threshold",
        policy.near_duplicate.similarity_threshold,
        min_value=0.0,
        max_value=1.0,
    )
    if float(policy.near_duplicate.similarity_threshold) <= 0.0:
        raise ValueError("provisional_memory.near_duplicate.similarity_threshold must be > 0.0")
    _validate_int(
        "provisional_memory.near_duplicate.max_pairs_per_record",
        policy.near_duplicate.max_pairs_per_record,
        min_value=1,
        max_value=32,
    )
    _validate_provisional_sensitivity("provisional_memory.conservative", policy.conservative)
    _validate_provisional_sensitivity("provisional_memory.balanced", policy.balanced)
    _validate_provisional_sensitivity("provisional_memory.eager", policy.eager)
    _validate_int("provisional_memory.dormant_days", policy.dormant_days, min_value=1, max_value=3650)
    _validate_int("provisional_memory.archive_days", policy.archive_days, min_value=2, max_value=7300)
    if policy.archive_days <= policy.dormant_days:
        raise ValueError("provisional_memory.archive_days must be > provisional_memory.dormant_days")
    _validate_int("provisional_memory.plan_currentness_days", policy.plan_currentness_days, min_value=1, max_value=365)
    _validate_int("provisional_memory.source_registration_ttl_seconds", policy.source_registration_ttl_seconds, min_value=60, max_value=2592000)
    _validate_int("provisional_memory.maintenance_max_records", policy.maintenance_max_records, min_value=1, max_value=100)
    if str(policy.policy_source) not in {"fresh_standard", "upgrade_preserved", "custom"}:
        raise ValueError("provisional_memory.policy_source must be fresh_standard, upgrade_preserved, or custom")


def _validate_retrieval_feedback_policy(policy: RetrievalFeedbackPolicy) -> None:
    if not isinstance(policy, RetrievalFeedbackPolicy):
        raise TypeError("retrieval_feedback must be RetrievalFeedbackPolicy")
    _validate_bool("retrieval_feedback.enabled", policy.enabled)
    _validate_int("retrieval_feedback.max_entries", policy.max_entries, min_value=1, max_value=100_000)
    _validate_int("retrieval_feedback.max_query_chars", policy.max_query_chars, min_value=1, max_value=2_000)


def _validate_history_surfaces_policy(policy: HistorySurfacesPolicy) -> None:
    if not isinstance(policy, HistorySurfacesPolicy):
        raise TypeError("history_surfaces must be HistorySurfacesPolicy")
    _validate_bool("history_surfaces.enabled", policy.enabled)
    _validate_int("history_surfaces.max_episode_entries", policy.max_episode_entries, min_value=1, max_value=500)
    _validate_int(
        "history_surfaces.max_provisional_events",
        policy.max_provisional_events,
        min_value=1,
        max_value=500,
    )


def _validate_continuity_adds_policy(policy: ContinuityAddsPolicy) -> None:
    if not isinstance(policy, ContinuityAddsPolicy):
        raise TypeError("continuity_adds must be ContinuityAddsPolicy")
    _validate_bool("continuity_adds.enabled", policy.enabled)
    _validate_bool("continuity_adds.action_log_enabled", policy.action_log_enabled)
    _validate_bool("continuity_adds.wake_up_pack_enabled", policy.wake_up_pack_enabled)
    _validate_bool("continuity_adds.resume_pack_enabled", policy.resume_pack_enabled)
    _validate_bool("continuity_adds.pinned_preferences_enabled", policy.pinned_preferences_enabled)
    _validate_int("continuity_adds.action_log_max_entries", policy.action_log_max_entries, min_value=1, max_value=10_000)


def _validate_work_session_scratchpad_policy(policy: WorkSessionScratchpadPolicy) -> None:
    if not isinstance(policy, WorkSessionScratchpadPolicy):
        raise TypeError("work_session_scratchpad must be WorkSessionScratchpadPolicy")
    _validate_bool("work_session_scratchpad.enabled", policy.enabled)
    _validate_bool("work_session_scratchpad.inject_enabled", policy.inject_enabled)
    _validate_bool("work_session_scratchpad.resume_injection_enabled", policy.resume_injection_enabled)
    _validate_bool("work_session_scratchpad.diagnostics_enabled", policy.diagnostics_enabled)
    _validate_int("work_session_scratchpad.max_entries_per_scope", policy.max_entries_per_scope, min_value=1, max_value=10_000)
    _validate_int("work_session_scratchpad.max_injected_items", policy.max_injected_items, min_value=1, max_value=100)
    _validate_int("work_session_scratchpad.max_injected_chars", policy.max_injected_chars, min_value=128, max_value=64_000)
    _validate_int("work_session_scratchpad.max_raw_ref_bytes", policy.max_raw_ref_bytes, min_value=1, max_value=100_000_000)
    _validate_int("work_session_scratchpad.retention_days", policy.retention_days, min_value=1, max_value=3650)
    _validate_float(
        "work_session_scratchpad.min_replaceability_score",
        policy.min_replaceability_score,
        min_value=0.0,
        max_value=1.0,
    )


def _validate_config(cfg: NumquamOblitaConfig) -> None:
    """Validate cross-field bounds that must hold after merges."""

    _validate_retrieval_config(cfg.retrieval)
    _validate_runtime_policy(cfg.runtime)
    _validate_provisional_memory_policy(cfg.provisional_memory)
    _validate_retrieval_feedback_policy(cfg.retrieval_feedback)
    _validate_history_surfaces_policy(cfg.history_surfaces)
    _validate_continuity_adds_policy(cfg.continuity_adds)
    # Re-hydrate to trigger RuntimeEfficiencyPolicy.__post_init__ validations.
    cfg.efficiency = RuntimeEfficiencyPolicy(**asdict(cfg.efficiency))
    _validate_work_session_scratchpad_policy(cfg.work_session_scratchpad)
