from __future__ import annotations

from datetime import datetime, timezone

from engine.config import GateThresholds
from engine.contracts import AtomType, CandidateAtom, SourceRef, WriteAction
from engine.write_gate import (
    DeterministicJudgmentAdapter,
    StageBContext,
    StageBWriteGate,
)


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    message_id: str | None = "m1",
    confidence: float = 0.82,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=message_id,
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=["continuity"],
        confidence=confidence,
        salience=0.65,
    )


def test_stage_b_low_trust_ignores_candidate() -> None:
    candidate = CandidateAtom(
        candidate_id="cand_low_trust",
        atom_type=AtomType.EPISODE,
        canonical_text="memory with weak provenance",
        source_refs=[SourceRef(source_id="conv_only")],
        entities=["user"],
        topics=["continuity"],
        confidence=0.95,
        salience=0.7,
    )
    adapter = DeterministicJudgmentAdapter(thresholds=GateThresholds(min_trust=0.6))
    gate = StageBWriteGate(adapter=adapter)

    decision = gate.evaluate(candidate, context=StageBContext(identity_relevance=0.8, novelty=0.8, recurrence=0.8))

    assert decision.action is WriteAction.IGNORE
    assert decision.reason_code == "B_LOW_TRUST"
    assert decision.gate_stage == "B"


def test_stage_b_conflict_routes_to_review_actions() -> None:
    adapter = DeterministicJudgmentAdapter()
    gate = StageBWriteGate(adapter=adapter)
    candidate = _candidate(
        candidate_id="cand_conflict",
        text="This directly contradicts prior core memory.",
        source_id="conv_conflict",
    )

    edit_decision = gate.evaluate(
        candidate,
        context=StageBContext(existing_atom_id="mem_1", conflict_risk=0.75, novelty=0.5, identity_relevance=0.5),
    )
    delete_decision = gate.evaluate(
        candidate,
        context=StageBContext(existing_atom_id="mem_1", conflict_risk=0.95, novelty=0.5, identity_relevance=0.5),
    )

    assert edit_decision.action is WriteAction.PROPOSE_EDIT
    assert edit_decision.reason_code == "B_CONFLICT_EDIT_REVIEW"
    assert delete_decision.action is WriteAction.PROPOSE_DELETE
    assert delete_decision.reason_code == "B_HIGH_CONFLICT_DELETE_REVIEW"


def test_stage_b_add_and_update_paths_and_logging() -> None:
    adapter = DeterministicJudgmentAdapter(
        thresholds=GateThresholds(add_threshold=0.60, update_threshold=0.45, min_identity_relevance=0.20)
    )
    gate = StageBWriteGate(adapter=adapter)
    candidate = _candidate(
        candidate_id="cand_add_update",
        text="We established continuity and verified supporting evidence.",
        source_id="conv_add",
        confidence=0.9,
    )

    add_decision = gate.evaluate(
        candidate,
        context=StageBContext(identity_relevance=0.8, novelty=0.7, recurrence=0.6, conflict_risk=0.1),
    )
    update_decision = gate.evaluate(
        candidate,
        context=StageBContext(identity_relevance=0.1, novelty=0.6, recurrence=0.9, conflict_risk=0.1),
    )

    assert add_decision.action is WriteAction.ADD
    assert update_decision.action is WriteAction.UPDATE
    assert len(gate.decision_log) == 2
    assert gate.decision_log[-1].adapter_name == "DeterministicJudgmentAdapter"
