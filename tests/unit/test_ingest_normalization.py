from __future__ import annotations

from datetime import timezone

from engine.ingest.parser import noise_reason, normalize_role, normalize_timestamp


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


def test_noise_reason_detects_preface_and_tool_payload() -> None:
    preface = "Make sure to include `【message_idx†source】` markers to provide citations based on this file"
    assert noise_reason(preface, role="assistant") == "preface_blob"
    assert noise_reason('{\"updates\":[{\"pattern\":\".\"}]}', role="tool") == "tool_payload"
    assert noise_reason("hello", role="assistant") is None
