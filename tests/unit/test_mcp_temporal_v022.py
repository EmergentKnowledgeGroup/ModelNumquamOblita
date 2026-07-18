from __future__ import annotations

from typing import Any

import pytest

from engine.mcp.server import AuthConfig, MCPRequestError, MCPServer, ServerConfig, _redact_stdio_trace_payload


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request_json(self, method, path, *, query, payload, headers, allow_error_status):
        self.calls.append({"method": method, "path": path, "payload": payload, "headers": headers})
        return 200, {"ok": True, "operation": "memory.temporal", "data": {}}


def test_v022_mcp_temporal_tools_have_exact_names_permissions_and_http_parity_shape() -> None:
    client = _Client()
    server = MCPServer(
        config=ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="operator")),
        api_client=client,
    )
    expected = {
        "integration.memory.temporal.schedule": "operator",
        "integration.memory.temporal.list": "viewer",
        "integration.memory.temporal.get": "viewer",
        "integration.memory.temporal.resolve": "operator",
    }
    assert {name: server._tools[name].permission for name in expected} == expected

    server._tool_integration_memory_temporal_schedule(
        {
            "session_id": "s", "run_id": "r", "idempotency_key": "idem_schedule", "temporal_request": {"relative_duration": {"amount": 1, "unit": "days"}},
            "original_expression": "tomorrow", "source_content": "Follow up tomorrow.", "source_role": "user", "source_registration": {"handle": "src_handle"},
        }
    )
    server._tool_integration_memory_temporal_list({"due_only": True, "include_upcoming": False, "limit": 3})
    server._tool_integration_memory_temporal_get({"record_id": "prov_record"})
    server._tool_integration_memory_temporal_resolve(
        {"record_id": "prov_record", "action": "cancel", "expected_revision": 1, "idempotency_key": "idem_resolve"}
    )

    assert [call["path"] for call in client.calls] == [
        "/api/integration/v1/memory/temporal/schedule",
        "/api/integration/v1/memory/temporal/list",
        "/api/integration/v1/memory/temporal/get",
        "/api/integration/v1/memory/temporal/resolve",
    ]
    assert client.calls[0]["headers"]["Idempotency-Key"] == "idem_schedule"
    assert client.calls[3]["headers"]["Idempotency-Key"] == "idem_resolve"
    assert client.calls[0]["payload"]["data"] == {
        "temporal_request": {"relative_duration": {"amount": 1, "unit": "days"}},
        "original_expression": "tomorrow",
        "source_content": "Follow up tomorrow.",
        "source_role": "user",
        "source_registration": {"handle": "src_handle"},
        "temporal_kind": "reminder",
    }
    assert client.calls[1]["payload"]["data"] == {"due_only": True, "include_upcoming": False, "limit": 3}
    assert client.calls[2]["payload"]["data"] == {"record_id": "prov_record"}
    assert client.calls[3]["payload"]["data"] == {
        "record_id": "prov_record",
        "action": "cancel",
        "expected_revision": 1,
    }


def test_v022_mcp_temporal_list_enforces_bounded_poll_limit() -> None:
    server = MCPServer(
        config=ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer")),
        api_client=_Client(),
    )

    for invalid in (0, 9, True):
        with pytest.raises(MCPRequestError, match="limit must be an integer from 1 to 8"):
            server._tool_integration_memory_temporal_list({"limit": invalid})


def test_stdio_trace_redacts_camel_case_secret_keys_recursively() -> None:
    redacted = _redact_stdio_trace_payload(
        {"apiKey": "alpha", "nested": {"clientSecret": "beta", "authToken": "gamma"}}
    )

    assert redacted == {
        "apiKey": "[REDACTED]",
        "nested": {"clientSecret": "[REDACTED]", "authToken": "[REDACTED]"},
    }
