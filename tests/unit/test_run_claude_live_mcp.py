from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_review_apply_token_is_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    assert module._review_apply_token({"NO_INTEGRATION_REVIEW_APPLY_TOKEN": " human-secret "}) == "human-secret"

    monkeypatch.setattr(sys, "argv", ["run_claude_live_mcp.py", "--review-apply-token", "argv-secret"])
    with pytest.raises(SystemExit) as exc_info:
        module._parse_args()
    assert exc_info.value.code == 2


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
    assert entry["type"] == "stdio"
    assert entry["type"] == "stdio"
    assert entry["command"] == str(Path(sys.executable).resolve())
    assert entry["env"] == {}
    assert entry["env"] == {}
    assert "--memories" in entry["args"]
    assert str(memories) in entry["args"]
    assert "--episodes" in entry["args"]
    assert str(episodes) in entry["args"]


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


def test_plan_only_loads_explicit_runtime_config(tmp_path: Path) -> None:
    store = tmp_path / "demo.sqlite3"
    store.write_text("", encoding="utf-8")
    config = tmp_path / "runtime-policy.json"
    config.write_text('{"provisional_memory":{"enabled":true}}', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--memories",
            str(store),
            "--config",
            str(config),
            "--plan-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"config_path={config.resolve()}" in result.stdout


def test_stdio_startup_stays_quiet_without_verbose(tmp_path: Path) -> None:
    store = tmp_path / "demo.sqlite3"
    store.write_text("", encoding="utf-8")
    config = tmp_path / "runtime-policy.json"
    config.write_text('{"provisional_memory":{"enabled":true}}', encoding="utf-8")
    state_root = tmp_path / "runtime-state"

    proc = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--memories",
            str(store),
            "--runtime-port",
            "0",
            "--config",
            str(config),
        ],
        env={
            **os.environ,
            "MNO_RUNTIME_STATE_ROOT": str(state_root),
            "NO_MCP_STDIO_TRACE": str(tmp_path / "mcp-stdio-trace.jsonl"),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            }
        ).encode("utf-8")
        framed = f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8") + body
        try:
            response, stderr = proc.communicate(input=framed, timeout=30.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            response, stderr = proc.communicate(timeout=5.0)
            trace_path = tmp_path / "mcp-stdio-trace.jsonl"
            trace = trace_path.read_text(encoding="utf-8") if trace_path.exists() else "<missing>"
            pytest.fail(
                f"MCP stdio child timed out: trace={trace!r} stdout={response!r} stderr={stderr!r}",
                pytrace=False,
            )
        assert proc.returncode == 0, stderr.decode("utf-8", errors="replace")
        assert b"protocolVersion" in response, stderr.decode("utf-8", errors="replace")
        assert b"runtime_url=" not in stderr
    finally:
        if proc.poll() is None:
            proc.kill()
