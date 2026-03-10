from __future__ import annotations

from datetime import datetime, timezone

from engine.contracts import AtomType, CandidateAtom, SourceRef, WriteAction
from engine.write_gate import StageAWriteGate, build_signature_index


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    message_id: str,
    confidence: float = 0.82,
    salience: float = 0.66,
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
        salience=salience,
    )


def test_stage_a_end_to_end_noise_rescue_and_duplicate_flow() -> None:
    gate = StageAWriteGate()
    initial = _candidate(
        candidate_id="cand_base",
        text="I remember this thread and I'll be here for continuity checks.",
        source_id="conv_1",
        message_id="m1",
        confidence=0.62,
        salience=0.18,
    )
    known_index = build_signature_index([initial])

    noisy = _candidate(
        candidate_id="cand_noise",
        text="Make sure to include citation markers and source references.",
        source_id="conv_noise",
        message_id="m1",
        confidence=0.95,
        salience=0.95,
    )
    exact_dup = _candidate(
        candidate_id="cand_dup_same",
        text=initial.canonical_text,
        source_id="conv_1",
        message_id="m1",
    )
    new_evidence_dup = _candidate(
        candidate_id="cand_dup_new",
        text=initial.canonical_text,
        source_id="conv_1",
        message_id="m2",
    )

    decisions = [
        gate.evaluate(noisy, known_signature_index=known_index),
        gate.evaluate(initial, known_signature_index={}),
        gate.evaluate(exact_dup, known_signature_index=known_index),
        gate.evaluate(new_evidence_dup, known_signature_index=known_index),
    ]

    assert decisions[0].action is WriteAction.IGNORE
    assert decisions[0].reason_code == "A_BOILERPLATE_NOISE"
    assert decisions[1].action is WriteAction.ADD
    assert decisions[1].reason_code == "A_CALLBACK_RESCUE"
    assert decisions[2].action is WriteAction.IGNORE
    assert decisions[2].reason_code == "A_DUPLICATE_NO_NEW_EVIDENCE"
    assert decisions[3].action is WriteAction.UPDATE
    assert decisions[3].reason_code == "A_DUPLICATE_WITH_NEW_EVIDENCE"
    assert len(gate.decision_log) == 4
