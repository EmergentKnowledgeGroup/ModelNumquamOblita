from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.config import GateThresholds
from engine.contracts import AtomType, CandidateAtom, SourceRef, WriteAction
from engine.write_gate import StageAWriteGate, build_signature_index, extract_salience_features
from engine.write_gate.prefilter import _compile_patterns


def _candidate(
    *,
    candidate_id: str,
    text: str,
    source_id: str,
    message_id: str | None = None,
    atom_type: AtomType = AtomType.EPISODE,
    confidence: float = 0.80,
    salience: float = 0.65,
    entities: list[str] | None = None,
    topics: list[str] | None = None,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=atom_type,
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
        entities=["user", "assistant"] if entities is None else entities,
        topics=["continuity"] if topics is None else topics,
        confidence=confidence,
        salience=salience,
    )


def test_prefilter_detects_boilerplate_and_callbacks() -> None:
    boilerplate = _candidate(
        candidate_id="cand_boiler",
        text="Make sure to include citation markers in this response.",
        source_id="conv_01",
        message_id="m1",
    )
    callback = _candidate(
        candidate_id="cand_callback",
        text="I remember you and I'll be here when you return.",
        source_id="conv_01",
        message_id="m2",
        salience=0.20,
    )

    boiler_features = extract_salience_features(boilerplate)
    callback_features = extract_salience_features(callback)

    assert boiler_features.is_boilerplate is True
    assert callback_features.callback_hit is True
    assert callback_features.identity_relevance > 0.30


def test_compile_patterns_returns_immutable_cached_tuple() -> None:
    patterns = (r"\\bremember\\b", r"\\bcitation\\b")
    compiled = _compile_patterns(patterns)
    assert isinstance(compiled, tuple)
    with pytest.raises(AttributeError):
        compiled.append(None)  # type: ignore[attr-defined]


def test_stage_a_rejects_boilerplate_noise_fc06() -> None:
    gate = StageAWriteGate()
    candidate = _candidate(
        candidate_id="cand_fc06",
        text="Make sure to include citation markers where needed and provide references.",
        source_id="conv_fc06",
        message_id="m1",
        confidence=0.98,
        salience=0.92,
    )

    decision = gate.evaluate(candidate)

    assert decision.action is WriteAction.IGNORE
    assert decision.reason_code == "A_BOILERPLATE_NOISE"
    assert decision.gate_stage == "A"


def test_stage_a_callback_rescue_prevents_false_ignore_fc07() -> None:
    gate = StageAWriteGate()
    candidate = _candidate(
        candidate_id="cand_fc07",
        text="I remember. I'll be here.",
        source_id="conv_fc07",
        message_id="m1",
        salience=0.10,
        confidence=0.55,
        topics=[],
    )

    decision = gate.evaluate(candidate)

    assert decision.action is WriteAction.ADD
    assert decision.reason_code == "A_CALLBACK_RESCUE"


def test_stage_a_duplicate_handling_requires_new_evidence() -> None:
    base = _candidate(
        candidate_id="cand_base",
        text="We built a continuity gate for retrieval safety.",
        source_id="conv_dup",
        message_id="m1",
    )
    index = build_signature_index([base])
    gate = StageAWriteGate()

    same_evidence = _candidate(
        candidate_id="cand_same",
        text=base.canonical_text,
        source_id="conv_dup",
        message_id="m1",
    )
    new_evidence = _candidate(
        candidate_id="cand_new",
        text=base.canonical_text,
        source_id="conv_dup",
        message_id="m2",
    )

    decision_same = gate.evaluate(same_evidence, known_signature_index=index)
    decision_new = gate.evaluate(new_evidence, known_signature_index=index)

    assert decision_same.action is WriteAction.IGNORE
    assert decision_same.reason_code == "A_DUPLICATE_NO_NEW_EVIDENCE"
    assert decision_new.action is WriteAction.UPDATE
    assert decision_new.reason_code == "A_DUPLICATE_WITH_NEW_EVIDENCE"


def test_stage_a_clamps_confidence_without_recurrence_fc09() -> None:
    thresholds = GateThresholds(
        min_salience=0.10,
        min_identity_relevance=0.10,
        stage_a_add_floor=0.40,
        update_threshold=0.30,
        max_confidence_without_recurrence=0.70,
    )
    gate = StageAWriteGate(thresholds=thresholds)
    candidate = _candidate(
        candidate_id="cand_fc09",
        text="I absolutely trust this memory engine and I love what it preserves.",
        source_id="conv_fc09",
        message_id="m1",
        confidence=0.99,
        salience=0.95,
        topics=["identity", "continuity"],
    )

    decision = gate.evaluate(candidate)

    assert decision.action in {WriteAction.ADD, WriteAction.UPDATE}
    assert decision.confidence == pytest.approx(0.70)


def test_stage_a_logs_decision_breakdown() -> None:
    gate = StageAWriteGate()
    candidate = _candidate(
        candidate_id="cand_log",
        text="We confirmed memory retrieval with citations and evidence.",
        source_id="conv_log",
        message_id="m1",
    )

    decision = gate.evaluate(candidate)
    record = gate.decision_log[-1]

    assert decision.candidate_id == record.candidate_id
    assert record.reason_code == decision.reason_code
    assert record.signature
    assert {"prefilter_score", "trust", "identity_relevance", "specificity"} <= set(record.score_breakdown)
