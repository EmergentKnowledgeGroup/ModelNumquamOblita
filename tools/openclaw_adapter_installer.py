#!/usr/bin/env python3
"""Install and diagnose the optional native OpenClaw MNO memory layer.

This command delegates every host mutation to OpenClaw's own plugin CLI.  It
never writes a token or copies a plugin into an arbitrary host directory.  The
doctor proves static runtime registration and the restricted MNO integration
contract; a real human-turn smoke check remains the proof that hooks fire in a
particular Gateway process.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid


PLUGIN_ID = "mno-openclaw-memory"
TOKEN_ENV = "NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN"
DEFAULT_RUNTIME_URL = "http://127.0.0.1:7340"
ALLOWED_OPERATIONS = frozenset({"health.get", "capabilities.get", "context.build", "memory.observe"})
REQUIRED_HOOK_POLICY = {
    "allowConversationAccess": True,
    "allowPromptInjection": True,
}
MAX_PROBE_RESPONSE_BYTES = 262144


class OpenClawInstallError(RuntimeError):
    """A safe diagnostic failure; command output is intentionally withheld."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def plugin_source_root() -> Path:
    return _package_root() / "engine" / "integrations" / "openclaw_plugin"


def _valid_runtime_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError as exc:
        raise OpenClawInstallError("runtime URL is invalid") from exc
    host = str(parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or (host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("127."))
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise OpenClawInstallError("runtime URL must be an http loopback root URL")
    if not parsed.netloc:
        raise OpenClawInstallError("runtime URL is missing a host")
    return f"http://{parsed.netloc}"


def _require_plugin_source() -> Path:
    source = plugin_source_root()
    required = ("package.json", "openclaw.plugin.json", "index.js", "runtime.js")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise OpenClawInstallError("packaged OpenClaw plugin files are incomplete")
    return source


def _run_openclaw(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise OpenClawInstallError("OpenClaw CLI is unavailable") from exc
    if completed.returncode != 0:
        raise OpenClawInstallError("OpenClaw CLI command failed")
    return str(completed.stdout or "")


def _openclaw_json(command: list[str]) -> Mapping[str, Any]:
    raw = _run_openclaw(command)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenClawInstallError("OpenClaw CLI did not return JSON") from exc
    if not isinstance(payload, Mapping):
        raise OpenClawInstallError("OpenClaw CLI returned an invalid JSON shape")
    return dict(payload)


def _runtime_hook_names(value: Any) -> set[str]:
    """Extract exact lifecycle hook names from an inspect --runtime response."""

    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, row in value.items():
            if key in {"before_prompt_build", "agent_end"}:
                found.add(key)
            found.update(_runtime_hook_names(row))
    elif isinstance(value, list):
        for row in value:
            found.update(_runtime_hook_names(row))
    elif isinstance(value, str) and value in {"before_prompt_build", "agent_end"}:
        found.add(value)
    return found


def install_plugin(
    *,
    openclaw_bin: str = "openclaw",
    link: bool = False,
    force: bool = False,
    runner: Callable[[list[str]], str] = _run_openclaw,
) -> dict[str, Any]:
    source = _require_plugin_source()
    install = [str(openclaw_bin), "plugins", "install", str(source)]
    if link:
        install.append("--link")
    if force:
        install.append("--force")
    runner(install)
    # OpenClaw intentionally blocks non-bundled conversation hooks until the
    # plugin-specific policy grants them.  Use the host CLI's narrow dotted
    # config writes rather than editing a Gateway config file ourselves.
    for policy_name, value in REQUIRED_HOOK_POLICY.items():
        runner([
            str(openclaw_bin),
            "config",
            "set",
            f"plugins.entries.{PLUGIN_ID}.hooks.{policy_name}",
            "true" if value else "false",
        ])
    runner([str(openclaw_bin), "plugins", "enable", PLUGIN_ID])
    return {
        "ok": True,
        "action": "install",
        "plugin_id": PLUGIN_ID,
        "installed_from": "packaged_mno_plugin",
        "linked": bool(link),
        "enabled": True,
        "required_hook_policy": dict(REQUIRED_HOOK_POLICY),
        "next": "Run mno-openclaw doctor, then perform one real human-turn smoke check.",
    }


def uninstall_plugin(
    *,
    openclaw_bin: str = "openclaw",
    runner: Callable[[list[str]], str] = _run_openclaw,
) -> dict[str, Any]:
    runner([str(openclaw_bin), "plugins", "uninstall", PLUGIN_ID])
    return {"ok": True, "action": "uninstall", "plugin_id": PLUGIN_ID}


def inspect_plugin(
    *,
    openclaw_bin: str = "openclaw",
    runtime: bool = False,
    runner: Callable[[list[str]], str] = _run_openclaw,
) -> Mapping[str, Any]:
    command = [str(openclaw_bin), "plugins", "inspect", PLUGIN_ID]
    if runtime:
        command.append("--runtime")
    command.append("--json")
    raw = runner(command)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenClawInstallError("OpenClaw CLI did not return JSON") from exc
    if not isinstance(payload, Mapping):
        raise OpenClawInstallError("OpenClaw CLI returned an invalid JSON shape")
    return dict(payload)


def _request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def _probe_get(runtime_url: str, token: str, *, operation: str, path: str) -> Mapping[str, Any]:
    query = urlencode({"schema_version": "integration.v1", "request_id": _request_id()})
    request = Request(
        f"{runtime_url}{path}?{query}",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=3.0) as response:
            raw = response.read(MAX_PROBE_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, OSError) as exc:
        raise OpenClawInstallError("MNO runtime probe failed") from exc
    if len(raw) > MAX_PROBE_RESPONSE_BYTES:
        raise OpenClawInstallError("MNO runtime probe response was too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenClawInstallError("MNO runtime probe returned invalid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("ok") is not True or payload.get("operation") != operation:
        raise OpenClawInstallError("MNO runtime probe failed the integration contract")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise OpenClawInstallError("MNO runtime probe returned an invalid data shape")
    return dict(data)


def probe_mno_contract(*, runtime_url: str, token: str) -> dict[str, Any]:
    normalized = _valid_runtime_url(runtime_url)
    _probe_get(normalized, token, operation="health.get", path="/api/integration/v1/health")
    capabilities = _probe_get(normalized, token, operation="capabilities.get", path="/api/integration/v1/capabilities")
    rows = capabilities.get("operations")
    if not isinstance(rows, list):
        raise OpenClawInstallError("MNO capabilities response is invalid")
    authorized = {
        str(row.get("name"))
        for row in rows
        if isinstance(row, Mapping) and row.get("available") is True and row.get("authorized") is True
    }
    return {
        "runtime_url": normalized,
        "authorized_operations": sorted(authorized),
        "least_privilege_ok": authorized == ALLOWED_OPERATIONS,
    }


def doctor(
    *,
    openclaw_bin: str = "openclaw",
    runtime_url: str = DEFAULT_RUNTIME_URL,
    environ: Mapping[str, str] | None = None,
    inspector: Callable[..., Mapping[str, Any]] = inspect_plugin,
    probe: Callable[..., Mapping[str, Any]] = probe_mno_contract,
) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    result: dict[str, Any] = {
        "ok": False,
        "action": "doctor",
        "plugin_id": PLUGIN_ID,
        "credential": {
            "source": "environment",
            "token_env": TOKEN_ENV,
            "visible_to_doctor": bool(str(environment.get(TOKEN_ENV) or "").strip()),
            "gateway_environment": "requires_real_turn_smoke_check",
        },
        "host": {"runtime_inspect": "not_checked", "required_hooks": ["before_prompt_build", "agent_end"]},
        "mno": {"contract": "not_checked"},
        "smoke_turn_required": True,
    }
    try:
        runtime_payload = inspector(openclaw_bin=openclaw_bin, runtime=True)
        hooks = _runtime_hook_names(runtime_payload)
        result["host"] = {
            "runtime_inspect": "ok",
            "required_hooks": ["before_prompt_build", "agent_end"],
            "registered_hooks": sorted(hooks),
            "runtime_registration_ok": {"before_prompt_build", "agent_end"}.issubset(hooks),
        }
    except OpenClawInstallError:
        result["host"] = {"runtime_inspect": "failed", "runtime_registration_ok": False}
    token = str(environment.get(TOKEN_ENV) or "").strip()
    if token:
        try:
            mno = dict(probe(runtime_url=runtime_url, token=token))
            mno["contract"] = "ok" if mno.get("least_privilege_ok") else "scope_mismatch"
            result["mno"] = mno
        except OpenClawInstallError:
            result["mno"] = {"contract": "failed", "least_privilege_ok": False}
    else:
        result["mno"] = {"contract": "token_missing", "least_privilege_ok": False}
    result["ok"] = bool(
        result["credential"].get("visible_to_doctor")
        and result["host"].get("runtime_registration_ok")
        and result["mno"].get("least_privilege_ok")
    )
    return result


def status(
    *,
    openclaw_bin: str = "openclaw",
    inspector: Callable[..., Mapping[str, Any]] = inspect_plugin,
) -> dict[str, Any]:
    try:
        payload = inspector(openclaw_bin=openclaw_bin, runtime=False)
    except OpenClawInstallError:
        return {"ok": False, "action": "status", "plugin_id": PLUGIN_ID, "host_inspect": "failed"}
    return {
        "ok": True,
        "action": "status",
        "plugin_id": PLUGIN_ID,
        "host_inspect": "ok",
        "inspect_fields": sorted(str(key) for key in payload.keys()),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw CLI executable (default: openclaw)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable, secret-free diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="install and enable the packaged plugin through OpenClaw")
    install.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install.add_argument("--link", action="store_true", help="request OpenClaw's development link mode")
    install.add_argument("--force", action="store_true", help="pass OpenClaw's force flag to the install command")
    uninstall = subparsers.add_parser("uninstall", help="remove the plugin through OpenClaw")
    uninstall.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    status_parser = subparsers.add_parser("status", help="inspect installed plugin metadata")
    status_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    doctor_parser = subparsers.add_parser("doctor", help="verify runtime hook registration and MNO contract scope")
    doctor_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    doctor_parser.add_argument("--runtime-url", default=DEFAULT_RUNTIME_URL, help="loopback MNO runtime URL")
    return parser


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(dict(payload), ensure_ascii=True, sort_keys=True))
        return
    print(f"{payload.get('action', 'openclaw')} {payload.get('plugin_id', PLUGIN_ID)}: {'OK' if payload.get('ok') else 'NEEDS ATTENTION'}")
    if payload.get("action") == "doctor":
        print("Run one real human-turn smoke check after doctor; it is the proof that this Gateway process inherited the credential and fired both hooks.")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            result = install_plugin(openclaw_bin=args.openclaw_bin, link=bool(args.link), force=bool(args.force))
        elif args.command == "uninstall":
            result = uninstall_plugin(openclaw_bin=args.openclaw_bin)
        elif args.command == "status":
            result = status(openclaw_bin=args.openclaw_bin)
        else:
            result = doctor(openclaw_bin=args.openclaw_bin, runtime_url=args.runtime_url)
    except OpenClawInstallError:
        result = {"ok": False, "action": str(args.command), "plugin_id": PLUGIN_ID, "error": "operation_failed"}
    _emit(result, as_json=bool(args.json))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
