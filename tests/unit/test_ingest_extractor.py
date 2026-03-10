from __future__ import annotations

from datetime import datetime, timezone

from engine.contracts import NormalizedTurn
from engine.ingest import DeterministicCandidateExtractor


def _turn(role: str, text: str, message_id: str = "m1") -> NormalizedTurn:
    return NormalizedTurn(
        source_id="conv_1",
        conversation_id="conv_1",
        message_id=message_id,
        role=role,
        text=text,
        timestamp=datetime.now(timezone.utc),
    )


def test_extractor_emits_deterministic_candidate_for_high_signal_turn() -> None:
    extractor = DeterministicCandidateExtractor()
    turn = _turn("assistant", "I remember this clearly and I trust you, and we should keep this memory safe.")

    first = extractor.extract_turn(turn)
    second = extractor.extract_turn(turn)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].candidate_id == second[0].candidate_id
    assert first[0].canonical_text == second[0].canonical_text
    assert first[0].confidence >= 0.52


def test_extractor_skips_structured_payload_and_short_text() -> None:
    extractor = DeterministicCandidateExtractor()

    assert extractor.extract_turn(_turn("assistant", '{"updates":[{"pattern":"."}]}')) == []
    assert extractor.extract_turn(_turn("assistant", "ok")) == []
    assert extractor.extract_turn(_turn("tool", "I remember this")) == []
