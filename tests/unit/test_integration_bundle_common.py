from __future__ import annotations

from pathlib import Path

from tools.integration_bundle_common import (
    build_integration_bundle,
    integration_target_catalog,
    managed_install_targets,
)


def _preview(tmp_path: Path) -> dict[str, object]:
    memories = tmp_path / "atoms.sqlite3"
    memories.write_text("", encoding="utf-8")
    episodes = tmp_path / "episode_cards.reviewed.json"
    episodes.write_text("[]", encoding="utf-8")
    return {
        "server_name": "numquamoblita_live",
        "memories_path": str(memories),
        "episodes_path": str(episodes),
        "default_role": "viewer",
        "compat_mode": "strict",
        "mutations_enabled": False,
        "mcp_http_url": "http://127.0.0.1:8765/mcp",
        "posix_entry": {"type": "stdio", "command": "python3", "args": ["tools/run_agent_live_mcp.py"]},
        "windows_entry": {"type": "stdio", "command": r"C:\Windows\System32\wsl.exe", "args": ["--exec", "python3"]},
        "claude_code_add_cmd": ["claude", "mcp", "add-json", "-s", "user", "numquamoblita_live", "{}"],
    }


def test_target_catalog_exposes_managed_and_export_targets() -> None:
    catalog = integration_target_catalog()
    assert "claude_code" in catalog
    assert "generic_mcp" in catalog
    assert "openclaw" in catalog
    assert managed_install_targets() == {"claude_code", "claude_desktop"}


def test_generic_mcp_bundle_contains_launcher_and_entry_artifacts(tmp_path: Path) -> None:
    bundle = build_integration_bundle(target="generic_mcp", preview=_preview(tmp_path), repo_root=tmp_path)
    assert bundle["target"] == "generic_mcp"
    artifacts = dict(bundle["artifacts"])
    assert "launch_runtime.sh" in artifacts
    assert "launch_agent_mcp.sh" in artifacts
    assert "generic_mcp_entry.posix.json" in artifacts
    assert bundle["agent_context_format"] == "mno_memory_context.v1"
    assert "agent_memory_context_instructions.md" in artifacts
    assert "<MNO_MEMORY_CONTEXT>" in artifacts["agent_memory_context_instructions.md"]


def test_exported_launchers_are_relocatable_and_do_not_run_setup(tmp_path: Path) -> None:
    origin = tmp_path / "origin checkout with spaces"
    bundle = build_integration_bundle(target="generic_mcp", preview=_preview(tmp_path), repo_root=origin)
    artifacts = dict(bundle["artifacts"])
    for name in (
        "launch_runtime.sh",
        "launch_runtime.ps1",
        "launch_runtime.bat",
        "launch_agent_mcp.sh",
        "launch_agent_mcp.ps1",
        "launch_agent_mcp.bat",
    ):
        launcher = str(artifacts[name])
        assert str(origin) not in launcher
        assert "setup_local" not in launcher
    assert "mno-runtime" in artifacts["launch_runtime.sh"]
    assert "MNO_RUNTIME_NOT_INSTALLED" in artifacts["launch_runtime.ps1"]
    assert "mno-agent-mcp" in artifacts["launch_agent_mcp.bat"]
    assert "MNO_AGENT_MCP_NOT_INSTALLED" in artifacts["launch_agent_mcp.sh"]


def test_openclaw_bundle_contains_adapter_and_sidecar_hints(tmp_path: Path) -> None:
    bundle = build_integration_bundle(target="openclaw", preview=_preview(tmp_path), repo_root=tmp_path)
    assert bundle["target"] == "openclaw"
    adapter = dict(bundle["adapter"])
    assert adapter["chat"].endswith("/api/adapters/openclaw/chat")
    assert adapter["context_package"].endswith("/api/adapters/openclaw/context-package")
    assert "integration_v1" in bundle
    assert "openclaw_bundle.json" in dict(bundle["artifacts"])
    assert "agent_memory_context_instructions.md" in dict(bundle["artifacts"])
