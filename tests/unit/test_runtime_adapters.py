from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import AdapterRegistry, NanobotAdapter, OpenClawAdapter, ReferenceChatAdapter, RuntimeSession


def _candidate(candidate_id: str, text: str, source_id: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_msg",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=["adapter"],
        confidence=0.88,
        salience=0.7,
    )


def _runtime() -> RuntimeSession:
    store = AtomStore()
    store.add_candidate(_candidate("a1", "You said tea helps focus.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    return RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
    )


def test_adapter_registry_register_and_lookup() -> None:
    registry = AdapterRegistry()
    adapter = ReferenceChatAdapter()
    registry.register(adapter)
    assert registry.get("reference") is adapter
    assert "reference" in registry.names()


def test_reference_adapter_normalizes_message_payload() -> None:
    adapter = ReferenceChatAdapter()
    adapted = adapter.normalize_request({"message": "  hello memory  ", "high_risk": True, "metadata": {"id": "x"}})
    assert adapted.message == "hello memory"
    assert adapted.high_risk is True
    assert adapted.metadata == {"id": "x"}


def test_reference_adapter_uses_latest_user_message() -> None:
    adapter = ReferenceChatAdapter()
    adapted = adapter.normalize_request(
        {
            "messages": [
                {"role": "assistant", "content": "ready"},
                {"role": "user", "content": [{"text": "first"}, {"text": "second"}]},
            ]
        }
    )
    assert adapted.message == "first\nsecond"


def test_reference_adapter_rejects_missing_message() -> None:
    adapter = ReferenceChatAdapter()
    with pytest.raises(ValueError, match="message is required"):
        adapter.normalize_request({"messages": [{"role": "assistant", "content": "no user"}]})


def test_reference_adapter_formats_runtime_trace() -> None:
    runtime = _runtime()
    try:
        trace = runtime.handle_turn("what did i say?")
        payload = ReferenceChatAdapter().format_response(trace, runtime)
        assert payload["ok"] is True
        assert payload["adapter"] == "reference"
        assert payload["turn"]["turn_id"] == trace.turn_id
    finally:
        runtime.close()


def test_openclaw_adapter_normalizes_messages_and_risk_level() -> None:
    adapter = OpenClawAdapter()
    adapted = adapter.normalize_request(
        {
            "messages": [
                {"role": "assistant", "content": "ready"},
                {"role": "user", "content": "Remember tea continuity."},
            ],
            "risk_level": "high",
            "metadata": {"session_id": "s1"},
        }
    )
    assert adapted.message == "Remember tea continuity."
    assert adapted.high_risk is True
    assert adapted.metadata == {"session_id": "s1"}


def test_openclaw_adapter_rejects_missing_messages() -> None:
    with pytest.raises(ValueError, match="messages array is required"):
        OpenClawAdapter().normalize_request({"message": "fallback not allowed"})


def test_openclaw_adapter_formats_chat_completion_shape() -> None:
    runtime = _runtime()
    try:
        trace = runtime.handle_turn("What do you remember?")
        payload = OpenClawAdapter().format_response(trace, runtime)
        assert payload["object"] == "chat.completion"
        assert payload["adapter"] == "openclaw"
        assert payload["choices"][0]["message"]["role"] == "assistant"
        assert payload["usage"]["total_tokens"] >= payload["usage"]["prompt_tokens"]
        assert payload["memory"]["decision"] in {"PASS", "CLARIFY", "ABSTAIN"}
    finally:
        runtime.close()


def test_nanobot_adapter_normalizes_query_and_safety() -> None:
    adapter = NanobotAdapter()
    adapted = adapter.normalize_request(
        {
            "query": "remember this thread",
            "meta": {"conversation_id": "conv-x"},
            "safety": {"high_risk": True},
        }
    )
    assert adapted.message == "remember this thread"
    assert adapted.high_risk is True
    assert adapted.metadata == {"conversation_id": "conv-x"}


def test_nanobot_adapter_rejects_missing_query() -> None:
    with pytest.raises(ValueError, match="query is required"):
        NanobotAdapter().normalize_request({"messages": [{"role": "assistant", "content": "no user"}]})


def test_nanobot_adapter_formats_expected_shape() -> None:
    runtime = _runtime()
    try:
        trace = runtime.handle_turn("what did i say about tea?")
        payload = NanobotAdapter().format_response(trace, runtime)
        assert payload["ok"] is True
        assert payload["adapter"] == "nanobot"
        assert payload["trace_id"] == trace.turn_id
        assert isinstance(payload["answer"], str) and payload["answer"]
        assert payload["usage"]["total_tokens"] >= payload["usage"]["prompt_tokens"]
        assert payload["memory"]["confidence"] == trace.pack_confidence
    finally:
        runtime.close()


def test_reference_adapter_formats_context_package_shape() -> None:
    runtime = _runtime()
    try:
        package = runtime.build_context_package("Remember the tea preference.")
        payload = ReferenceChatAdapter().format_context_package(package, runtime)
        assert payload["ok"] is True
        assert payload["adapter"] == "reference"
        assert payload["model"] == runtime.model_name
        assert payload["context_package"]["package_version"] == "v1"
    finally:
        runtime.close()


def test_openclaw_adapter_formats_context_package_shape() -> None:
    runtime = _runtime()
    try:
        package = runtime.build_context_package("Remember tea continuity.")
        payload = OpenClawAdapter().format_context_package(package, runtime)
        assert payload["object"] == "memory.context_package"
        assert payload["adapter"] == "openclaw"
        assert payload["model"] == runtime.model_name
        assert payload["context_package"]["package_version"] == "v1"
    finally:
        runtime.close()


def test_nanobot_adapter_formats_context_package_shape() -> None:
    runtime = _runtime()
    try:
        package = runtime.build_context_package("Remember tea continuity.")
        payload = NanobotAdapter().format_context_package(package, runtime)
        assert payload["ok"] is True
        assert payload["adapter"] == "nanobot"
        assert payload["model"] == runtime.model_name
        assert payload["context_package"]["package_version"] == "v1"
    finally:
        runtime.close()
