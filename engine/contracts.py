from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Iterable, Optional


class AtomType(str, Enum):
    """Canonical memory atom categories."""

    EPISODE = "episode"
    ATOMIC_FACT = "atomic_fact"
    RELATIONAL = "relational"
    AFFECTIVE = "affective"
    PROCEDURAL_STYLE = "procedural_style"


class WriteAction(str, Enum):
    """Allowed write-gate outcomes."""

    ADD = "ADD"
    UPDATE = "UPDATE"
    IGNORE = "IGNORE"
    PROPOSE_CREATE = "PROPOSE_CREATE"
    PROPOSE_EDIT = "PROPOSE_EDIT"
    PROPOSE_DELETE = "PROPOSE_DELETE"


@dataclass(slots=True)
class SourceRef:
    """Immutable evidence pointer into source content."""

    source_id: str
    message_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate source reference invariants."""

        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if self.span_start is not None and self.span_start < 0:
            raise ValueError("span_start must be >= 0")
        if self.span_end is not None and self.span_end < 0:
            raise ValueError("span_end must be >= 0")
        if self.span_start is not None and self.span_end is not None and self.span_end < self.span_start:
            raise ValueError("span_end must be >= span_start")


@dataclass(slots=True)
class NormalizedTurn:
    """Normalized conversation turn used by ingest pipeline."""

    source_id: str
    role: str
    text: str
    message_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    conversation_id: Optional[str] = None
    quote_text: Optional[str] = None
    sequence_index: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate normalized turn fields."""

        if not self.source_id.strip():
            raise ValueError("source_id is required")
        role = self.role.strip().lower()
        if role not in {"user", "assistant", "developer", "system", "tool"}:
            raise ValueError(f"unsupported role: {self.role}")
        self.role = role
        if not self.text.strip():
            raise ValueError("text is required")
        quote_text = self.text if self.quote_text is None else str(self.quote_text)
        if not quote_text:
            raise ValueError("quote_text is required")
        self.quote_text = quote_text
        if self.sequence_index is not None and self.sequence_index < 0:
            raise ValueError("sequence_index must be >= 0")


@dataclass(slots=True)
class CandidateAtom:
    """Candidate memory atom proposed by extraction stage."""

    candidate_id: str
    atom_type: AtomType
    canonical_text: str
    source_refs: list[SourceRef]
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    confidence: float = 0.0
    salience: float = 0.0

    def __post_init__(self) -> None:
        """Validate candidate atom fields and score bounds."""

        if not self.candidate_id.strip():
            raise ValueError("candidate_id is required")
        if not self.canonical_text.strip():
            raise ValueError("canonical_text is required")
        if not self.source_refs:
            raise ValueError("source_refs is required")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.salience < 0.0 or self.salience > 1.0:
            raise ValueError("salience must be in [0, 1]")


@dataclass(slots=True)
class WriteDecision:
    """Normalized write-gate decision record."""

    candidate_id: str
    action: WriteAction
    confidence: float
    reason_code: str
    gate_stage: str

    def __post_init__(self) -> None:
        """Validate write decision payload."""

        if not self.candidate_id.strip():
            raise ValueError("candidate_id is required")
        if not self.reason_code.strip():
            raise ValueError("reason_code is required")
        stage = self.gate_stage.strip().upper()
        if stage not in {"A", "B"}:
            raise ValueError("gate_stage must be A or B")
        self.gate_stage = stage
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(slots=True)
class MemoryPackItem:
    """Single memory-pack evidence item."""

    atom_id: str
    canonical_text: str
    confidence: float
    source_refs: list[SourceRef]
    record_updated_at: Optional[datetime] = None
    conflict_state: str = "active"
    conflict_with_ids: list[str] = field(default_factory=list)
    memory_layer: str = "atom"
    trust_tier: str = "evidence"
    raw_context_text: str = ""
    raw_context_turn_count: int = 0

    def __post_init__(self) -> None:
        """Validate memory-pack item integrity."""

        if not self.atom_id.strip():
            raise ValueError("atom_id is required")
        if not self.canonical_text.strip():
            raise ValueError("canonical_text is required")
        if not self.source_refs:
            raise ValueError("source_refs is required")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.record_updated_at is not None and not isinstance(self.record_updated_at, datetime):
            raise ValueError("record_updated_at must be datetime when provided")
        if not str(self.memory_layer or "").strip():
            raise ValueError("memory_layer is required")
        if not str(self.trust_tier or "").strip():
            raise ValueError("trust_tier is required")
        if not isinstance(self.raw_context_turn_count, int) or isinstance(self.raw_context_turn_count, bool):
            raise ValueError("raw_context_turn_count must be int")
        if self.raw_context_turn_count < 0:
            raise ValueError("raw_context_turn_count must be >= 0")


@dataclass(slots=True)
class EfficiencyMetricsContract:
    """Additive runtime-efficiency metrics for backward-compatible contracts."""

    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    tokens_prompt_avg: float = 0.0
    tokens_completion_avg: float = 0.0
    tokens_total_avg: float = 0.0
    retrieval_fanout_avg: float = 0.0
    retrieval_fanout_p95: float = 0.0

    def __post_init__(self) -> None:
        for key in (
            "latency_p50_ms",
            "latency_p95_ms",
            "tokens_prompt_avg",
            "tokens_completion_avg",
            "tokens_total_avg",
            "retrieval_fanout_avg",
            "retrieval_fanout_p95",
        ):
            value = float(getattr(self, key))
            if not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
            if value < 0.0:
                raise ValueError(f"{key} must be >= 0")
            setattr(self, key, value)


@dataclass(slots=True)
class RetrievalSelectedAtomContract:
    """Redacted selected-evidence audit record."""

    atom_id: str
    section: str
    score: float = 0.0

    def __post_init__(self) -> None:
        if not self.atom_id.strip():
            raise ValueError("atom_id is required")
        if not self.section.strip():
            raise ValueError("section is required")
        value = float(self.score)
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        if value < 0.0:
            raise ValueError("score must be >= 0")
        self.score = value


@dataclass(slots=True)
class RetrievalDroppedAtomContract:
    """Redacted dropped-evidence audit record."""

    atom_id: str
    reason_code: str
    score: float | None = None

    def __post_init__(self) -> None:
        if not self.atom_id.strip():
            raise ValueError("atom_id is required")
        if not self.reason_code.strip():
            raise ValueError("reason_code is required")
        if self.score is None:
            return
        value = float(self.score)
        if not math.isfinite(value):
            raise ValueError("score must be finite when provided")
        if value < 0.0:
            raise ValueError("score must be >= 0 when provided")
        self.score = value


@dataclass(slots=True)
class RetrievalHelperLaneContract:
    """Additive helper-lane diagnostics block for bounded retrieval helpers."""

    name: str
    enabled: bool = False
    used: bool = False
    contribution_count: int = 0
    fallback_reason: str = ""

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        if not self.name:
            raise ValueError("name is required")
        self.enabled = bool(self.enabled)
        self.used = bool(self.used)
        self.contribution_count = int(self.contribution_count)
        if self.contribution_count < 0:
            raise ValueError("contribution_count must be >= 0")
        self.fallback_reason = str(self.fallback_reason or "").strip()


@dataclass(slots=True)
class RetrievalDerivedArtifactContract:
    """Helper-only derived artifact contract that can never become truth authority."""

    helper_name: str
    source_ids: list[str] = field(default_factory=list)
    anchor_atom_ids: list[str] = field(default_factory=list)
    truth_namespace: str = "retrieval_helper_only"
    authoritative: bool = False
    sole_evidence_allowed: bool = False
    rebuildable: bool = True

    def __post_init__(self) -> None:
        self.helper_name = str(self.helper_name or "").strip()
        if not self.helper_name:
            raise ValueError("helper_name is required")
        self.source_ids = [str(item or "").strip() for item in list(self.source_ids or []) if str(item or "").strip()]
        self.anchor_atom_ids = [
            str(item or "").strip() for item in list(self.anchor_atom_ids or []) if str(item or "").strip()
        ]
        self.truth_namespace = str(self.truth_namespace or "").strip() or "retrieval_helper_only"
        if self.truth_namespace != "retrieval_helper_only":
            raise ValueError("truth_namespace must be retrieval_helper_only")
        if bool(self.authoritative):
            raise ValueError("authoritative must be False for derived helper artifacts")
        if bool(self.sole_evidence_allowed):
            raise ValueError("sole_evidence_allowed must be False for derived helper artifacts")
        self.authoritative = False
        self.sole_evidence_allowed = False
        self.rebuildable = bool(self.rebuildable)


@dataclass(slots=True)
class RetrievalDiagnosticsContract:
    """Redacted retrieval audit payload for runtime/eval/readout surfaces."""

    selected: list[RetrievalSelectedAtomContract] = field(default_factory=list)
    dropped: list[RetrievalDroppedAtomContract] = field(default_factory=list)
    helper_lanes: list[RetrievalHelperLaneContract] = field(default_factory=list)
    dropped_reason_counts: dict[str, int] = field(default_factory=dict)
    profile_used: str = ""
    selected_count: int = 0
    dropped_count: int = 0
    raw_text_included: bool = False
    ann_enabled: bool = False
    ann_used: bool = False
    ann_candidate_count: int = 0
    ann_latency_ms: float = 0.0
    ann_fallback_reason: str = ""
    ann_store_fingerprint: str = ""
    ann_backend_version: str = ""

    def __post_init__(self) -> None:
        self.selected_count = int(self.selected_count)
        self.dropped_count = int(self.dropped_count)
        if self.selected_count < len(self.selected):
            raise ValueError("selected_count must be >= len(selected)")
        if self.dropped_count < len(self.dropped):
            raise ValueError("dropped_count must be >= len(dropped)")
        if self.selected_count < 0:
            raise ValueError("selected_count must be >= 0")
        if self.dropped_count < 0:
            raise ValueError("dropped_count must be >= 0")
        if not isinstance(self.raw_text_included, bool):
            raise ValueError("raw_text_included must be bool")
        if not isinstance(self.ann_enabled, bool):
            raise ValueError("ann_enabled must be bool")
        if not isinstance(self.ann_used, bool):
            raise ValueError("ann_used must be bool")
        self.ann_candidate_count = int(self.ann_candidate_count)
        if self.ann_candidate_count < 0:
            raise ValueError("ann_candidate_count must be >= 0")
        value = float(self.ann_latency_ms)
        if not math.isfinite(value):
            raise ValueError("ann_latency_ms must be finite")
        if value < 0.0:
            raise ValueError("ann_latency_ms must be >= 0")
        self.ann_latency_ms = value
        self.profile_used = str(self.profile_used or "").strip()
        normalized_counts: dict[str, int] = {}
        for key, value in dict(self.dropped_reason_counts or {}).items():
            reason = str(key or "").strip()
            if not reason:
                raise ValueError("dropped_reason_counts keys must be non-empty")
            count = int(value)
            if count < 0:
                raise ValueError("dropped_reason_counts values must be >= 0")
            normalized_counts[reason] = normalized_counts.get(reason, 0) + count
        self.dropped_reason_counts = normalized_counts
        self.helper_lanes = list(self.helper_lanes or [])


@dataclass(slots=True)
class RetrievalPTLItemContract:
    """Compact ranked-item view for PTL stage payloads."""

    atom_id: str = ""
    source_id: str = ""
    kind: str = ""
    score: float = 0.0
    rank: int = 0
    channel: str = ""

    def __post_init__(self) -> None:
        self.atom_id = str(self.atom_id or "").strip()
        self.source_id = str(self.source_id or "").strip()
        self.kind = str(self.kind or "").strip()
        self.channel = str(self.channel or "").strip()
        self.rank = max(0, int(self.rank or 0))
        value = float(self.score or 0.0)
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        self.score = max(0.0, value)


@dataclass(slots=True)
class RetrievalPTLStageContract:
    """Bounded stage entry for PTL minimal traces."""

    name: str
    status: str = "skipped"
    reason_codes: list[str] = field(default_factory=list)
    counters: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    selected: list[RetrievalPTLItemContract] = field(default_factory=list)
    rejected: list[RetrievalPTLItemContract] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        if not self.name:
            raise ValueError("name is required")
        status = str(self.status or "").strip().lower()
        if status not in {"ok", "skipped", "error"}:
            raise ValueError("status must be ok, skipped, or error")
        self.status = status
        self.reason_codes = [str(item or "").strip() for item in list(self.reason_codes or []) if str(item or "").strip()]
        self.counters = dict(self.counters or {})
        self.details = dict(self.details or {})
        self.selected = list(self.selected or [])[:10]
        self.rejected = list(self.rejected or [])[:10]


@dataclass(slots=True)
class RetrievalPTLAnnContract:
    """Bounded ANN telemetry block for PTL traces."""

    enabled: bool = False
    used: bool = False
    candidate_count: int = 0
    latency_ms: float = 0.0
    fallback_reason: str = ""
    store_fingerprint: str = ""
    backend_version: str = ""

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.used = bool(self.used)
        self.candidate_count = max(0, int(self.candidate_count or 0))
        value = float(self.latency_ms or 0.0)
        if not math.isfinite(value):
            raise ValueError("latency_ms must be finite")
        self.latency_ms = max(0.0, value)
        self.fallback_reason = str(self.fallback_reason or "").strip()
        self.store_fingerprint = str(self.store_fingerprint or "").strip()
        self.backend_version = str(self.backend_version or "").strip()


@dataclass(slots=True)
class RetrievalPTLSummaryContract:
    """Eval-only benchmark overlay attached after retrieval execution."""

    gold_source_ids: list[str] = field(default_factory=list)
    ranked_source_ids_top10: list[str] = field(default_factory=list)
    gold_source_present_in_store: bool = False
    gold_source_shortlisted: bool = False
    source_recall_at_5: float = 0.0
    source_recall_at_10: float = 0.0
    miss_family_hint: str = "unknown"

    def __post_init__(self) -> None:
        self.gold_source_ids = [str(item or "").strip() for item in list(self.gold_source_ids or []) if str(item or "").strip()]
        self.ranked_source_ids_top10 = [str(item or "").strip() for item in list(self.ranked_source_ids_top10 or []) if str(item or "").strip()][:10]
        self.gold_source_present_in_store = bool(self.gold_source_present_in_store)
        self.gold_source_shortlisted = bool(self.gold_source_shortlisted)
        for key in ("source_recall_at_5", "source_recall_at_10"):
            value = float(getattr(self, key) or 0.0)
            if not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
            setattr(self, key, max(0.0, min(1.0, value)))
        self.miss_family_hint = str(self.miss_family_hint or "unknown").strip() or "unknown"


@dataclass(slots=True)
class RetrievalPTLTraceContract:
    """Bounded retrieval-only PTL artifact for benchmark diagnostics."""

    trace_version: str = "ptl_min_v1"
    case_id: str = ""
    question_id: str = ""
    profile_requested: str = ""
    profile_used: str = ""
    query_text_preview: str = ""
    query_hash: str = ""
    timestamp_utc: Optional[datetime] = None
    trace_scope: str = "retrieval_only"
    ann: RetrievalPTLAnnContract = field(default_factory=RetrievalPTLAnnContract)
    stage_order: list[str] = field(default_factory=list)
    stages: list[RetrievalPTLStageContract] = field(default_factory=list)
    summary: RetrievalPTLSummaryContract = field(default_factory=RetrievalPTLSummaryContract)

    def __post_init__(self) -> None:
        self.trace_version = str(self.trace_version or "").strip() or "ptl_min_v1"
        if self.trace_version != "ptl_min_v1":
            raise ValueError("trace_version must be ptl_min_v1")
        self.case_id = str(self.case_id or "").strip()
        self.question_id = str(self.question_id or "").strip()
        self.profile_requested = str(self.profile_requested or "").strip()
        self.profile_used = str(self.profile_used or "").strip()
        preview = str(self.query_text_preview or "")
        self.query_text_preview = preview[:157] + "..." if len(preview) > 160 else preview
        self.query_hash = str(self.query_hash or "").strip()
        if self.timestamp_utc is None:
            self.timestamp_utc = datetime.now(timezone.utc)
        self.trace_scope = str(self.trace_scope or "").strip() or "retrieval_only"
        if self.trace_scope != "retrieval_only":
            raise ValueError("trace_scope must be retrieval_only")
        self.stage_order = [str(item or "").strip() for item in list(self.stage_order or []) if str(item or "").strip()]
        self.stages = list(self.stages or [])
        if not isinstance(self.ann, RetrievalPTLAnnContract):
            raise ValueError("ann must be RetrievalPTLAnnContract")
        if not isinstance(self.summary, RetrievalPTLSummaryContract):
            raise ValueError("summary must be RetrievalPTLSummaryContract")


@dataclass(slots=True)
class RetrievalOverrideRequestContract:
    """Internal-only retrieval override request used by debug/eval callers."""

    query: str
    invoker: str
    reason: str
    scope: str
    auth_context: str

    def __post_init__(self) -> None:
        self.query = str(self.query or "").strip()
        self.invoker = str(self.invoker or "").strip()
        self.reason = str(self.reason or "").strip()
        self.scope = str(self.scope or "").strip()
        self.auth_context = str(self.auth_context or "").strip()
        if not self.query:
            raise ValueError("query is required")
        if not self.invoker:
            raise ValueError("invoker is required")
        if not self.reason:
            raise ValueError("reason is required")
        if not self.scope:
            raise ValueError("scope is required")
        if not self.auth_context:
            raise ValueError("auth_context is required")


@dataclass(slots=True)
class RetrievalOverrideAuditContract:
    """Audit record for requested retrieval override behavior."""

    requested: bool = False
    allowed: bool = False
    applied: bool = False
    invoker: str = ""
    reason: str = ""
    scope: str = ""
    auth_context: str = ""
    denied_reason: str = ""
    requested_query_tokens: int = 0

    def __post_init__(self) -> None:
        for key in ("requested", "allowed", "applied"):
            value = getattr(self, key)
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be bool")
        self.invoker = str(self.invoker or "").strip()
        self.reason = str(self.reason or "").strip()
        self.scope = str(self.scope or "").strip()
        self.auth_context = str(self.auth_context or "").strip()
        self.denied_reason = str(self.denied_reason or "").strip()
        self.requested_query_tokens = int(self.requested_query_tokens)
        if self.requested_query_tokens < 0:
            raise ValueError("requested_query_tokens must be >= 0")


@dataclass(slots=True)
class MemoryPack:
    """Structured set of evidence returned by retrieval."""

    core: list[MemoryPackItem] = field(default_factory=list)
    context: list[MemoryPackItem] = field(default_factory=list)
    conflict: list[MemoryPackItem] = field(default_factory=list)
    continuity: list[MemoryPackItem] = field(default_factory=list)
    efficiency: Optional[EfficiencyMetricsContract] = None
    pack_confidence: float = 0.0

    def __post_init__(self) -> None:
        """Validate memory-pack confidence range."""

        if self.pack_confidence < 0.0 or self.pack_confidence > 1.0:
            raise ValueError("pack_confidence must be in [0, 1]")
        if self.efficiency is not None and not isinstance(self.efficiency, EfficiencyMetricsContract):
            raise ValueError("efficiency must be EfficiencyMetricsContract when provided")


def _encode_value(value: Any) -> Any:
    """Recursively encode dataclass payloads for JSON compatibility."""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_encode_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode_value(v) for k, v in value.items()}
    return value


def contract_to_dict(obj: Any) -> dict[str, Any]:
    """Convert contract dataclass object into a JSON-serializable dict."""

    return _encode_value(asdict(obj))


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse nullable datetime values from strings or datetime objects."""

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def source_ref_from_dict(payload: dict[str, Any]) -> SourceRef:
    """Build SourceRef from dictionary payload."""

    return SourceRef(
        source_id=str(payload.get("source_id", "")),
        message_id=payload.get("message_id"),
        timestamp=_parse_dt(payload.get("timestamp")),
        span_start=payload.get("span_start"),
        span_end=payload.get("span_end"),
    )


def candidate_atom_from_dict(payload: dict[str, Any]) -> CandidateAtom:
    """Build CandidateAtom from dictionary payload."""

    refs = [source_ref_from_dict(item) for item in payload.get("source_refs", [])]
    return CandidateAtom(
        candidate_id=str(payload.get("candidate_id", "")),
        atom_type=AtomType(str(payload.get("atom_type", "episode"))),
        canonical_text=str(payload.get("canonical_text", "")),
        source_refs=refs,
        entities=[str(v) for v in payload.get("entities", [])],
        topics=[str(v) for v in payload.get("topics", [])],
        confidence=float(payload.get("confidence", 0.0)),
        salience=float(payload.get("salience", 0.0)),
    )


def efficiency_metrics_from_dict(payload: dict[str, Any]) -> EfficiencyMetricsContract:
    """Build additive efficiency metrics contract from dictionary payload."""

    return EfficiencyMetricsContract(
        latency_p50_ms=float(payload.get("latency_p50_ms", 0.0)),
        latency_p95_ms=float(payload.get("latency_p95_ms", 0.0)),
        tokens_prompt_avg=float(payload.get("tokens_prompt_avg", 0.0)),
        tokens_completion_avg=float(payload.get("tokens_completion_avg", 0.0)),
        tokens_total_avg=float(payload.get("tokens_total_avg", 0.0)),
        retrieval_fanout_avg=float(payload.get("retrieval_fanout_avg", 0.0)),
        retrieval_fanout_p95=float(payload.get("retrieval_fanout_p95", 0.0)),
    )


def memory_pack_from_items(
    core: Iterable[MemoryPackItem],
    *,
    context: Iterable[MemoryPackItem] = (),
    conflict: Iterable[MemoryPackItem] = (),
    continuity: Iterable[MemoryPackItem] = (),
    pack_confidence: float,
    efficiency: Optional[EfficiencyMetricsContract] = None,
) -> MemoryPack:
    """Create a MemoryPack from section iterables."""

    return MemoryPack(
        core=list(core),
        context=list(context),
        conflict=list(conflict),
        continuity=list(continuity),
        efficiency=efficiency,
        pack_confidence=pack_confidence,
    )
