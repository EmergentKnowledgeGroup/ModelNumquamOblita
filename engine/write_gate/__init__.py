"""Stage-A write gate exports."""

from .prefilter import (
    DEFAULT_BOILERPLATE_PATTERNS,
    DEFAULT_CALLBACK_PATTERNS,
    SalienceFeatures,
    candidate_signature,
    clamp01,
    extract_salience_features,
    prefilter_score,
    provenance_trust,
    signature_from_fields,
    source_ref_signature,
)
from .stage_a import StageADecisionRecord, StageAWriteGate, build_signature_index
from .stage_b import (
    DeterministicJudgmentAdapter,
    JudgmentAdapter,
    StageBContext,
    StageBDecisionRecord,
    StageBJudgment,
    StageBWriteGate,
)

__all__ = [
    "DEFAULT_BOILERPLATE_PATTERNS",
    "DEFAULT_CALLBACK_PATTERNS",
    "SalienceFeatures",
    "StageADecisionRecord",
    "StageAWriteGate",
    "StageBContext",
    "StageBDecisionRecord",
    "StageBJudgment",
    "StageBWriteGate",
    "build_signature_index",
    "candidate_signature",
    "clamp01",
    "extract_salience_features",
    "prefilter_score",
    "provenance_trust",
    "signature_from_fields",
    "source_ref_signature",
    "DeterministicJudgmentAdapter",
    "JudgmentAdapter",
]
