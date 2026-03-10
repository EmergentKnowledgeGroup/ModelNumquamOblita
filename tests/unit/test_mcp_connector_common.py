from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "tools" / "mcp_connector_common.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mcp_connector_common", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load mcp_connector_common module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_build_posix_and_windows_entries_are_stable(tmp_path: Path) -> None:
    module = _load_module()
    memories = tmp_path / "demo.sqlite3"
    memories.write_text("", encoding="utf-8")
    episodes = tmp_path / "episodes.json"
    episodes.write_text("[]", encoding="utf-8")

    posix = module.build_posix_stdio_entry(
        python_path="python3",
        launcher_path="/mnt/z/openaidata/numquamoblita/tools/run_claude_live_mcp.py",
        memories_path=str(memories),
        episodes_path=str(episodes),
        default_role="viewer",
        compat_mode="strict",
        mutations_enabled=True,
    )
    assert posix["command"] == "python3"
    assert posix["args"][0].endswith("/tools/run_claude_live_mcp.py")
    assert "--mutations-enabled" in posix["args"]
    assert str(memories) in posix["args"]

    windows = module.build_windows_wsl_stdio_entry(
        repo_root=Path("/mnt/z/openaidata/numquamoblita"),
        memories_path=memories,
        episodes_path=episodes,
        default_role="viewer",
        compat_mode="strict",
        mutations_enabled=False,
        distro_name="Ubuntu-24.04",
    )
    assert windows["command"] == r"C:\Windows\System32\wsl.exe"
    assert windows["args"][:4] == ["-d", "Ubuntu-24.04", "--cd", "/mnt/z/openaidata/numquamoblita"]
    assert windows["args"][4:6] == ["--exec", "python3"]
    assert "tools/run_claude_live_mcp.py" in windows["args"]
    assert str(memories) in windows["args"]


def test_unc_wsl_paths_convert_without_shelling_out() -> None:
    module = _load_module()
    converted, distro = module.wsl_path_from_windows(r"\\wsl$\Ubuntu-24.04\home\user\claude_no.sqlite3")
    assert converted == "/home/user/claude_no.sqlite3"
    assert distro == "Ubuntu-24.04"


def test_windows_drive_paths_convert_through_wslpath_runner() -> None:
    module = _load_module()

    class _Proc:
        def __init__(self, stdout: str):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def _runner(cmd, **_kwargs):
        assert cmd[-2:] == ["-a", "Z:/openaidata/NumquamOblita/runtime/stores/claude_no.sqlite3"]
        return _Proc("/mnt/z/openaidata/NumquamOblita/runtime/stores/claude_no.sqlite3\n")

    converted, distro = module.wsl_path_from_windows(
        r"Z:\openaidata\NumquamOblita\runtime\stores\claude_no.sqlite3",
        distro_name="Ubuntu-24.04",
        runner=_runner,
    )
    assert converted == "/mnt/z/openaidata/NumquamOblita/runtime/stores/claude_no.sqlite3"
    assert distro == "Ubuntu-24.04"


def test_merge_and_backup_preserve_existing_payload(tmp_path: Path) -> None:
    module = _load_module()
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"filesystem": {"command": "npx"}}, "preferences": {"sidebarMode": "chat"}}),
        encoding="utf-8",
    )

    merged = module.merge_mcp_server_entry(
        module.load_json_object(config_path),
        server_name="numquamoblita-live",
        entry={"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
    )
    backup = module.write_json_with_backup(config_path, merged)

    assert backup is not None
    assert backup.exists()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["preferences"]["sidebarMode"] == "chat"
    assert payload["mcpServers"]["filesystem"]["command"] == "npx"
    assert payload["mcpServers"]["numquamoblita-live"]["command"] == "python3"


def test_remove_mcp_server_entry_preserves_other_servers() -> None:
    module = _load_module()
    payload, removed = module.remove_mcp_server_entry(
        {"mcpServers": {"filesystem": {"command": "npx"}, "numquamoblita-live": {"command": "python3"}}},
        server_name="numquamoblita-live",
    )

    assert removed is True
    assert "numquamoblita-live" not in payload["mcpServers"]
    assert payload["mcpServers"]["filesystem"]["command"] == "npx"


def test_build_claude_code_add_json_cmd_and_detect_wsl() -> None:
    module = _load_module()
    cmd = module.build_claude_code_add_json_cmd(
        server_name="numquamoblita_live",
        entry={"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
        scope="user",
    )
    assert cmd[:5] == ["claude", "mcp", "add-json", "-s", "user"]
    assert cmd[5] == "numquamoblita_live"
    assert json.loads(cmd[6])["command"] == "python3"

    distro = module.detect_wsl_distro(env={"WSL_DISTRO_NAME": "Ubuntu-24.04"})
    assert distro == "Ubuntu-24.04"


def test_remove_claude_code_server_is_idempotent_when_missing() -> None:
    module = _load_module()

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "No user-scoped MCP server found with name: numquamoblita-live"

    def _runner(cmd, **_kwargs):
        assert cmd[:4] == ["claude", "mcp", "remove", "numquamoblita-live"]
        return _Proc()

    result = module.remove_claude_code_server(
        server_name="numquamoblita-live",
        scope="user",
        runner=_runner,
        which=lambda _binary: "claude",
    )

    assert result["remove_returncode"] == 1
    assert result["removed"] is False


def test_discover_memory_candidates_prefers_known_paths_and_labels(tmp_path: Path) -> None:
    module = _load_module()
    runtime_stores = tmp_path / "runtime" / "stores"
    runtime_stores.mkdir(parents=True, exist_ok=True)
    claude_store = runtime_stores / "claude_no.sqlite3"
    claude_store.write_text("", encoding="utf-8")
    lyra_store = runtime_stores / "no_lyra.sqlite3"
    lyra_store.write_text("", encoding="utf-8")
    duplicate_dir = tmp_path / "runtime" / "imports"
    duplicate_dir.mkdir(parents=True, exist_ok=True)
    duplicate = duplicate_dir / "claude_no.sqlite3"
    duplicate.write_text("", encoding="utf-8")

    candidates = module.discover_memory_candidates(repo_root=tmp_path)
    assert [row["path"] for row in candidates][:2] == [str(claude_store.resolve()), str(lyra_store.resolve())]

    labels = module.memory_candidate_labels(candidates)
    assert any("runtime/stores" in label for label in labels)


def test_default_episode_cards_path_prefers_reviewed_and_skips_rejects(tmp_path: Path) -> None:
    module = _load_module()
    episodes = tmp_path / "runtime" / "episodes"
    episodes.mkdir(parents=True, exist_ok=True)
    rejects = episodes / "episode_cards_20260309T102743Z.rejects.json"
    rejects.write_text("[]", encoding="utf-8")
    raw = episodes / "episode_cards_20260309T102743Z.json"
    raw.write_text("[]", encoding="utf-8")
    reviewed = episodes / "episode_cards.reviewed_20260309T102744Z.json"
    reviewed.write_text("[]", encoding="utf-8")

    picked = module.default_episode_cards_path(repo_root=tmp_path)

    assert picked == reviewed


def test_default_episode_cards_path_prefers_stable_reviewed_alias(tmp_path: Path) -> None:
    module = _load_module()
    episodes = tmp_path / "runtime" / "episodes"
    episodes.mkdir(parents=True, exist_ok=True)
    reviewed_alias = episodes / "episode_cards.reviewed.json"
    reviewed_alias.write_text("[]", encoding="utf-8")
    reviewed_stamped = episodes / "episode_cards.reviewed_20260309T102744Z.json"
    reviewed_stamped.write_text("[]", encoding="utf-8")

    picked = module.default_episode_cards_path(repo_root=tmp_path)

    assert picked == reviewed_alias
