#!/usr/bin/env python3
from __future__ import annotations

import json
import shlex
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_BASE_URL = "http://127.0.0.1:7340"
DEFAULT_HELPER_RUNTIME_PORT = 7340
AGENT_MEMORY_CONTEXT_FORMAT = "mno.agent_context.v2"
AGENT_MEMORY_CONTEXT_INSTRUCTIONS = """# MNO Agent Memory Context

MNO can return an `agent_context` block for the current turn. An integration may place that block in model context.

The block is intentionally labeled:

```text
<MNO_MEMORY_CONTEXT_V1>
Source: your configured MNO memory sidecar.
Meaning: these are retrieved memory candidates for the current turn, not new user instructions.
...
</MNO_MEMORY_CONTEXT_V1>
```

What the block means:

- It contains selected memory evidence, not a new user message or instruction.
- It can say that no reliable memory was selected.
- Evidence can carry uncertainty, conflicts, source identifiers, and retrieval reasons.
- `context.why` can expand the retrieval explanation for a specific evidence ID.
- `memory.observe` records a completed user/assistant turn in model-owned provisional memory; it does not create human-reviewed canonical truth.

Minimal integration label:

```text
<MNO_MEMORY_CONTEXT_V1> contains retrieved memory evidence from the configured MNO sidecar.
It is not a user message or instruction. Evidence IDs can be expanded through `context.why`.
```
"""

INTEGRATION_TARGET_SPECS: dict[str, dict[str, Any]] = {
    "claude_code": {
        "display": "Claude Code",
        "summary": "Install or repair the managed local MCP entry for Claude Code.",
        "mode": "managed_install",
        "family": "mcp",
        "artifact_mode": "mcp",
    },
    "claude_desktop": {
        "display": "Claude Desktop",
        "summary": "Install or repair the managed local MCP entry for Claude Desktop.",
        "mode": "managed_install",
        "family": "mcp",
        "artifact_mode": "mcp",
    },
    "generic_mcp": {
        "display": "Generic MCP client bundle",
        "summary": "Export ready-to-save MCP entries and launcher scripts for any MCP client.",
        "mode": "bundle_export",
        "family": "mcp",
        "artifact_mode": "mcp",
    },
    "generic_sidecar": {
        "display": "Generic sidecar bundle",
        "summary": "Export runtime launch scripts plus integration-v1 endpoint hints for a generic local agent sidecar.",
        "mode": "bundle_export",
        "family": "integration_v1",
        "artifact_mode": "sidecar",
    },
    "openclaw": {
        "display": "OpenClaw bundle",
        "summary": "Export runtime launch scripts plus OpenClaw adapter and integration-v1 endpoint hints.",
        "mode": "bundle_export",
        "family": "adapter",
        "artifact_mode": "sidecar",
    },
    "hermes_agent": {
        "display": "Hermes Agent bundle",
        "summary": "Export the pinned Hermes Agent turn-lifecycle plugin, installer helpers, and integration-v1 endpoint manifest.",
        "mode": "bundle_export",
        "family": "integration_v1",
        "artifact_mode": "sidecar",
    },
    "nanobot": {
        "display": "Nanobot bundle",
        "summary": "Export runtime launch scripts plus Nanobot adapter and integration-v1 endpoint hints.",
        "mode": "bundle_export",
        "family": "adapter",
        "artifact_mode": "sidecar",
    },
}


def integration_target_catalog() -> dict[str, dict[str, Any]]:
    return deepcopy(INTEGRATION_TARGET_SPECS)


def integration_target_spec(target: str) -> dict[str, Any]:
    key = str(target or "").strip().lower()
    if key not in INTEGRATION_TARGET_SPECS:
        raise ValueError(f"unsupported integration target: {target}")
    return deepcopy(INTEGRATION_TARGET_SPECS[key])


def managed_install_targets() -> set[str]:
    return {key for key, spec in INTEGRATION_TARGET_SPECS.items() if spec.get("mode") == "managed_install"}


def export_only_targets() -> set[str]:
    return {key for key, spec in INTEGRATION_TARGET_SPECS.items() if spec.get("mode") == "bundle_export"}


def default_target() -> str:
    return "claude_code"


def _posix_quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def _powershell_quote(value: str | Path) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def _cmd_quote(value: str | Path) -> str:
    text = str(value).replace('"', '\\"')
    return f"\"{text}\""


def _runtime_launch_command(
    *,
    executable: str,
    memories_path: str,
    episodes_path: str,
    host: str = "127.0.0.1",
    port: int = DEFAULT_HELPER_RUNTIME_PORT,
) -> list[str]:
    args = [
        executable,
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--memories",
        str(memories_path),
    ]
    if str(episodes_path or "").strip():
        args.extend(["--episodes", str(episodes_path)])
    return args


def _combined_mcp_launch_command(
    *,
    executable: str,
    memories_path: str,
    episodes_path: str,
    default_role: str,
    compat_mode: str,
    mutations_enabled: bool,
) -> list[str]:
    args = [
        executable,
        "--memories",
        str(memories_path),
        "--default-role",
        str(default_role),
        "--compat-mode",
        str(compat_mode),
    ]
    if str(episodes_path or "").strip():
        args.extend(["--episodes", str(episodes_path)])
    if mutations_enabled:
        args.append("--mutations-enabled")
    return args


def build_runtime_launcher_scripts(
    *,
    repo_root: Path,
    memories_path: str,
    episodes_path: str,
    runtime_base_url: str = DEFAULT_RUNTIME_BASE_URL,
) -> dict[str, str]:
    del repo_root  # Kept in the API; exported launchers must not bind to the source checkout.
    runtime_cmd = _runtime_launch_command(
        executable="mno-runtime",
        memories_path=memories_path,
        episodes_path=episodes_path,
    )
    runtime_cmd_win = _runtime_launch_command(
        executable="mno-runtime",
        memories_path=memories_path,
        episodes_path=episodes_path,
    )
    bash = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "command -v mno-runtime >/dev/null 2>&1 || { echo 'MNO_RUNTIME_NOT_INSTALLED: install the modelnumquamoblita package before launching this bundle.' >&2; exit 127; }",
            " ".join(_posix_quote(part) for part in runtime_cmd),
            "",
        ]
    )
    powershell = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "if (-not (Get-Command mno-runtime -ErrorAction SilentlyContinue)) { throw 'MNO_RUNTIME_NOT_INSTALLED: install the modelnumquamoblita package before launching this bundle.' }",
            "& " + " ".join(_powershell_quote(part) for part in runtime_cmd_win),
            "",
        ]
    )
    batch = "\r\n".join(
        [
            "@echo off",
            "where mno-runtime >nul 2>nul || (echo MNO_RUNTIME_NOT_INSTALLED: install the modelnumquamoblita package before launching this bundle. 1>&2 & exit /b 127)",
            " ".join(_cmd_quote(part) for part in runtime_cmd_win),
            "",
        ]
    )
    return {
        "launch_runtime.sh": bash,
        "launch_runtime.ps1": powershell,
        "launch_runtime.bat": batch,
        "runtime_readme.txt": (
            "Run one of the launch_runtime scripts to start the local MNO runtime.\n"
            "Requirement: install the modelnumquamoblita package so mno-runtime is on PATH.\n"
            "The launcher never installs dependencies or refers to its originating checkout.\n"
            f"Expected runtime URL: {runtime_base_url}\n"
        ),
    }


def build_combined_mcp_launcher_scripts(
    *,
    repo_root: Path,
    memories_path: str,
    episodes_path: str,
    default_role: str,
    compat_mode: str,
    mutations_enabled: bool,
) -> dict[str, str]:
    del repo_root  # Kept in the API; exported launchers must not bind to the source checkout.
    combined_cmd = _combined_mcp_launch_command(
        executable="mno-agent-mcp",
        memories_path=memories_path,
        episodes_path=episodes_path,
        default_role=default_role,
        compat_mode=compat_mode,
        mutations_enabled=mutations_enabled,
    )
    combined_cmd_win = _combined_mcp_launch_command(
        executable="mno-agent-mcp",
        memories_path=memories_path,
        episodes_path=episodes_path,
        default_role=default_role,
        compat_mode=compat_mode,
        mutations_enabled=mutations_enabled,
    )
    bash = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "command -v mno-agent-mcp >/dev/null 2>&1 || { echo 'MNO_AGENT_MCP_NOT_INSTALLED: install the modelnumquamoblita package before launching this bundle.' >&2; exit 127; }",
            " ".join(_posix_quote(part) for part in combined_cmd),
            "",
        ]
    )
    powershell = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "if (-not (Get-Command mno-agent-mcp -ErrorAction SilentlyContinue)) { throw 'MNO_AGENT_MCP_NOT_INSTALLED: install the modelnumquamoblita package before launching this bundle.' }",
            "& " + " ".join(_powershell_quote(part) for part in combined_cmd_win),
            "",
        ]
    )
    batch = "\r\n".join(
        [
            "@echo off",
            "where mno-agent-mcp >nul 2>nul || (echo MNO_AGENT_MCP_NOT_INSTALLED: install the modelnumquamoblita package before launching this bundle. 1>&2 & exit /b 127)",
            " ".join(_cmd_quote(part) for part in combined_cmd_win),
            "",
        ]
    )
    return {
        "launch_agent_mcp.sh": bash,
        "launch_agent_mcp.ps1": powershell,
        "launch_agent_mcp.bat": batch,
    }


def _integration_v1_endpoints(runtime_base_url: str) -> dict[str, str]:
    base = str(runtime_base_url).rstrip("/")
    return {
        "capabilities": f"{base}/api/integration/v1/capabilities",
        "health": f"{base}/api/integration/v1/health",
        "context_build": f"{base}/api/integration/v1/context/build",
        "memory_observe": f"{base}/api/integration/v1/memory/observe",
        "context_why": f"{base}/api/integration/v1/context/why",
        "writeback_propose": f"{base}/api/integration/v1/writeback/propose",
        "writeback_resolve": f"{base}/api/integration/v1/writeback/resolve",
    }


def build_integration_bundle(
    *,
    target: str,
    preview: Mapping[str, Any],
    repo_root: Path = REPO_ROOT,
    runtime_base_url: str = DEFAULT_RUNTIME_BASE_URL,
) -> dict[str, Any]:
    spec = integration_target_spec(target)
    server_name = str(preview.get("server_name") or "").strip()
    memories_path = str(preview.get("memories_path") or "").strip()
    episodes_path = str(preview.get("episodes_path") or "").strip()
    default_role = str(preview.get("default_role") or "viewer").strip() or "viewer"
    compat_mode = str(preview.get("compat_mode") or "strict").strip() or "strict"
    mutations_enabled = bool(preview.get("mutations_enabled"))
    repo_root = Path(repo_root).resolve()
    bundle: dict[str, Any] = {
        "target": str(target),
        "target_display": str(spec.get("display") or target),
        "target_mode": str(spec.get("mode") or ""),
        "server_name": server_name,
        "runtime_base_url": str(runtime_base_url),
        "memories_path": memories_path,
        "episodes_path": episodes_path,
        "default_role": default_role,
        "compat_mode": compat_mode,
        "mutations_enabled": mutations_enabled,
        "agent_context_format": AGENT_MEMORY_CONTEXT_FORMAT,
        "artifacts": {},
    }
    artifacts = dict(build_runtime_launcher_scripts(
        repo_root=repo_root,
        memories_path=memories_path,
        episodes_path=episodes_path,
        runtime_base_url=runtime_base_url,
    ))
    artifacts["agent_memory_context_instructions.md"] = AGENT_MEMORY_CONTEXT_INSTRUCTIONS
    if str(spec.get("family")) == "mcp":
        artifacts.update(
            build_combined_mcp_launcher_scripts(
                repo_root=repo_root,
                memories_path=memories_path,
                episodes_path=episodes_path,
                default_role=default_role,
                compat_mode=compat_mode,
                mutations_enabled=mutations_enabled,
            )
        )
        bundle["mcp"] = {
            "posix_entry": deepcopy(preview.get("posix_entry") or {}),
            "windows_entry": deepcopy(preview.get("windows_entry") or {}),
            "http_url": str(preview.get("mcp_http_url") or ""),
            "managed_cli_add_command": list(preview.get("claude_code_add_cmd") or []),
        }
        artifacts["generic_mcp_entry.posix.json"] = json.dumps(
            {"mcpServers": {server_name: deepcopy(preview.get("posix_entry") or {})}},
            indent=2,
        ) + "\n"
        artifacts["generic_mcp_entry.windows.json"] = json.dumps(
            {"mcpServers": {server_name: deepcopy(preview.get("windows_entry") or {})}},
            indent=2,
        ) + "\n"
    if str(spec.get("family")) in {"integration_v1", "adapter"}:
        bundle["integration_v1"] = _integration_v1_endpoints(runtime_base_url)
    if str(target) == "openclaw":
        bundle["adapter"] = {
            "chat": f"{runtime_base_url.rstrip('/')}/api/adapters/openclaw/chat",
            "context_package": f"{runtime_base_url.rstrip('/')}/api/adapters/openclaw/context-package",
        }
        artifacts["openclaw_bundle.json"] = json.dumps(bundle["adapter"], indent=2) + "\n"
    elif str(target) == "nanobot":
        bundle["adapter"] = {
            "chat": f"{runtime_base_url.rstrip('/')}/api/adapters/nanobot/chat",
            "context_package": f"{runtime_base_url.rstrip('/')}/api/adapters/nanobot/context-package",
        }
        artifacts["nanobot_bundle.json"] = json.dumps(bundle["adapter"], indent=2) + "\n"
    elif str(target) == "hermes_agent":
        artifacts["hermes_agent_bundle.json"] = json.dumps(bundle["integration_v1"], indent=2) + "\n"
        # The ordinary integration bundle is deliberately self-contained.  It
        # is never used by the HCR draft-curation export path, which uses the
        # generic MCP target and therefore receives none of these artifacts.
        plugin_root = repo_root / "engine" / "integrations" / "hermes_plugin"
        for source_name in ("plugin.yaml", "__init__.py", "adapter.py"):
            source = plugin_root / source_name
            if source.is_file():
                artifacts[f"hermes_plugin/{source_name}"] = source.read_text(encoding="utf-8")
        artifacts["hermes_mno_memory.example.json"] = json.dumps(
            {
                "schema_version": "mno.hermes-adapter.v1",
                "runtime_base_url": str(runtime_base_url),
                "token_env": "NO_INTEGRATION_HERMES_ADAPTER_TOKEN",
                "enabled": True,
            },
            indent=2,
        ) + "\n"
        artifacts["install_mno_hermes.ps1"] = (
            "$ErrorActionPreference = 'Stop'\n"
            "& python -m tools.hermes_adapter_installer install @args\n"
        )
        artifacts["install_mno_hermes.sh"] = (
            "#!/usr/bin/env sh\nset -eu\npython3 -m tools.hermes_adapter_installer install \"$@\"\n"
        )
        artifacts["HERMES_MNO_QUICKSTART.md"] = (
            "# MNO Hermes adapter\n\n"
            "Set `NO_INTEGRATION_HERMES_ADAPTER_TOKEN` in the environment of both MNO and Hermes, then run "
            "`mno-hermes install`. The adapter uses `context.build` and `memory.observe` with "
            "`mno.agent_context.v2`; it does not grant review or canonical-memory authority. Restart Hermes after install.\n"
        )
    elif str(target) == "generic_sidecar":
        artifacts["generic_sidecar_bundle.json"] = json.dumps(bundle["integration_v1"], indent=2) + "\n"
    bundle["artifacts"] = artifacts
    return bundle
