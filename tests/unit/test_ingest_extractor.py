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


def test_extractor_emits_candidate_for_explicit_memory_cue_turn() -> None:
    extractor = DeterministicCandidateExtractor()

    candidates = extractor.extract_turn(
        _turn("user", "Please remember the launch rollback drill and keep the orange binder with the checklist.")
    )

    assert len(candidates) == 1
    assert candidates[0].confidence >= 0.52
    assert candidates[0].canonical_text.startswith("Please remember the launch rollback drill")


def test_extractor_skips_structured_payload_and_short_text() -> None:
    extractor = DeterministicCandidateExtractor()

    assert extractor.extract_turn(_turn("assistant", '{"updates":[{"pattern":"."}]}')) == []
    assert extractor.extract_turn(_turn("assistant", "ok")) == []
    assert extractor.extract_turn(_turn("tool", "I remember this")) == []
