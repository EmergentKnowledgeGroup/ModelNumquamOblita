"""Focused safety and contract tests for the OpenClaw native-layer installer."""

from __future__ import annotations

import json

import pytest

from tools import openclaw_adapter_installer as installer


def test_install_delegates_only_to_openclaw_plugin_commands() -> None:
    calls: list[list[str]] = []

    def runner(command: list[str]) -> str:
        calls.append(command)
        return "{}"

    result = installer.install_plugin(openclaw_bin="openclaw-test", link=True, force=True, runner=runner)
    assert result["ok"] is True
    assert calls[0][:3] == ["openclaw-test", "plugins", "install"]
    assert calls[0][-2:] == ["--link", "--force"]
    assert calls[1] == [
        "openclaw-test", "config", "set",
        f"plugins.entries.{installer.PLUGIN_ID}.hooks.allowConversationAccess", "true",
    ]
    assert calls[2] == [
        "openclaw-test", "config", "set",
        f"plugins.entries.{installer.PLUGIN_ID}.hooks.allowPromptInjection", "true",
    ]
    assert calls[3] == ["openclaw-test", "plugins", "enable", installer.PLUGIN_ID]
    assert result["required_hook_policy"] == installer.REQUIRED_HOOK_POLICY
    assert all(installer.TOKEN_ENV not in " ".join(command) for command in calls)
    assert calls[0][3].endswith("engine\\integrations\\openclaw_plugin") or calls[0][3].endswith("engine/integrations/openclaw_plugin")


def test_doctor_requires_runtime_hook_registration_and_exact_mno_scope_without_exposing_token() -> None:
    inspected: list[tuple[str, bool]] = []
    probed: list[tuple[str, str]] = []

    def inspector(*, openclaw_bin: str, runtime: bool):
        inspected.append((openclaw_bin, runtime))
        return {"runtime": {"hooks": ["before_prompt_build", "agent_end"]}}

    def probe(*, runtime_url: str, token: str):
        probed.append((runtime_url, token))
        return {
            "runtime_url": runtime_url,
            "authorized_operations": sorted(installer.ALLOWED_OPERATIONS),
            "least_privilege_ok": True,
        }

    result = installer.doctor(
        openclaw_bin="openclaw-test",
        runtime_url="http://127.0.0.1:7340",
        environ={installer.TOKEN_ENV: "do-not-print-me"},
        inspector=inspector,
        probe=probe,
    )
    assert result["ok"] is True
    assert inspected == [("openclaw-test", True)]
    assert probed == [("http://127.0.0.1:7340", "do-not-print-me")]
    assert result["host"]["runtime_registration_ok"] is True
    assert result["smoke_turn_required"] is True
    assert "do-not-print-me" not in json.dumps(result)


def test_doctor_fails_closed_for_missing_hook_or_broader_mno_authorization() -> None:
    result = installer.doctor(
        environ={installer.TOKEN_ENV: "token"},
        inspector=lambda **_: {"runtime": {"hooks": ["before_prompt_build"]}},
        probe=lambda **_: {
            "authorized_operations": sorted({*installer.ALLOWED_OPERATIONS, "writeback.resolve"}),
            "least_privilege_ok": False,
        },
    )
    assert result["ok"] is False
    assert result["host"]["runtime_registration_ok"] is False
    assert result["mno"]["contract"] == "scope_mismatch"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:7340",
        "http://example.test:7340",
        "http://127.attacker.example:7340",
        "http://127.0.0.1:7340/?query=1",
        "http://user@127.0.0.1:7340",
    ],
)
def test_runtime_url_rejects_non_loopback_or_ambiguous_values(url: str) -> None:
    with pytest.raises(installer.OpenClawInstallError):
        installer._valid_runtime_url(url)
