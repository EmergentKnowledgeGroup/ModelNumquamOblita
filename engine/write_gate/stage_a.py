from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping

from ..config import GateThresholds
from ..contracts import CandidateAtom, WriteAction, WriteDecision
from .prefilter import (
    candidate_signature,
    clamp01,
    extract_salience_features,
    prefilter_score,
    provenance_trust,
    source_ref_signature,
)


def build_signature_index(candidates: Iterable[CandidateAtom]) -> dict[str, set[str]]:
    """Build duplicate index keyed by candidate signature and evidence refs."""

    index: dict[str, set[str]] = {}
    for candidate in candidates:
        signature = candidate_signature(candidate)
        refs = {source_ref_signature(ref) for ref in candidate.source_refs}
        if signature in index:
            index[signature].update(refs)
        else:
            index[signature] = refs
    return index


@dataclass(slots=True)
class StageADecisionRecord:
    """Auditable Stage-A decision entry with score breakdown."""

    candidate_id: str
    action: WriteAction
    reason_code: str
    confidence: float
    timestamp: datetime
    score_breakdown: dict[str, float]
    signature: str


@dataclass(slots=True)
class StageAWriteGate:
    """Deterministic Stage-A write gate that filters low-value memory writes."""

    thresholds: GateThresholds = field(default_factory=GateThresholds)
    decision_log: list[StageADecisionRecord] = field(default_factory=list)

    def evaluate(
        self,
        candidate: CandidateAtom,
        *,
        known_signature_index: Mapping[str, set[str]] | None = None,
    ) -> WriteDecision:
        """Evaluate one candidate and return deterministic Stage-A decision."""

        known_index = known_signature_index or {}
        signature = candidate_signature(candidate)
        evidence_signatures = {source_ref_signature(ref) for ref in candidate.source_refs}
        features = extract_salience_features(candidate)
        score = prefilter_score(features)
        trust = provenance_trust(candidate.source_refs)

        if features.is_boilerplate and not features.callback_hit:
            action = WriteAction.IGNORE
            reason = "A_BOILERPLATE_NOISE"
        elif trust < self.thresholds.min_trust:
            action = WriteAction.IGNORE
            reason = "A_LOW_TRUST_PROVENANCE"
        elif signature in known_index:
            known_refs = known_index[signature]
            if evidence_signatures and evidence_signatures.issubset(known_refs):
                action = WriteAction.IGNORE
                reason = "A_DUPLICATE_NO_NEW_EVIDENCE"
            else:
                action = WriteAction.UPDATE
                reason = "A_DUPLICATE_WITH_NEW_EVIDENCE"
        elif features.callback_hit and trust >= self.thresholds.min_trust:
            action = WriteAction.ADD
            reason = "A_CALLBACK_RESCUE"
        elif score >= self.thresholds.stage_a_add_floor and candidate.salience >= self.thresholds.min_salience:
            action = WriteAction.ADD
            reason = "A_HIGH_VALUE_ADD"
        elif score >= self.thresholds.update_threshold and features.identity_relevance >= self.thresholds.min_identity_relevance:
            action = WriteAction.UPDATE
            reason = "A_REINFORCE_CANDIDATE"
        else:
            action = WriteAction.IGNORE
            reason = "A_LOW_SIGNAL"

        confidence = self._decision_confidence(
            candidate_confidence=candidate.confidence,
            score=score,
            trust=trust,
            recurrence=features.recurrence,
            action=action,
        )

        decision = WriteDecision(
            candidate_id=candidate.candidate_id,
            action=action,
            confidence=confidence,
            reason_code=reason,
            gate_stage="A",
        )
        self.decision_log.append(
            StageADecisionRecord(
                candidate_id=candidate.candidate_id,
                action=action,
                reason_code=reason,
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
                score_breakdown={
                    "prefilter_score": score,
                    "trust": trust,
                    "emotional_intensity": features.emotional_intensity,
                    "identity_relevance": features.identity_relevance,
                    "specificity": features.specificity,
                    "recurrence": features.recurrence,
                },
                signature=signature,
            )
        )
        return decision

    def _decision_confidence(
        self,
        *,
        candidate_confidence: float,
        score: float,
        trust: float,
        recurrence: float,
        action: WriteAction,
    ) -> float:
        base = clamp01(0.55 * candidate_confidence + 0.25 * score + 0.20 * trust)
        if action is WriteAction.IGNORE:
            base = min(base, 0.74)
        if recurrence < 0.34:
            base = min(base, self.thresholds.max_confidence_without_recurrence)
        if action is WriteAction.UPDATE and score > self.thresholds.update_threshold:
            base = min(0.90, base + 0.05)
        return clamp01(base)
