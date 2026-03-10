from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from ..config import GateThresholds
from ..contracts import CandidateAtom, WriteAction, WriteDecision
from .prefilter import clamp01, provenance_trust


@dataclass(slots=True)
class StageBContext:
    """Context signals for Stage-B judgment decisions."""

    existing_atom_id: str | None = None
    conflict_risk: float = 0.0
    recurrence: float = 0.0
    novelty: float = 0.0
    identity_relevance: float = 0.0


@dataclass(slots=True)
class StageBJudgment:
    """Adapter output schema for Stage-B decisions."""

    action: WriteAction
    confidence: float
    reason_code: str
    score_breakdown: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {
            WriteAction.ADD,
            WriteAction.UPDATE,
            WriteAction.IGNORE,
            WriteAction.PROPOSE_EDIT,
            WriteAction.PROPOSE_DELETE,
        }
        if self.action not in allowed:
            raise ValueError("unsupported Stage-B action")
        if not self.reason_code.strip():
            raise ValueError("reason_code is required")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")


class JudgmentAdapter(Protocol):
    """Adapter interface for Stage-B write judgments."""

    def judge(self, candidate: CandidateAtom, context: StageBContext) -> StageBJudgment:
        """Produce Stage-B action proposal for one candidate."""


@dataclass(slots=True)
class DeterministicJudgmentAdapter:
    """Offline deterministic Stage-B adapter for local testing."""

    thresholds: GateThresholds = field(default_factory=GateThresholds)

    def judge(self, candidate: CandidateAtom, context: StageBContext) -> StageBJudgment:
        trust = provenance_trust(candidate.source_refs)
        conflict_risk = clamp01(context.conflict_risk)
        identity = clamp01(context.identity_relevance)
        novelty = clamp01(context.novelty)
        recurrence = clamp01(context.recurrence)
        score = clamp01(0.45 * candidate.confidence + 0.35 * trust + 0.20 * novelty)

        if trust < self.thresholds.min_trust:
            action = WriteAction.IGNORE
            reason = "B_LOW_TRUST"
        elif conflict_risk >= 0.90 and context.existing_atom_id:
            action = WriteAction.PROPOSE_DELETE
            reason = "B_HIGH_CONFLICT_DELETE_REVIEW"
        elif conflict_risk >= 0.70 and context.existing_atom_id:
            action = WriteAction.PROPOSE_EDIT
            reason = "B_CONFLICT_EDIT_REVIEW"
        elif score >= self.thresholds.add_threshold and identity >= self.thresholds.min_identity_relevance:
            action = WriteAction.ADD
            reason = "B_HIGH_CONFIDENCE_ADD"
        elif score >= self.thresholds.update_threshold and recurrence >= 0.20:
            action = WriteAction.UPDATE
            reason = "B_REINFORCE_UPDATE"
        else:
            action = WriteAction.IGNORE
            reason = "B_LOW_SIGNAL"

        return StageBJudgment(
            action=action,
            confidence=score,
            reason_code=reason,
            score_breakdown={
                "score": score,
                "trust": trust,
                "conflict_risk": conflict_risk,
                "identity_relevance": identity,
                "novelty": novelty,
                "recurrence": recurrence,
            },
        )


@dataclass(slots=True)
class StageBDecisionRecord:
    """Auditable Stage-B decision with adapter score traces."""

    candidate_id: str
    action: WriteAction
    reason_code: str
    confidence: float
    timestamp: datetime
    score_breakdown: dict[str, float]
    adapter_name: str


@dataclass(slots=True)
class StageBWriteGate:
    """Stage-B write gate wrapper over a pluggable judgment adapter."""

    adapter: JudgmentAdapter
    decision_log: list[StageBDecisionRecord] = field(default_factory=list)

    def evaluate(self, candidate: CandidateAtom, *, context: StageBContext) -> WriteDecision:
        judgment = self.adapter.judge(candidate, context)
        decision = WriteDecision(
            candidate_id=candidate.candidate_id,
            action=judgment.action,
            confidence=judgment.confidence,
            reason_code=judgment.reason_code,
            gate_stage="B",
        )
        self.decision_log.append(
            StageBDecisionRecord(
                candidate_id=candidate.candidate_id,
                action=judgment.action,
                reason_code=judgment.reason_code,
                confidence=judgment.confidence,
                timestamp=datetime.now(timezone.utc),
                score_breakdown=dict(judgment.score_breakdown),
                adapter_name=type(self.adapter).__name__,
            )
        )
        return decision
