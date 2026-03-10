from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


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
        confidence=0.86,
        salience=0.7,
    )


def _json_get(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_post_error(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _extract_memory_contract(adapter: str, response: dict) -> dict:
    if adapter == "reference":
        turn = dict(response.get("turn") or {})
        return {
            "session_id": turn.get("session_id"),
            "decision": turn.get("decision"),
            "citations": turn.get("citations"),
            "pack_confidence": turn.get("pack_confidence"),
            "retrieved_atom_ids": turn.get("retrieved_atom_ids"),
            "memory_mode": turn.get("memory_mode"),
            "memory_route": turn.get("memory_route"),
            "route_reason": turn.get("route_reason"),
            "route_reason_text": turn.get("route_reason_text"),
            "retrieval_passes": turn.get("retrieval_passes"),
            "retrieval_query_tokens": turn.get("retrieval_query_tokens"),
            "retrieval_stop_reason": turn.get("retrieval_stop_reason"),
            "short_term_hits": turn.get("short_term_hits"),
            "memory_cards": turn.get("memory_cards"),
            "budget": turn.get("budget"),
            "writeback_event_id": turn.get("writeback_event_id"),
        }
    return dict(response.get("memory") or {})


def _assert_memory_contract(memory: dict, *, session_id: str) -> None:
    required_keys = {
        "session_id",
        "decision",
        "citations",
        "pack_confidence",
        "retrieved_atom_ids",
        "memory_mode",
        "memory_route",
        "route_reason",
        "route_reason_text",
        "retrieval_passes",
        "retrieval_query_tokens",
        "retrieval_stop_reason",
        "short_term_hits",
        "memory_cards",
        "budget",
        "writeback_event_id",
    }
    missing = sorted(required_keys.difference(memory.keys()))
    assert not missing, f"missing memory contract keys: {missing}"
    assert memory["session_id"] == session_id
    assert str(memory["decision"]) in {"PASS", "ABSTAIN", "CLARIFY"}
    assert isinstance(memory["citations"], list)
    assert isinstance(memory["retrieved_atom_ids"], list)
    assert str(memory["memory_mode"]) in {"none", "stm_primary", "hybrid", "ltm_only"}
    assert str(memory["memory_route"]) in {"none", "stm_only", "ltm_light", "ltm_deep"}
    assert isinstance(memory["route_reason"], str) and memory["route_reason"]
    assert isinstance(memory["route_reason_text"], str) and memory["route_reason_text"]
    assert isinstance(memory["retrieval_passes"], int)
    assert isinstance(memory["retrieval_query_tokens"], int)
    assert isinstance(memory["retrieval_stop_reason"], str) and memory["retrieval_stop_reason"]
    assert isinstance(memory["short_term_hits"], int)
    assert isinstance(memory["memory_cards"], list)
    assert isinstance(memory["budget"], dict)


def _adapter_chat_payload(adapter: str, *, message: str, session_id: str) -> dict:
    if adapter == "reference":
        return {
            "messages": [{"role": "user", "content": message}],
            "metadata": {"session_id": session_id},
        }
    if adapter == "openclaw":
        return {
            "messages": [{"role": "user", "content": message}],
            "metadata": {"session_id": session_id},
            "risk_level": "low",
        }
    if adapter == "nanobot":
        return {
            "query": message,
            "meta": {"conversation_id": session_id},
            "safety": {"high_risk": False},
        }
    raise AssertionError


def test_runtime_adapter_endpoint_reference_chat() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))

    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        adapters = _json_get(f"{base}/api/adapters")
        assert adapters["ok"] is True
        assert "reference" in adapters["adapters"]
        assert "openclaw" in adapters["adapters"]
        assert "nanobot" in adapters["adapters"]

        chat = _json_post(
            f"{base}/api/adapters/reference/chat",
            {
                "messages": [{"role": "user", "content": "What do you remember about tea?"}],
                "metadata": {"session_id": "s-reference"},
            },
        )
        assert chat["ok"] is True
        assert chat["adapter"] == "reference"
        assert chat["turn"]["turn_id"].startswith("turn_")
        assert chat["turn"]["session_id"] == "s-reference"
        assert isinstance(chat["turn"]["route_reason_text"], str) and chat["turn"]["route_reason_text"]
        assert isinstance(chat["turn"]["retrieval_query_tokens"], int)
        assert chat["turn"]["budget"]["warning_state"] in {"ok", "warn"}

        context_package = _json_post(
            f"{base}/api/adapters/reference/context-package",
            {
                "messages": [{"role": "user", "content": "What do you remember about tea?"}],
                "metadata": {"session_id": "s-reference"},
            },
        )
        assert context_package["ok"] is True
        assert context_package["adapter"] == "reference"
        assert context_package["context_package"]["package_version"] == "v1"
        assert "preview" in context_package["context_package"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_adapter_endpoint_openclaw_shape() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))

    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        chat = _json_post(
            f"{base}/api/adapters/openclaw/chat",
            {
                "messages": [
                    {"role": "system", "content": "stay grounded"},
                    {"role": "user", "content": "What do you remember?"},
                ],
                "risk_level": "low",
                "metadata": {"session_id": "s-openclaw"},
            },
        )
        assert chat["object"] == "chat.completion"
        assert chat["adapter"] == "openclaw"
        assert chat["choices"][0]["message"]["role"] == "assistant"
        assert chat["usage"]["total_tokens"] >= chat["usage"]["prompt_tokens"]
        assert chat["memory"]["decision"] in {"PASS", "CLARIFY", "ABSTAIN"}
        assert chat["memory"]["memory_mode"] in {"none", "stm_primary", "hybrid", "ltm_only"}
        assert chat["memory"]["memory_route"] in {"none", "stm_only", "ltm_light", "ltm_deep"}
        assert isinstance(chat["memory"]["route_reason"], str) and chat["memory"]["route_reason"]
        assert isinstance(chat["memory"]["route_reason_text"], str) and chat["memory"]["route_reason_text"]
        assert isinstance(chat["memory"]["retrieval_passes"], int)
        assert isinstance(chat["memory"]["retrieval_query_tokens"], int)
        assert isinstance(chat["memory"]["retrieval_stop_reason"], str) and chat["memory"]["retrieval_stop_reason"]
        assert isinstance(chat["memory"]["short_term_hits"], int)
        assert chat["memory"]["session_id"] == "s-openclaw"
        assert isinstance(chat["memory"]["memory_cards"], list)
        assert chat["memory"]["budget"]["warning_state"] in {"ok", "warn"}

        context_package = _json_post(
            f"{base}/api/adapters/openclaw/context-package",
            {
                "messages": [
                    {"role": "system", "content": "stay grounded"},
                    {"role": "user", "content": "What do you remember?"},
                ],
                "risk_level": "low",
                "metadata": {"session_id": "s-openclaw"},
            },
        )
        assert context_package["object"] == "memory.context_package"
        assert context_package["adapter"] == "openclaw"
        assert context_package["context_package"]["package_version"] == "v1"
        assert "working_set" in context_package["context_package"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_adapter_endpoint_nanobot_shape() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))

    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        chat = _json_post(
            f"{base}/api/adapters/nanobot/chat",
            {
                "query": "What do you remember about tea?",
                "meta": {"conversation_id": "nano-1"},
                "safety": {"high_risk": False},
            },
        )
        assert chat["ok"] is True
        assert chat["adapter"] == "nanobot"
        assert chat["trace_id"].startswith("turn_")
        assert isinstance(chat["answer"], str) and chat["answer"]
        assert chat["usage"]["total_tokens"] >= chat["usage"]["prompt_tokens"]
        assert "confidence" in chat["memory"]
        assert chat["memory"]["memory_mode"] in {"none", "stm_primary", "hybrid", "ltm_only"}
        assert chat["memory"]["memory_route"] in {"none", "stm_only", "ltm_light", "ltm_deep"}
        assert isinstance(chat["memory"]["route_reason"], str) and chat["memory"]["route_reason"]
        assert isinstance(chat["memory"]["route_reason_text"], str) and chat["memory"]["route_reason_text"]
        assert isinstance(chat["memory"]["retrieval_passes"], int)
        assert isinstance(chat["memory"]["retrieval_query_tokens"], int)
        assert isinstance(chat["memory"]["retrieval_stop_reason"], str) and chat["memory"]["retrieval_stop_reason"]
        assert isinstance(chat["memory"]["short_term_hits"], int)
        assert chat["memory"]["session_id"] == "nano-1"
        assert isinstance(chat["memory"]["memory_cards"], list)
        assert chat["memory"]["budget"]["warning_state"] in {"ok", "warn"}

        context_package = _json_post(
            f"{base}/api/adapters/nanobot/context-package",
            {
                "query": "What do you remember about tea?",
                "meta": {"conversation_id": "nano-1"},
                "safety": {"high_risk": False},
            },
        )
        assert context_package["ok"] is True
        assert context_package["adapter"] == "nanobot"
        assert context_package["context_package"]["package_version"] == "v1"
        assert "ltm_query_plan" in context_package["context_package"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_adapter_endpoint_rejects_unknown_adapter() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status, payload = _json_post_error(f"{base}/api/adapters/not-real/chat", {"message": "x"})
        assert status == 404
        assert "unknown adapter" in payload["error"]
        status_ctx, payload_ctx = _json_post_error(
            f"{base}/api/adapters/not-real/context-package",
            {"message": "x"},
        )
        assert status_ctx == 404
        assert "unknown adapter" in payload_ctx["error"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_adapter_endpoint_rejects_invalid_payload() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status, payload = _json_post_error(
            f"{base}/api/adapters/reference/chat",
            {"messages": [{"role": "assistant", "content": "no user turn"}]},
        )
        assert status == 400
        assert payload["error"] == "message is required"
        status_ctx, payload_ctx = _json_post_error(
            f"{base}/api/adapters/reference/context-package",
            {"messages": [{"role": "assistant", "content": "no user turn"}]},
        )
        assert status_ctx == 400
        assert payload_ctx["error"] == "message is required"

        status_ref_meta, payload_ref_meta = _json_post_error(
            f"{base}/api/adapters/reference/chat",
            {"message": "hello", "metadata": "not-an-object"},
        )
        assert status_ref_meta == 400
        assert payload_ref_meta["error"] == "metadata must be an object when provided"

        status_openclaw_msgs, payload_openclaw_msgs = _json_post_error(
            f"{base}/api/adapters/openclaw/chat",
            {"messages": "invalid"},
        )
        assert status_openclaw_msgs == 400
        assert payload_openclaw_msgs["error"] == "messages array is required"

        status_openclaw_meta, payload_openclaw_meta = _json_post_error(
            f"{base}/api/adapters/openclaw/context-package",
            {
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": "invalid",
            },
        )
        assert status_openclaw_meta == 400
        assert payload_openclaw_meta["error"] == "metadata must be an object when provided"

        status_nanobot_meta, payload_nanobot_meta = _json_post_error(
            f"{base}/api/adapters/nanobot/chat",
            {"query": "hello", "meta": "invalid"},
        )
        assert status_nanobot_meta == 400
        assert payload_nanobot_meta["error"] == "meta/metadata must be an object when provided"

        status_nanobot_query, payload_nanobot_query = _json_post_error(
            f"{base}/api/adapters/nanobot/context-package",
            {"messages": [{"role": "assistant", "content": "no user text"}]},
        )
        assert status_nanobot_query == 400
        assert payload_nanobot_query["error"] == "query is required"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_adapter_context_package_sanitizes_internal_error() -> None:
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )

    def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("internal-sensitive-detail")

    runtime.build_context_package = _boom  # type: ignore[assignment]
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status, payload = _json_post_error(
            f"{base}/api/adapters/reference/context-package",
            {"messages": [{"role": "user", "content": "remember this"}]},
        )
        assert status == 500
        assert payload["error"] == "adapter context package failed"
        assert "internal-sensitive-detail" not in payload["error"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_adapter_endpoint_memory_contract_parity() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "You prefer tea in late sessions.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))

    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    adapters = ("reference", "openclaw", "nanobot")

    try:
        for adapter in adapters:
            session_id = f"parity-{adapter}"
            payload = _adapter_chat_payload(
                adapter,
                message="What do you remember about tea preferences?",
                session_id=session_id,
            )
            response = _json_post(f"{base}/api/adapters/{adapter}/chat", payload)
            contract = _extract_memory_contract(adapter, response)
            _assert_memory_contract(contract, session_id=session_id)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_runtime_adapter_endpoints_keep_thread_local_reference_in_long_sessions() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "Project Atlas has milestone alpha and one blocker.", "conv_1"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))

    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        short_term_primary_score=0.35,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    adapters = ("reference", "openclaw", "nanobot")

    try:
        for adapter in adapters:
            session_id = f"thread-{adapter}"
            first_payload = _adapter_chat_payload(
                adapter,
                message="Project Atlas has milestone alpha and one blocker.",
                session_id=session_id,
            )
            second_payload = _adapter_chat_payload(
                adapter,
                message="Continue this thread and summarize the Project Atlas blocker.",
                session_id=session_id,
            )
            _json_post(f"{base}/api/adapters/{adapter}/chat", first_payload)
            second = _json_post(f"{base}/api/adapters/{adapter}/chat", second_payload)
            memory = _extract_memory_contract(adapter, second)
            _assert_memory_contract(memory, session_id=session_id)
            assert memory["memory_route"] == "stm_only"
            assert memory["route_reason"] == "thread_local_reference"
            assert int(memory["short_term_hits"]) >= 1
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
