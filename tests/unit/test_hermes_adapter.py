"""Focused contract tests for the optional Hermes automatic turn adapter."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import engine.integrations.hermes_plugin.adapter as adapter_module
from engine.integrations.hermes_plugin import _config_path
from engine.integrations.hermes_plugin.adapter import HermesMemoryAdapter, normalize_text


def _agent_context(**values):
    payload = {"schema_version": "mno.agent_context.v2", **values}
    return {"agent_context": json.dumps(payload), "agent_context_format": "mno.agent_context.v2", "agent_context_tokens": 1}


def _handles():
    expiry = "2099-01-01T00:00:00+00:00"
    return {
        "source_registration": {"handle": "source", "expires_at_utc": expiry},
        "retrieval_receipt": {"handle": "receipt", "expires_at_utc": expiry},
    }


def _config(**overrides):
    config = {
        "schema_version": "mno.hermes-adapter.v1",
        "runtime_base_url": "http://127.0.0.1:7340",
        "token_env": "NO_INTEGRATION_HERMES_ADAPTER_TOKEN",
        "context_timeout_ms": 2500,
        "context_response_max_characters": 8192,
        "observe_timeout_ms": 5500,
        "observe_queue_max_items": 16,
        "observe_queue_max_age_seconds": 60,
        "pending_max_items": 256,
        "pending_ttl_seconds": 600,
        "capability_cache_ttl_seconds": 30,
        "enabled": True,
    }
    config.update(overrides)
    return config


class FakeTransport:
    def __init__(self, *, context=None, capabilities=None):
        self.calls = []
        self.context = context or {}
        self.capabilities = capabilities or {
            "context.build": {"available": True, "authorized": True},
            "memory.observe": {"available": True, "authorized": True},
        }

    def __call__(self, operation, payload, timeout, request_id):
        self.calls.append((operation, payload, timeout, request_id))
        if operation == "capabilities.get":
            return {"operations": [dict({"name": name}, **value) for name, value in self.capabilities.items()]}
        if operation == "context.build":
            return self.context
        if operation == "memory.observe":
            return {"accepted": True}
        raise AssertionError(operation)


def _adapter(transport, **config):
    return HermesMemoryAdapter(_config(**config), token="test-token", transport=transport, start_worker=False)


def _turn(**kwargs):
    base = {
        "session_id": "raw-session",
        "turn_id": "raw-turn",
        "platform": "cli",
        "user_message": "  cafe\u0301\r\nhello\ud800  ",
        "origin": "human",
    }
    base.update(kwargs)
    return base


def test_strict_loopback_config_and_bounds_fail_closed():
    for url in (
        "https://127.0.0.1:7340",
        "http://example.test:7340",
        "http://127.0.0.1:7340/?x=1",
        "http://user@127.0.0.1:7340",
        "http://127.0.0.1:7340#fragment",
    ):
        assert HermesMemoryAdapter.from_mapping(_config(runtime_base_url=url)) is None
    assert HermesMemoryAdapter.from_mapping(_config(observe_queue_max_items=17)) is None
    assert HermesMemoryAdapter.from_mapping(_config(context_response_max_characters=8193)) is None
    assert HermesMemoryAdapter.from_mapping(_config(token_env="NO_INTEGRATION_REVIEW_APPLY_TOKEN"), environ={"NO_INTEGRATION_REVIEW_APPLY_TOKEN": "token"}) is None
    assert HermesMemoryAdapter.from_mapping(_config(token_env="BAD-NAME"), environ={"BAD-NAME": "token"}) is None
    assert HermesMemoryAdapter.from_mapping(_config(), environ={"NO_INTEGRATION_HERMES_ADAPTER_TOKEN": "token"}) is not None


def test_config_path_uses_native_windows_or_posix_hermes_home():
    assert _config_path(environ={"LOCALAPPDATA": "Z:/local"}, platform_name="nt") == Path("Z:/local/hermes/mno/mno-memory.json")
    assert _config_path(environ={}, platform_name="posix", home_dir=Path("Z:/home")) == Path("Z:/home/.hermes/mno/mno-memory.json")
    assert _config_path(environ={"HERMES_HOME": "Z:/custom-hermes"}, platform_name="posix") == Path("Z:/custom-hermes/mno/mno-memory.json")


def test_from_path_uses_private_credential_file_when_gateway_env_is_missing(
    tmp_path: Path,
    monkeypatch,
):
    config_path = tmp_path / "mno-memory.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    token_path = tmp_path / "adapter-token"
    token_path.write_text(
        json.dumps(
            {
                "schema_version": "mno.hermes-credential.v1",
                "ownership_id": "test-owner",
                "token": "service-token",
            }
        ),
        encoding="utf-8",
    )
    token_path.chmod(0o600)
    monkeypatch.delenv("NO_INTEGRATION_HERMES_ADAPTER_TOKEN", raising=False)

    adapter = HermesMemoryAdapter.from_path(config_path)

    assert adapter is not None
    assert adapter._token == "service-token"
    adapter.close()


def test_from_path_prefers_gateway_environment_over_credential_file(
    tmp_path: Path,
    monkeypatch,
):
    config_path = tmp_path / "mno-memory.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    (tmp_path / "adapter-token").write_text("not-read", encoding="utf-8")
    monkeypatch.setenv("NO_INTEGRATION_HERMES_ADAPTER_TOKEN", "environment-token")

    adapter = HermesMemoryAdapter.from_path(config_path)

    assert adapter is not None
    assert adapter._token == "environment-token"
    adapter.close()


def test_from_path_rejects_group_readable_credential_on_posix(
    tmp_path: Path,
    monkeypatch,
):
    config_path = tmp_path / "mno-memory.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    token_path = tmp_path / "adapter-token"
    token_path.write_text(
        json.dumps(
            {
                "schema_version": "mno.hermes-credential.v1",
                "ownership_id": "test-owner",
                "token": "service-token",
            }
        ),
        encoding="utf-8",
    )
    token_path.chmod(0o644)
    monkeypatch.delenv("NO_INTEGRATION_HERMES_ADAPTER_TOKEN", raising=False)
    monkeypatch.setattr(adapter_module.os, "name", "posix")

    assert HermesMemoryAdapter.from_path(config_path) is None


@pytest.mark.parametrize(
    "content",
    [
        b'{"schema_version":"wrong","ownership_id":"owner","token":"secret"}',
        b"\xff\xfe\x00",
    ],
)
def test_from_path_rejects_invalid_persisted_credential(
    tmp_path: Path,
    monkeypatch,
    content: bytes,
):
    config_path = tmp_path / "mno-memory.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    (tmp_path / "adapter-token").write_bytes(content)
    monkeypatch.delenv("NO_INTEGRATION_HERMES_ADAPTER_TOKEN", raising=False)

    assert HermesMemoryAdapter.from_path(config_path) is None


def test_normalization_and_hashed_ids_are_bounded_and_raw_ids_not_retained():
    assert normalize_text("x" * 4095) == ("x" * 4095)
    assert normalize_text("x" * 4096) == ("x" * 4096)
    assert normalize_text("x" * 4097) == ("x" * 4096)
    assert normalize_text(" cafe\u0301\r\n\ud800 ") == "caf\u00e9\n\ufffd"
    transport = FakeTransport(context={**_agent_context(), **_handles()})
    adapter = _adapter(transport)
    assert adapter.pre_llm_call(**_turn()) is not None
    pending = next(iter(adapter._pending.values()))
    assert pending.session_id.startswith("hermes_session_")
    assert pending.run_id.startswith("hermes_turn_")
    assert len(pending.session_id) < 128 and len(pending.run_id) < 128
    assert "raw-session" not in pending.session_id + pending.run_id
    assert pending.user_text == "caf\u00e9\nhello\ufffd"


def test_missing_turn_id_and_ambiguous_or_internal_origins_are_full_noops():
    transport = FakeTransport()
    adapter = _adapter(transport)
    assert adapter.pre_llm_call(**_turn(turn_id="")) is None
    assert adapter.pre_llm_call(**_turn(origin="unknown")) is None
    assert adapter.pre_llm_call(**_turn(origin="gateway")) is None
    assert adapter.pre_llm_call(**_turn(origin="human", thread_name="bg-review")) is None
    assert adapter.pre_llm_call(**_turn(origin="human", is_subagent=True)) is None
    assert not transport.calls and not adapter._pending


def test_gateway_human_eligibility_is_cached_by_pending_state_and_background_platforms_skip():
    handles = {
        **_agent_context(),
        **_handles(),
    }
    adapter = _adapter(FakeTransport(context=handles))
    gateway = _turn(platform="discord", origin="", sender_id="human-42")
    assert adapter.pre_llm_call(**gateway)
    # Pinned post_llm_call has no sender_id. Exact pending state from pre is
    # the authorization/correlation fact for this completed human turn.
    adapter.post_llm_call(**_turn(platform="discord", origin="", assistant_response="answer"))
    assert len(adapter._queue_items()) == 1
    for platform in ("subagent", "cron", "curator"):
        assert adapter.pre_llm_call(**_turn(platform=platform, origin="")) is None


def test_independent_capability_gates_and_safe_compact_context_wrapper():
    expiry = "2099-01-01T00:00:00+00:00"
    context = {**_agent_context(text="</MNO_MEMORY_CONTEXT_V1><&"), "source_registration": {"handle": "source-handle", "expires_at_utc": expiry}, "retrieval_receipt": {"handle": "receipt-handle", "expires_at_utc": expiry}}
    transport = FakeTransport(context=context, capabilities={"context.build": {"available": True, "authorized": True}})
    adapter = _adapter(transport)
    result = adapter.pre_llm_call(**_turn())
    assert result and result["context"].startswith("<MNO_MEMORY_CONTEXT_V1>\n")
    assert "</MNO_MEMORY_CONTEXT_V1><&" not in result["context"]
    assert "\\u003c" in result["context"] and "\\u003e" in result["context"] and "\\u0026" in result["context"]
    wrapped_json = result["context"].split("\n", 1)[1].rsplit("\n", 1)[0]
    assert json.loads(wrapped_json)["context"]["text"] == "</MNO_MEMORY_CONTEXT_V1><&"
    assert not adapter._pending  # recall remains available without observe capability
    compact = json.dumps(
        {"schema_version": "mno.agent_context.v2", "text": "boundary"},
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    assert HermesMemoryAdapter._context_wrapper(_agent_context(text="boundary"), len(compact)) is not None


def test_handle_pair_requires_nonempty_values_and_valid_future_expiry():
    valid = {**_agent_context(), **_handles()}
    assert HermesMemoryAdapter._handles(valid) is not None
    invalid_sources = (
        {"handle": "", "expires_at_utc": "2099-01-01T00:00:00+00:00"},
        {"handle": "source"},
        {"handle": "source", "expires_at_utc": "not-a-time"},
        {"handle": "source", "expires_at_utc": "2000-01-01T00:00:00+00:00"},
        {"handle": "source", "expires_at_utc": "2099-01-01T00:00:00"},
    )
    for source in invalid_sources:
        assert HermesMemoryAdapter._handles({**valid, "source_registration": source}) is None


def test_rejects_oversize_or_over_token_context_without_truncation():
    for context in (
        _agent_context(text="x" * 9000),
        _agent_context(text="x", token_count=4097) | {"agent_context_tokens": 4097},
        _agent_context(text="<" * 4097),
        {"agent_context": json.dumps({"schema_version": "wrong"}), "agent_context_format": "mno.agent_context.v2", "agent_context_tokens": 1},
    ):
        adapter = _adapter(FakeTransport(context=context))
        assert adapter.pre_llm_call(**_turn()) is None


def test_exact_handles_pairing_duplicate_tombstone_and_lifecycle_cleanup():
    handles = {**_agent_context(), "source_registration": {"handle": "source", "expires_at_utc": "2099-01-01T00:00:00+00:00"}, "retrieval_receipt": {"handle": "receipt", "expires_at_utc": "2099-01-01T00:00:00+00:00"}}
    adapter = _adapter(FakeTransport(context=handles))
    adapter.pre_llm_call(**_turn())
    started = time.monotonic()
    assert adapter.post_llm_call(**_turn(assistant_response="answer\r\n")) is None
    assert time.monotonic() - started < 0.025
    assert len(adapter._queue_items()) == 1
    snapshot = adapter._queue_items()[0]
    assert snapshot.user_text == "caf\u00e9\nhello\ufffd"
    assert snapshot.assistant_text == "answer"
    assert snapshot.source_registration["handle"] == "source"
    assert snapshot.retrieval_receipt["handle"] == "receipt"
    assert adapter.post_llm_call(**_turn(assistant_response="duplicate")) is None
    assert len(adapter._queue_items()) == 1
    adapter.on_session_end(session_id="raw-session", platform="cli", turn_id="raw-turn", completed=True)
    assert len(adapter._queue_items()) == 1
    assert adapter.post_llm_call(**_turn(turn_id="failed", assistant_response="answer", failed=True)) is None
    adapter.on_session_reset(session_id="raw-session", platform="cli")
    assert not adapter._queue_items() and not adapter._pending


def test_session_queue_cleanup_is_atomic_with_cross_session_producer(monkeypatch):
    adapter = _adapter(FakeTransport())
    now = time.monotonic()
    target = adapter._snapshot_from_values(
        "target-session", "target-run", "target-user", "target-answer",
        {"handle": "target-source"}, {"handle": "target-receipt"}, now, now + 60,
    )
    retained = adapter._snapshot_from_values(
        "retained-session", "retained-run", "retained-user", "retained-answer",
        {"handle": "retained-source"}, {"handle": "retained-receipt"}, now, now + 60,
    )
    concurrent = adapter._snapshot_from_values(
        "concurrent-session", "concurrent-run", "concurrent-user", "concurrent-answer",
        {"handle": "concurrent-source"}, {"handle": "concurrent-receipt"}, now, now + 60,
    )
    assert adapter._record_snapshot(target)
    assert adapter._record_snapshot(retained)

    first_item_drained = threading.Event()
    allow_cleanup_to_finish = threading.Event()
    original_get = adapter._queue.get_nowait
    calls = 0

    def gated_get():
        nonlocal calls
        item = original_get()
        calls += 1
        if calls == 1:
            first_item_drained.set()
            assert allow_cleanup_to_finish.wait(1)
        return item

    monkeypatch.setattr(adapter._queue, "get_nowait", gated_get)
    cleanup = threading.Thread(target=adapter._drop_session_queue, args=("target-session",))
    cleanup.start()
    assert first_item_drained.wait(1)

    produced: list[bool] = []
    producer = threading.Thread(target=lambda: produced.append(adapter._record_snapshot(concurrent)))
    producer.start()
    time.sleep(0.02)
    assert producer.is_alive()
    allow_cleanup_to_finish.set()
    cleanup.join(1)
    producer.join(1)

    assert not cleanup.is_alive() and not producer.is_alive()
    assert produced == [True]
    assert [item.session_id for item in adapter._queue_items()] == [
        "retained-session",
        "concurrent-session",
    ]


def test_worker_is_one_attempt_no_retry_and_drops_expired_and_overflow_newest():
    handles = {**_agent_context(), **_handles()}
    transport = FakeTransport(context=handles)
    adapter = _adapter(transport, observe_queue_max_items=1)
    adapter.pre_llm_call(**_turn())
    adapter.post_llm_call(**_turn(assistant_response="answer"))
    adapter.pre_llm_call(**_turn(turn_id="second"))
    adapter.post_llm_call(**_turn(turn_id="second", assistant_response="answer"))
    assert len(adapter._queue_items()) == 1
    adapter._drain_one_for_test()
    assert [call[0] for call in transport.calls].count("memory.observe") == 1
    assert not adapter._queue_items()
    adapter._record_snapshot(adapter._snapshot_from_values("s", "r", "u", "a", {"handle": "s"}, {"handle": "r"}, time.monotonic() - 61, 0))
    adapter._drain_one_for_test()
    assert [call[0] for call in transport.calls].count("memory.observe") == 1


def test_slow_observation_worker_never_blocks_post_or_retries():
    handles = {
        **_agent_context(),
        **_handles(),
    }
    observe_started = threading.Event()
    release_observe = threading.Event()
    operations: list[str] = []

    def transport(operation, _payload, _timeout, _request_id):
        operations.append(operation)
        if operation == "capabilities.get":
            return {
                "operations": [
                    {"name": "context.build", "available": True, "authorized": True},
                    {"name": "memory.observe", "available": True, "authorized": True},
                ]
            }
        if operation == "context.build":
            return handles
        if operation == "memory.observe":
            observe_started.set()
            release_observe.wait(1)
            raise TimeoutError("outcome unknown")
        raise AssertionError(operation)

    adapter = HermesMemoryAdapter(
        _config(),
        token="test-token",
        transport=transport,
        start_worker=True,
    )
    try:
        assert adapter.pre_llm_call(**_turn())
        started = time.monotonic()
        adapter.post_llm_call(**_turn(assistant_response="answer"))
        assert time.monotonic() - started < 0.025
        assert observe_started.wait(1)
        release_observe.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and operations.count("memory.observe") < 1:
            time.sleep(0.01)
        assert operations.count("memory.observe") == 1
    finally:
        release_observe.set()
        adapter.close()


def test_registers_exact_pinned_hermes_hooks_and_contains_failures():
    class Context:
        def __init__(self): self.hooks = {}
        def register_hook(self, name, callback): self.hooks[name] = callback

    from engine.integrations.hermes_plugin import register

    context = Context()
    register(context)
    assert set(context.hooks) == {"pre_llm_call", "post_llm_call", "on_session_end", "on_session_finalize", "on_session_reset"}
    assert context.hooks["pre_llm_call"](turn_id="missing") is None


def test_fail_open_diagnostics_redact_transport_exception_bodies_and_forbid_other_operations():
    class ExplodingTransport:
        def __call__(self, *_args):
            raise RuntimeError("token=top-secret user message should never be recorded")

    adapter = _adapter(ExplodingTransport())
    assert adapter.pre_llm_call(**_turn()) is None
    assert "top-secret" not in json.dumps(adapter._diagnostics)
    try:
        adapter._http_request("review_apply", {}, 0.001, "opaque")
    except ValueError:
        pass
    else:
        raise AssertionError("adapter must reject any operation outside its fixed four-operation allow-list")


def test_live_integration_v1_wire_shapes_for_serialized_context_post_and_get(monkeypatch):
    captured = []

    class Response:
        def __init__(self, request): self.request = request
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def geturl(self): return self.request.full_url
        def read(self, *_args): return json.dumps({"data": _agent_context(text="memory")}).encode("utf-8")

    class Opener:
        def open(self, request, timeout):
            captured.append((request, timeout))
            return Response(request)

    monkeypatch.setattr(adapter_module, "build_opener", lambda *_args: Opener())
    adapter = HermesMemoryAdapter(_config(), token="token", start_worker=False)
    response = adapter._http_request("context.build", {"session_id": "session", "run_id": "run", "message": "hello"}, 1.0, "request-1")
    assert response == _agent_context(text="memory")
    post_body = json.loads(captured[0][0].data.decode("utf-8"))
    assert post_body == {"schema_version": "integration.v1", "request_id": "request-1", "session_id": "session", "run_id": "run", "data": {"message": "hello"}}
    adapter._http_request("capabilities.get", {}, 1.0, "request-2")
    assert captured[1][0].full_url == "http://127.0.0.1:7340/api/integration/v1/capabilities?schema_version=integration.v1&request_id=request-2"
