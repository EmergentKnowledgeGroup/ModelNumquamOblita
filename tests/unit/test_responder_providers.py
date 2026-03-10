from __future__ import annotations

import pytest

from engine.responder.providers import (
    LMStudioProvider,
    MockProvider,
    OpenAIChatCompletionsProvider,
    _extract_chat_text,
)


def test_extract_chat_text_supports_lmstudio_output_message() -> None:
    payload = {
        "output": [
            {"type": "reasoning", "content": "thinking"},
            {"type": "message", "content": "\n\nHello there"},
        ]
    }
    assert _extract_chat_text(payload).strip() == "Hello there"


def test_lmstudio_provider_messages_to_input_adds_assistant_marker() -> None:
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
    ]
    rendered = LMStudioProvider._messages_to_input(messages)
    assert "System:\nYou are helpful." in rendered
    assert "User:\nHi" in rendered
    assert rendered.endswith("Assistant:")


def test_mock_provider_uses_numbered_evidence_line() -> None:
    provider = MockProvider()
    out = provider.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "Service verdict (follow this): PASS\n"
                    "1. User: Tea helps focus during late sessions.\n"
                    "Sources: 67e5b719-09d4-8009-913e-c6e8d8c2a143#12"
                ),
            },
            {"role": "user", "content": "What do you remember about tea?"},
        ],
        model="mock-model",
    )
    assert "Tea helps focus during late sessions." in out.text


def test_lmstudio_provider_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError):
        LMStudioProvider(base_url="file:///etc/passwd")


def test_lmstudio_provider_rejects_missing_host() -> None:
    for url in ("http://", "http://user@", "http://:1234"):
        with pytest.raises(ValueError):
            LMStudioProvider(base_url=url)


def test_openai_provider_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError):
        OpenAIChatCompletionsProvider(
            base_url="file:///tmp/nope",
            api_key="test-key",
        )


def test_openai_provider_rejects_missing_host() -> None:
    for url in ("https://", "https://user@", "https://:443"):
        with pytest.raises(ValueError):
            OpenAIChatCompletionsProvider(
                base_url=url,
                api_key="test-key",
            )
