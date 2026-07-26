from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from engine.runtime import server as runtime_server
from engine.runtime.server import IntegrationAuthManager, IntegrationContractError, _integration_require_role


def test_retrieval_override_from_payload_does_not_promote_raw_query_when_override_object_is_empty() -> None:
    override = runtime_server._retrieval_override_from_payload(
        {"retrieval_override": {}, "retrieval_query": "force anchor"},
        default_invoker="engine.runtime.server.api.chat",
        default_scope="runtime_api_chat",
        default_reason="api_requested_override",
        default_auth_context="runtime_api_chat",
    )
    assert override is None


def test_retrieval_override_from_payload_ignores_caller_auth_context() -> None:
    override = runtime_server._retrieval_override_from_payload(
        {
            "retrieval_override": {
                "query": "force anchor",
                "invoker": "custom.invoker",
                "reason": "custom_reason",
                "scope": "custom_scope",
                "auth_context": "spoofed",
            }
        },
        default_invoker="engine.runtime.server.api.chat",
        default_scope="runtime_api_chat",
        default_reason="api_requested_override",
        default_auth_context="runtime_api_chat",
    )
    assert override is not None
    assert override.query == "force anchor"
    assert override.invoker == "custom.invoker"
    assert override.reason == "custom_reason"
    assert override.scope == "custom_scope"
    assert override.auth_context == "runtime_api_chat"


def test_integration_auth_blocks_default_tokens_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_INTEGRATION_RUNTIME_MODE", "production")
    monkeypatch.setenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", raising=False)
    monkeypatch.delenv("NO_INTEGRATION_TOKENS_FILE", raising=False)
    monkeypatch.delenv("NO_INTEGRATION_SECRET_MANAGER_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="default integration tokens are forbidden in production mode"):
        IntegrationAuthManager.from_env()


def test_integration_auth_requires_command_in_production_command_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_INTEGRATION_RUNTIME_MODE", "production")
    monkeypatch.setenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", raising=False)
    monkeypatch.setenv("NO_INTEGRATION_SECRET_MANAGER_PROVIDER", "command")
    monkeypatch.delenv("NO_INTEGRATION_SECRET_MANAGER_COMMAND", raising=False)
    monkeypatch.delenv("NO_INTEGRATION_TOKENS_FILE", raising=False)
    with pytest.raises(ValueError, match="requires NO_INTEGRATION_SECRET_MANAGER_COMMAND"):
        IntegrationAuthManager.from_env()


def test_integration_auth_loads_and_rotates_secret_manager_env_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_INTEGRATION_RUNTIME_MODE", raising=False)
    monkeypatch.setenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", raising=False)
    monkeypatch.setenv("NO_INTEGRATION_SECRET_MANAGER_PROVIDER", "env_json")
    monkeypatch.setenv("NO_INTEGRATION_SECRET_MANAGER_ENV", "NO_TEST_SECRET_JSON")
    monkeypatch.setenv(
        "NO_TEST_SECRET_JSON",
        json.dumps(
            {
                "opaque_tokens": [
                    {
                        "token": "sm-viewer-token",
                        "principal_id": "sm_viewer",
                        "roles": ["viewer"],
                        "allowed_operations": ["context.build"],
                    }
                ]
            }
        ),
    )

    manager = IntegrationAuthManager.from_env()
    principal_viewer, viewer_error = manager.resolve_authorization("Bearer sm-viewer-token")
    assert viewer_error is None
    assert str(dict(principal_viewer or {}).get("principal_id") or "") == "sm_viewer"
    assert list(dict(principal_viewer or {}).get("allowed_operations") or []) == ["context.build"]

    monkeypatch.setenv(
        "NO_TEST_SECRET_JSON",
        json.dumps(
            {
                "opaque_tokens": [
                    {
                        "token": "sm-operator-token",
                        "principal_id": "sm_operator",
                        "roles": ["operator"],
                        "allowed_operations": ["writeback.propose", "writeback.resolve"],
                    }
                ]
            }
        ),
    )
    manager.refresh(force=True)
    principal_operator, operator_error = manager.resolve_authorization("Bearer sm-operator-token")
    assert operator_error is None
    assert str(dict(principal_operator or {}).get("principal_id") or "") == "sm_operator"
    assert sorted(list(dict(principal_operator or {}).get("allowed_operations") or [])) == [
        "writeback.propose",
        "writeback.resolve",
    ]


def test_integration_auth_command_provider_executes_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_INTEGRATION_RUNTIME_MODE", raising=False)
    monkeypatch.setenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", raising=False)
    monkeypatch.setenv("NO_INTEGRATION_SECRET_MANAGER_PROVIDER", "command")
    monkeypatch.setenv("NO_INTEGRATION_SECRET_MANAGER_COMMAND", "secretctl --profile test")

    captured: dict[str, object] = {}

    def _fake_run(
        command: list[str],
        *,
        shell: bool,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> SimpleNamespace:
        captured["command"] = list(command)
        captured["shell"] = shell
        captured["check"] = check
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "opaque_tokens": [
                        {
                            "token": "sm-command-token",
                            "principal_id": "sm_command",
                            "roles": ["operator"],
                            "allowed_operations": ["writeback.propose"],
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(runtime_server.subprocess, "run", _fake_run)
    manager = IntegrationAuthManager.from_env()
    principal, error = manager.resolve_authorization("Bearer sm-command-token")
    assert error is None
    assert str(dict(principal or {}).get("principal_id") or "") == "sm_command"
    assert captured.get("command") == ["secretctl", "--profile", "test"]
    assert captured.get("shell") is False
    assert captured.get("check") is False
    assert captured.get("capture_output") is True
    assert captured.get("text") is True


def test_integration_auth_secret_refresh_runs_outside_auth_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_INTEGRATION_RUNTIME_MODE", raising=False)
    monkeypatch.setenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", raising=False)
    monkeypatch.setenv("NO_INTEGRATION_SECRET_MANAGER_PROVIDER", "env_json")
    monkeypatch.setenv("NO_INTEGRATION_SECRET_MANAGER_ENV", "NO_TEST_SECRET_JSON")
    monkeypatch.setenv("NO_TEST_SECRET_JSON", "{}")
    manager = IntegrationAuthManager.from_env()

    lock_states: list[bool] = []

    def _fake_load_secret_manager_payload() -> dict[str, object]:
        lock_states.append(manager._lock.locked())  # type: ignore[attr-defined]
        return {
            "opaque_tokens": [
                {
                    "token": "sm-fresh-token",
                    "principal_id": "sm_fresh",
                    "roles": ["viewer"],
                    "allowed_operations": ["context.build"],
                }
            ]
        }

    monkeypatch.setattr(manager, "_load_secret_manager_payload", _fake_load_secret_manager_payload)
    manager._last_secret_reload_monotonic = 0.0
    principal, error = manager.resolve_authorization("Bearer sm-fresh-token")
    assert error is None
    assert str(dict(principal or {}).get("principal_id") or "") == "sm_fresh"
    assert lock_states == [False]


def test_integration_require_role_enforces_operation_scope() -> None:
    principal = {
        "principal_id": "scoped_operator",
        "roles": ["operator"],
        "allowed_operations": ["WriteBack.Propose"],
    }
    _integration_require_role(principal=principal, operation="WRITEBACK.PROPOSE")
    with pytest.raises(IntegrationContractError, match="token scope is not authorized for this operation"):
        _integration_require_role(principal=principal, operation="writeback.resolve")


def test_hermes_adapter_env_token_is_dedicated_to_its_four_server_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_INTEGRATION_HERMES_ADAPTER_TOKEN", "hermes-scoped-token")
    monkeypatch.setenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", raising=False)
    manager = IntegrationAuthManager.from_env()
    principal, error = manager.resolve_authorization("Bearer hermes-scoped-token")
    assert error is None
    assert dict(principal or {}).get("principal_id") == "integration_hermes_adapter"
    assert set(dict(principal or {}).get("allowed_operations") or []) == {
        "health.get",
        "capabilities.get",
        "context.build",
        "memory.observe",
    }
    _integration_require_role(principal=dict(principal or {}), operation="memory.observe")
    with pytest.raises(IntegrationContractError, match="token scope is not authorized"):
        _integration_require_role(principal=dict(principal or {}), operation="writeback.resolve")


def test_automatic_turn_operations_log_metadata_without_message_or_handle_content() -> None:
    secret_text = "private tea preference"
    source_handle = "signed-source-handle"
    receipt_handle = "signed-receipt-handle"
    context_summary = runtime_server._integration_log_payload(
        "context.build",
        {"message": secret_text, "include_temporal": True},
    )
    observe_summary = runtime_server._integration_log_payload(
        "memory.observe",
        {
            "messages": [
                {"role": "user", "content": secret_text},
                {"role": "assistant", "content": "private answer"},
            ],
            "source_registration": {"handle": source_handle},
            "retrieval_receipt": {"handle": receipt_handle},
        },
    )
    serialized = json.dumps({"context": context_summary, "observe": observe_summary})
    assert secret_text not in serialized
    assert "private answer" not in serialized
    assert source_handle not in serialized
    assert receipt_handle not in serialized
    assert context_summary["message_utf8_bytes"] == len(secret_text.encode("utf-8"))
    assert observe_summary["message_count"] == 2
    assert observe_summary["message_roles"] == ["user", "assistant"]
