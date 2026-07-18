from __future__ import annotations

import pytest

from engine.memory.content_safety import SecretDetectedError, assert_safe_content, scrub_content


@pytest.mark.parametrize(
    "value",
    (
        {"api_key": "short-value"},
        {"Authorization": "Bearer abcdefghijklmnop"},
    ),
)
def test_sensitive_mapping_keys_and_bearer_credentials_are_rejected(value) -> None:
    with pytest.raises(SecretDetectedError):
        assert_safe_content(value)


def test_scrub_redacts_values_owned_by_sensitive_mapping_keys() -> None:
    assert scrub_content(
        {
            "api_key": "short-value",
            "Authorization": "Bearer abcdefghijklmnop",
            "safe": "keep me",
        }
    ) == {
        "api_key": "[REDACTED_LEGACY_SECRET]",
        "Authorization": "[REDACTED_LEGACY_SECRET]",
        "safe": "keep me",
    }
