#!/usr/bin/env python3
"""Ownership-safe lifecycle command for the optional Hermes MNO adapter.

This module is the only installer engine.  Exported shell helpers invoke this
entry point; they never copy files or mutate a Hermes home themselves.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


PLUGIN_NAME = "mno-memory"
STATE_SCHEMA = "mno.hermes-install-state.v1"
CONFIG_SCHEMA = "mno.hermes-adapter.v1"
DEFAULT_RUNTIME_URL = "http://127.0.0.1:7340"
DEFAULT_TOKEN_ENV = "NO_INTEGRATION_HERMES_ADAPTER_TOKEN"
SUPPORTED_HERMES_VERSION = "0.19.0"
OWNED_PLUGIN_FILES = ("plugin.yaml", "__init__.py", "adapter.py")
ALLOWED_OPERATIONS = frozenset({"health.get", "capabilities.get", "context.build", "memory.observe"})
MAX_PROBE_RESPONSE_BYTES = 524288


class HermesInstallError(RuntimeError):
    pass


class HermesProbeError(HermesInstallError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def plugin_source_root() -> Path:
    return _package_root() / "engine" / "integrations" / "hermes_plugin"


def resolve_hermes_home(value: str | Path | None = None, *, env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    environment = os.environ if env is None else env
    raw = str(value or environment.get("HERMES_HOME") or "").strip()
    effective_platform = platform or sys.platform
    if not raw:
        if os.name == "nt" or effective_platform.startswith("win"):
            local = str(environment.get("LOCALAPPDATA") or environment.get("APPDATA") or "").strip()
            raw = str((Path(local) if local else Path.home() / "AppData" / "Local") / "hermes")
        else:
            raw = str(Path.home() / ".hermes")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    _reject_reparse_components(candidate)
    return candidate.resolve(strict=False)


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attrs = path.stat(follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def _reject_reparse_components(path: Path) -> None:
    # Inspect lexical components before resolve() can hide a link/junction.
    current = Path(path.anchor) if path.anchor else Path.cwd().anchor
    for part in path.parts[1:] if path.anchor else path.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_reparse(current):
                raise HermesInstallError(f"Hermes home contains a symlink, junction, or reparse point: {current}")


def _contained(home: Path, path: Path) -> Path:
    _reject_reparse_components(path)
    resolved_home = home.resolve(strict=False)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_home)
    except ValueError as exc:
        raise HermesInstallError("installer path escapes the resolved Hermes home") from exc
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_components(path.parent)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HermesInstallError(f"invalid adapter state file: {path}") from exc
    if not isinstance(data, dict):
        raise HermesInstallError("adapter state must be a JSON object")
    return data


def _state_paths(home: Path) -> tuple[Path, Path, Path]:
    plugin = _contained(home, home / "plugins" / PLUGIN_NAME)
    config = _contained(home, home / "mno" / "mno-memory.json")
    state = _contained(home, home / "mno" / "install-state.json")
    return plugin, config, state


def _config_payload(*, runtime_url: str, token_env: str) -> dict[str, Any]:
    _validate_runtime_url(runtime_url)
    if not token_env or token_env != DEFAULT_TOKEN_ENV:
        raise HermesInstallError(f"token env must be {DEFAULT_TOKEN_ENV}; token values are never accepted")
    return {
        "schema_version": CONFIG_SCHEMA,
        "runtime_base_url": runtime_url,
        "token_env": token_env,
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


def _validate_runtime_url(value: str) -> None:
    parsed = urlparse(str(value))
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise HermesInstallError("runtime URL must be plain http loopback URL without credentials, query, or fragment")
    hostname = parsed.hostname.lower()
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise HermesInstallError("runtime URL host must be loopback") from exc
        if not address.is_loopback or (address.version == 4 and not hostname.startswith("127.")):
            raise HermesInstallError("runtime URL host must be loopback")


def _source_files() -> dict[str, bytes]:
    root = plugin_source_root()
    result: dict[str, bytes] = {}
    for name in OWNED_PLUGIN_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise HermesInstallError(f"packaged Hermes plugin file is unavailable: {name}")
        result[name] = path.read_bytes()
    return result


def _owned_hashes(home: Path, plugin: Path, config: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in [*(plugin / name for name in OWNED_PLUGIN_FILES), config]:
        if path.is_file():
            hashes[path.resolve().relative_to(home.resolve()).as_posix()] = _sha256(path)
    return hashes


def _tree_hashes(root: Path, *, home: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.resolve().relative_to(home.resolve()).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _validate_existing_ownership(home: Path, plugin: Path, config: Path, state: Mapping[str, Any] | None, *, force: bool) -> None:
    present = [path for path in [plugin, config] if path.exists()]
    if not present:
        return
    if not state or state.get("schema_version") != STATE_SCHEMA:
        raise HermesInstallError("refusing to replace an unowned Hermes adapter plugin or config")
    expected = dict(state.get("owned_hashes") or {})
    actual = _owned_hashes(home, plugin, config)
    all_plugin_files = {
        path.resolve().relative_to(home.resolve()).as_posix()
        for path in plugin.rglob("*")
        if path.is_file() and not path.is_symlink()
    } if plugin.is_dir() else set()
    unknown_plugin_files = all_plugin_files - set(expected)
    if unknown_plugin_files:
        raise HermesInstallError("refusing to replace unowned files inside the adapter plugin directory")
    unknown = set(actual) - set(expected)
    mismatched = [name for name, digest in actual.items() if expected.get(name) != digest]
    if unknown:
        raise HermesInstallError("refusing to replace unowned files inside the adapter paths")
    if mismatched and not force:
        raise HermesInstallError("owned adapter files changed; rerun with --force to replace only owned paths")


def _run_hermes(args: list[str], *, home: Path, runner: Callable[..., Any] = subprocess.run) -> Any:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env["HERMES_CONFIG"] = str(_contained(home, home / "config.yaml"))
    try:
        completed = runner(["hermes", *args], check=False, capture_output=True, text=True, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HermesInstallError("Hermes CLI is unavailable or timed out") from exc
    if int(getattr(completed, "returncode", 1)) != 0:
        raise HermesInstallError("Hermes plugin command failed")
    return completed


def _hermes_version(home: Path, *, runner: Callable[..., Any] = subprocess.run) -> str:
    completed = _run_hermes(["--version"], home=home, runner=runner)
    output = f"{getattr(completed, 'stdout', '')}\n{getattr(completed, 'stderr', '')}"
    # Anchor to the Hermes product banner so a parenthesized build date such
    # as ``(2026.7.20)`` can never be mistaken for the package version.
    match = re.search(r"\bHermes\s+Agent\s+v?(\d+\.\d+\.\d+)\b", output, re.IGNORECASE)
    if not match:
        raise HermesInstallError("Hermes CLI did not report a semantic version")
    version = match.group(1)
    if version != SUPPORTED_HERMES_VERSION:
        raise HermesInstallError(
            f"Hermes {version} is not the pinned adapter target {SUPPORTED_HERMES_VERSION}"
        )
    return version


def _plugin_state(home: Path, *, runner: Callable[..., Any] = subprocess.run) -> str:
    completed = _run_hermes(["plugins", "list", "--json"], home=home, runner=runner)
    try:
        rows = json.loads(str(getattr(completed, "stdout", "") or "[]"))
    except json.JSONDecodeError as exc:
        raise HermesInstallError("Hermes plugin list did not return JSON") from exc
    if not isinstance(rows, list):
        raise HermesInstallError("Hermes plugin list did not return a list")
    for row in rows:
        if isinstance(row, dict) and str(row.get("name") or "") == PLUGIN_NAME:
            status = str(row.get("status") or "").lower()
            if status in {"enabled", "disabled"}:
                return status
    return "neither"


def _set_plugin_state(home: Path, state: str, *, runner: Callable[..., Any] = subprocess.run) -> None:
    if state == "enabled":
        _run_hermes(["plugins", "enable", PLUGIN_NAME, "--no-allow-tool-override"], home=home, runner=runner)
    elif state == "disabled":
        _run_hermes(["plugins", "disable", PLUGIN_NAME], home=home, runner=runner)
    elif state != "neither":
        raise HermesInstallError("invalid prior Hermes plugin state")


def _config_list(home: Path, key: str, *, runner: Callable[..., Any] = subprocess.run) -> list[str]:
    completed = _run_hermes(["config", "get", key, "--json"], home=home, runner=runner)
    try:
        value = json.loads(str(getattr(completed, "stdout", "") or "null"))
    except json.JSONDecodeError as exc:
        raise HermesInstallError(f"Hermes config get returned invalid JSON for {key}") from exc
    if not isinstance(value, list):
        raise HermesInstallError(f"Hermes config key {key} is not a list")
    return [str(item) for item in value]


def _restore_plugin_state(home: Path, state: str, *, runner: Callable[..., Any] = subprocess.run) -> None:
    if state in {"enabled", "disabled"}:
        _set_plugin_state(home, state, runner=runner)
        return
    if state != "neither":
        raise HermesInstallError("invalid prior Hermes plugin state")
    # Official disable removes the allow-list entry. It intentionally leaves a
    # disabled tombstone, so remove only that exact list item and our own
    # capability entry through Hermes's config command.
    _set_plugin_state(home, "disabled", runner=runner)
    disabled = _config_list(home, "plugins.disabled", runner=runner)
    indexes = [index for index, value in enumerate(disabled) if value == PLUGIN_NAME]
    for index in reversed(indexes):
        _run_hermes(["config", "unset", f"plugins.disabled.{index}"], home=home, runner=runner)
    try:
        _run_hermes(["config", "unset", f"plugins.entries.{PLUGIN_NAME}"], home=home, runner=runner)
    except HermesInstallError:
        pass


def _live_probe(config: Mapping[str, Any], *, token: str) -> dict[str, Any]:
    base = str(config["runtime_base_url"]).rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    result: dict[str, Any] = {}
    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req: Any, fp: Any, code: int, msg: str, response_headers: Any, newurl: str) -> None:
            return None

    opener = build_opener(ProxyHandler({}), _NoRedirect())
    for name, suffix in (("health", "/api/integration/v1/health"), ("capabilities", "/api/integration/v1/capabilities")):
        request_id = f"req_{hashlib.sha256((name + _utc_now()).encode('utf-8')).hexdigest()[:32]}"
        request = Request(
            base + suffix + "?" + urlencode({"schema_version": "integration.v1", "request_id": request_id}),
            headers=headers,
            method="GET",
        )
        try:
            with opener.open(request, timeout=2.5) as response:
                if response.geturl() != request.full_url:
                    raise HermesProbeError("contract_incompatible", "MNO runtime redirected the read-only probe")
                raw = response.read(MAX_PROBE_RESPONSE_BYTES + 1)
                if len(raw) > MAX_PROBE_RESPONSE_BYTES:
                    raise HermesProbeError("contract_incompatible", "MNO runtime probe response exceeded the size limit")
                try:
                    decoded = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HermesProbeError("contract_incompatible", "MNO runtime probe returned invalid JSON") from exc
                expected_operation = f"{name}.get"
                if (
                    not isinstance(decoded, Mapping)
                    or decoded.get("schema_version") != "integration.v1"
                    or decoded.get("operation") != expected_operation
                    or decoded.get("ok") is not True
                    or not isinstance(decoded.get("data"), Mapping)
                ):
                    raise HermesProbeError("contract_incompatible", "MNO runtime returned an invalid integration-v1 envelope")
                result[name] = dict(decoded["data"])
        except HermesProbeError:
            raise
        except HTTPError as exc:
            if exc.code in {401, 403}:
                status = "auth_denied"
            elif 300 <= exc.code < 500:
                status = "contract_incompatible"
            else:
                status = "runtime_unavailable"
            raise HermesProbeError(status, f"MNO runtime probe failed with HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise HermesProbeError("runtime_unavailable", "MNO runtime is unavailable for the read-only probe") from exc
        except Exception as exc:
            raise HermesProbeError("contract_incompatible", "MNO runtime probe failed unexpectedly") from exc
    return result


def doctor(*, home: Path, live: bool = True, runner: Callable[..., Any] = subprocess.run, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    plugin, config_path, state_path = _state_paths(home)
    if not config_path.is_file() or not state_path.is_file():
        return {"status": "disabled", "installed": False, "home": str(home)}
    state = _read_json(state_path)
    if state.get("schema_version") != STATE_SCHEMA:
        raise HermesInstallError("unsupported adapter install state schema")
    config = _read_json(config_path)
    if config.get("schema_version") != CONFIG_SCHEMA:
        raise HermesInstallError("unsupported adapter config schema")
    _validate_runtime_url(str(config.get("runtime_base_url") or ""))
    token_env = str(config.get("token_env") or "")
    if token_env != DEFAULT_TOKEN_ENV:
        raise HermesInstallError("adapter config has an invalid token environment variable")
    hashes_match = _owned_hashes(home, plugin, config_path) == dict(state.get("owned_hashes") or {})
    hermes_version = _hermes_version(home, runner=runner)
    enabled = _plugin_state(home, runner=runner) == "enabled"
    result: dict[str, Any] = {
        "status": "healthy" if hashes_match and enabled else "disabled",
        "installed": True,
        "home": str(home),
        "hashes_match": hashes_match,
        "plugin_enabled": enabled,
        "hermes_version": hermes_version,
    }
    if not live:
        return result
    env = os.environ if environ is None else environ
    token = str(env.get(token_env) or "")
    if not token:
        result["status"] = "auth_missing"
        return result
    try:
        probe = _live_probe(config, token=token)
    except HermesProbeError as exc:
        result["status"] = exc.status
        return result
    operations = {str(row.get("name") or ""): row for row in list(dict(probe.get("capabilities") or {}).get("operations") or []) if isinstance(row, dict)}
    effective = {
        name
        for name in ALLOWED_OPERATIONS
        if name in {"health.get", "capabilities.get"}
        or bool(operations.get(name, {}).get("available"))
        and bool(operations.get(name, {}).get("authorized"))
    }
    broader_authorized = sorted(
        name
        for name, row in operations.items()
        if bool(row.get("authorized")) and name not in ALLOWED_OPERATIONS
    )
    result.update(
        {
            "health": str(dict(probe.get("health") or {}).get("status") or "unknown"),
            "effective_operations": sorted(effective),
            "broader_authorized_operations": broader_authorized,
            "review_apply_denied": not broader_authorized,
        }
    )
    if not {"context.build", "memory.observe"}.issubset(effective):
        result["status"] = "operation_unavailable"
    elif broader_authorized:
        result["status"] = "contract_incompatible"
    return result


def install(*, home: Path, runtime_url: str = DEFAULT_RUNTIME_URL, token_env: str = DEFAULT_TOKEN_ENV, dry_run: bool = False, force: bool = False, runner: Callable[..., Any] = subprocess.run, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    plugin, config_path, state_path = _state_paths(home)
    config = _config_payload(runtime_url=runtime_url, token_env=token_env)
    env = os.environ if environ is None else environ
    token_present = bool(str(env.get(token_env) or ""))
    if not token_present:
        raise HermesInstallError(f"required token environment variable is missing: {token_env}")
    _hermes_version(home, runner=runner)
    previous = _plugin_state(home, runner=runner)
    prior_state = _read_json(state_path) if state_path.is_file() else None
    original_state = state_path.read_bytes() if state_path.is_file() else None
    original_prior_plugin_state = (
        str(prior_state.get("prior_plugin_state") or previous)
        if prior_state
        else previous
    )
    _validate_existing_ownership(home, plugin, config_path, prior_state, force=force)
    if dry_run:
        return {"status": "dry_run", "home": str(home), "token_present": token_present, "prior_plugin_state": previous, "restart_required": True}
    source = _source_files()
    plugin.parent.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup = _contained(home, home / "mno" / "backups" / "mno-memory")
    staging = plugin.parent / f".{PLUGIN_NAME}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    previous_plugin = plugin.exists()
    original_config = config_path.read_bytes() if config_path.is_file() else None
    try:
        staging.mkdir()
        for name, data in source.items():
            _atomic_write(staging / name, data)
        if backup.exists():
            shutil.rmtree(backup)
        backup_plugin = backup / "plugins" / PLUGIN_NAME
        backup_config = backup / "mno-memory.json"
        if previous_plugin:
            backup_plugin.parent.mkdir(parents=True, exist_ok=True)
            os.replace(plugin, backup_plugin)
        if original_config is not None:
            _atomic_write(backup_config, original_config)
        os.replace(staging, plugin)
        _atomic_write(config_path, json.dumps(config, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        _set_plugin_state(home, "enabled", runner=runner)
        owned = _owned_hashes(home, plugin, config_path)
        state = {
            "schema_version": STATE_SCHEMA,
            "adapter_version": "0.2.3",
            "hermes_version": SUPPORTED_HERMES_VERSION,
            "hermes_home": str(home),
            "installed_at": _utc_now(),
            "owned_hashes": owned,
            "prior_plugin_state": original_prior_plugin_state,
            "backup": {
                "path": str(backup.relative_to(home)) if backup.exists() else "",
                "hashes": _tree_hashes(backup, home=home),
            },
        }
        _atomic_write(state_path, json.dumps(state, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        diagnosis = doctor(home=home, live=True, runner=runner, environ=env)
        if diagnosis.get("status") != "healthy":
            raise HermesInstallError(f"adapter doctor failed: {diagnosis.get('status')}")
        return {"status": "installed", "home": str(home), "token_present": token_present, "doctor": diagnosis, "restart_required": True}
    except Exception as original_exc:
        rollback_errors: list[str] = []
        try:
            if plugin.exists():
                shutil.rmtree(plugin)
            backup_plugin = backup / "plugins" / PLUGIN_NAME
            if previous_plugin and backup_plugin.exists():
                plugin.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup_plugin, plugin)
            if original_config is None:
                config_path.unlink(missing_ok=True)
            else:
                _atomic_write(config_path, original_config)
            if original_state is None:
                state_path.unlink(missing_ok=True)
            else:
                _atomic_write(state_path, original_state)
        except Exception as exc:
            rollback_errors.append(f"bytes: {type(exc).__name__}")
        try:
            _restore_plugin_state(home, previous, runner=runner)
        except Exception as exc:
            rollback_errors.append(f"Hermes state: {type(exc).__name__}")
        if rollback_errors:
            raise HermesInstallError(
                "adapter install failed and rollback incomplete ("
                + ", ".join(rollback_errors)
                + f"); original error: {type(original_exc).__name__}"
            ) from original_exc
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def uninstall(*, home: Path, dry_run: bool = False, force: bool = False, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    plugin, config_path, state_path = _state_paths(home)
    if not state_path.is_file():
        return {"status": "not_installed", "home": str(home)}
    state = _read_json(state_path)
    if state.get("schema_version") != STATE_SCHEMA:
        raise HermesInstallError("refusing to remove unrecognized adapter state")
    expected = dict(state.get("owned_hashes") or {})
    actual = _owned_hashes(home, plugin, config_path)
    if actual != expected and not force:
        raise HermesInstallError("adapter files changed; refusing uninstall without --force")
    backup_state = dict(state.get("backup") or {})
    backup_rel = str(backup_state.get("path") or "").strip()
    backup_path = _contained(home, home / backup_rel) if backup_rel else None
    expected_backup = dict(backup_state.get("hashes") or {})
    actual_backup = _tree_hashes(backup_path, home=home) if backup_path else {}
    if actual_backup != expected_backup and not force:
        raise HermesInstallError("adapter backup changed; refusing uninstall without --force")
    if dry_run:
        return {"status": "dry_run", "home": str(home), "would_remove": sorted(actual), "restore_plugin_state": str(state.get("prior_plugin_state") or "neither")}
    current_plugin_state = _plugin_state(home, runner=runner)
    desired_plugin_state = str(state.get("prior_plugin_state") or "neither")
    snapshots: dict[Path, bytes] = {state_path: state_path.read_bytes()}
    for rel in {*expected, *actual_backup}:
        target = _contained(home, home / rel)
        if target.is_file():
            snapshots[target] = target.read_bytes()
    try:
        _restore_plugin_state(home, desired_plugin_state, runner=runner)
    except Exception as original_exc:
        try:
            _restore_plugin_state(home, current_plugin_state, runner=runner)
        except Exception as rollback_exc:
            raise HermesInstallError(
                "adapter uninstall failed and Hermes state rollback incomplete"
            ) from original_exc
        raise
    try:
        for rel in expected:
            target = _contained(home, home / rel)
            if target.is_file():
                target.unlink()
        if backup_path and backup_path.is_dir():
            shutil.rmtree(backup_path)
        state_path.unlink(missing_ok=True)
    except Exception as original_exc:
        rollback_errors: list[str] = []
        try:
            for target, content in snapshots.items():
                _atomic_write(target, content)
        except Exception as exc:
            rollback_errors.append(f"bytes: {type(exc).__name__}")
        try:
            _restore_plugin_state(home, current_plugin_state, runner=runner)
        except Exception as exc:
            rollback_errors.append(f"Hermes state: {type(exc).__name__}")
        if rollback_errors:
            raise HermesInstallError(
                "adapter uninstall failed and rollback incomplete ("
                + ", ".join(rollback_errors)
                + ")"
            ) from original_exc
        raise
    for directory in (plugin, plugin.parent):
        try:
            directory.rmdir()
        except OSError:
            pass
    for directory in (config_path.parent / "backups", config_path.parent):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"status": "uninstalled", "home": str(home), "restart_required": True}


def status(*, home: Path, live: bool = False, runner: Callable[..., Any] = subprocess.run, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    return doctor(home=home, live=live, runner=runner, environ=environ)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install or inspect the optional MNO Hermes adapter.", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "doctor", "status", "uninstall"):
        command = sub.add_parser(name, allow_abbrev=False)
        command.add_argument("--hermes-home", default="")
        command.add_argument("--json", action="store_true")
    install_parser = sub.choices["install"]
    install_parser.add_argument("--runtime-url", default=DEFAULT_RUNTIME_URL)
    install_parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--force", action="store_true")
    uninstall_parser = sub.choices["uninstall"]
    uninstall_parser.add_argument("--dry-run", action="store_true")
    uninstall_parser.add_argument("--force", action="store_true")
    sub.choices["status"].add_argument("--live", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        home = resolve_hermes_home(args.hermes_home or None)
        if args.command == "install":
            payload = install(home=home, runtime_url=args.runtime_url, token_env=args.token_env, dry_run=args.dry_run, force=args.force)
        elif args.command == "doctor":
            payload = doctor(home=home, live=True)
        elif args.command == "status":
            payload = status(home=home, live=bool(args.live))
        else:
            payload = uninstall(home=home, dry_run=args.dry_run, force=args.force)
        output = json.dumps(payload, sort_keys=True) if args.json else "\n".join(f"{key}: {value}" for key, value in payload.items())
        print(output)
        return 0
    except HermesInstallError as exc:
        payload = {"status": "error", "error": str(exc)}
        print(json.dumps(payload, sort_keys=True) if getattr(args, "json", False) else f"error: {payload['error']}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
