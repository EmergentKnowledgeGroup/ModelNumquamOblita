from __future__ import annotations

from datetime import timezone

import pytest

from engine.ingest.parser import ConversationIngestor, noise_reason, normalize_role, normalize_timestamp


def test_normalize_role_maps_expected_values() -> None:
    assert normalize_role("Assistant") == "assistant"
    assert normalize_role("human") == "user"
    assert normalize_role("developer") == "developer"
    assert normalize_role("weird") is None


def test_normalize_timestamp_supports_iso_and_epoch() -> None:
    dt_iso = normalize_timestamp("2026-02-08T05:00:00Z")
    assert dt_iso is not None
    assert dt_iso.tzinfo == timezone.utc

    dt_epoch = normalize_timestamp(1739000000)
    assert dt_epoch is not None
    assert dt_epoch.tzinfo == timezone.utc

    dt_ms = normalize_timestamp(1739000000000)
    assert dt_ms is not None
    assert dt_ms.tzinfo == timezone.utc

    assert normalize_timestamp("not-a-timestamp") is None


def test_normalize_timestamp_rejects_naive_values_unless_policy_is_explicit() -> None:
    assert normalize_timestamp("2026-02-08T05:00:00") is None
    assumed = normalize_timestamp("2026-02-08T05:00:00", naive_policy="assume_utc")
    assert assumed is not None
    assert assumed.tzinfo == timezone.utc


def test_normalize_timestamp_validates_policy_before_handling_input() -> None:
    with pytest.raises(ValueError, match="naive_policy"):
        normalize_timestamp(None, naive_policy="local_machine")


def test_noise_reason_detects_preface_and_tool_payload() -> None:
    preface = "Make sure to include `【message_idx†source】` markers to provide citations based on this file"
    assert noise_reason(preface, role="assistant") == "preface_blob"
    assert noise_reason('{\"updates\":[{\"pattern\":\".\"}]}', role="tool") == "tool_payload"
    assert noise_reason("hello", role="assistant") is None


def test_conversation_ingestor_preserves_quote_text_except_newlines() -> None:
    convo = {
        "id": "conv-q1",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "text": "  Keep the spacing.\r\nAnd keep this line too.  ",
            }
        ],
    }

    result = list(ConversationIngestor().iter_turns_from_conversation(convo))

    turn, reason = result[0]
    assert reason is None
    assert turn is not None
    assert turn.text == "Keep the spacing.\nAnd keep this line too."
    assert turn.quote_text == "  Keep the spacing.\nAnd keep this line too.  "
    assert turn.sequence_index == 0
