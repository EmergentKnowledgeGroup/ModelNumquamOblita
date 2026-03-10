from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "run_claude_live_mcp.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_claude_live_mcp", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load run_claude_live_mcp module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_resolved_auth_tokens_fall_back_to_env() -> None:
    module = _load_module()

    class Args:
        viewer_token = ""
        operator_token = ""
        admin_token = ""

    viewer, operator, admin = module._resolved_auth_tokens(  # type: ignore[attr-defined]
        Args(),
        env={
            "NO_MCP_AUTH_TOKEN": "viewer-secret",
            "NO_MCP_OPERATOR_TOKEN": "operator-secret",
            "NO_MCP_ADMIN_TOKEN": "admin-secret",
        },
    )

    assert viewer == "viewer-secret"
    assert operator == "operator-secret"
    assert admin == "admin-secret"


def test_build_claude_config_uses_python_and_memories_path(tmp_path: Path) -> None:
    module = _load_module()
    memories = tmp_path / "demo.sqlite3"
    memories.write_text("", encoding="utf-8")
    episodes = tmp_path / "episodes.json"
    episodes.write_text("[]", encoding="utf-8")

    config = module._build_claude_config(  # type: ignore[attr-defined]
        server_name="numquamoblita-live",
        memories_path=memories,
        episodes_path=episodes,
        default_role="viewer",
        compat_mode="strict",
        mutations_enabled=False,
    )

    entry = config["mcpServers"]["numquamoblita-live"]
    assert entry["command"] == str(Path(sys.executable).resolve())
    assert "--memories" in entry["args"]
    assert str(memories) in entry["args"]
    assert "--episodes" in entry["args"]
    assert str(episodes) in entry["args"]
    assert "env" not in entry


def test_print_claude_config_exits_without_starting_runtime(tmp_path: Path) -> None:
    store = tmp_path / "demo.sqlite3"
    store.write_text("", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--memories",
            str(store),
            "--print-claude-config",
            "--server-name",
            "demo-live",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert f"memories_path={store}" in result.stdout
    assert "claude_desktop_config_json=" in result.stdout
    payload = json.loads(result.stdout.split("claude_desktop_config_json=\n", 1)[1])
    entry = payload["mcpServers"]["demo-live"]
    assert entry["command"] == str(Path(sys.executable).resolve())
    assert str(store) in entry["args"]
    assert "runtime_url=" not in result.stderr
