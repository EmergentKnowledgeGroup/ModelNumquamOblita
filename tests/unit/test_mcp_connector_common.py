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
        launcher_path="/mnt/z/mno-workspace/tools/run_claude_live_mcp.py",
        memories_path=str(memories),
        episodes_path=str(episodes),
        default_role="viewer",
        compat_mode="strict",
        mutations_enabled=True,
    )
    assert posix["type"] == "stdio"
    assert posix["command"] == "python3"
    assert posix["env"] == {}
    assert posix["args"][0].endswith("/tools/run_claude_live_mcp.py")
    assert "--mutations-enabled" in posix["args"]
    assert str(memories) in posix["args"]

    class _Proc:
        def __init__(self, stdout: str):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def _runner(cmd, **_kwargs):
        if "-c" in cmd and "--exec" in cmd:
            candidate = str(cmd[cmd.index("--exec") + 1])
            if candidate == "/usr/local/bin/python3.14":
                return _Proc("3.14\n")
            return type("Failed", (), {"returncode": 1, "stdout": "", "stderr": "missing"})()
        return _Proc(f"/converted/{Path(str(cmd[-1])).name}\n")

    windows = module.build_windows_wsl_stdio_entry(
        repo_root="/mnt/z/mno-workspace",
        memories_path=memories,
        episodes_path=episodes,
        default_role="viewer",
        compat_mode="strict",
        mutations_enabled=False,
        distro_name="Ubuntu-24.04",
        runner=_runner,
    )
    assert windows["type"] == "stdio"
    assert windows["command"] == r"C:\Windows\System32\wsl.exe"
    assert windows["env"] == {}
    assert windows["args"][:4] == ["-d", "Ubuntu-24.04", "--cd", "/mnt/z/mno-workspace"]
    assert windows["args"][4:6] == ["--exec", "/usr/local/bin/python3.14"]
    assert "tools/run_claude_live_mcp.py" in windows["args"]
    raw_memories = str(memories)
    expected_memories = raw_memories
    if len(raw_memories) >= 2 and raw_memories[1] == ":":
        path_tail = raw_memories[2:].lstrip("\\").replace("\\", "/")
        expected_memories = f"/mnt/{raw_memories[0].lower()}/{path_tail}"
    assert expected_memories in windows["args"]


def test_unc_wsl_paths_convert_without_shelling_out() -> None:
    module = _load_module()
    converted, distro = module.wsl_path_from_windows(r"\\wsl$\Ubuntu-24.04\home\user\claude_no.sqlite3")
    assert converted == "/home/user/claude_no.sqlite3"
    assert distro == "Ubuntu-24.04"


def test_windows_drive_paths_convert_without_live_wsl() -> None:
    module = _load_module()

    class _Proc:
        def __init__(self, stdout: str):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def _runner(cmd, **_kwargs):
        raise AssertionError(f"drive conversion must not invoke WSL: {cmd}")

    converted, distro = module.wsl_path_from_windows(
        r"Z:\mno-workspace\runtime\stores\claude_no.sqlite3",
        distro_name="Ubuntu-24.04",
        runner=_runner,
    )
    assert converted == "/mnt/z/mno-workspace/runtime/stores/claude_no.sqlite3"
    assert distro == "Ubuntu-24.04"


def test_windows_drive_relative_paths_are_resolved_by_wslpath() -> None:
    module = _load_module()
    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "/home/user/relative/file\n"
        stderr = ""

    def _runner(cmd, **_kwargs):
        calls.append(cmd)
        return _Proc()

    converted, distro = module.wsl_path_from_windows(
        r"C:relative\file",
        distro_name="Ubuntu-24.04",
        runner=_runner,
    )

    assert converted == "/home/user/relative/file"
    assert distro == "Ubuntu-24.04"
    assert len(calls) == 1
    assert calls[0][0].lower().endswith("wsl.exe")
    assert calls[0][1:] == ["-d", "Ubuntu-24.04", "wslpath", "-a", "C:relative/file"]


def test_detect_wsl_distro_returns_empty_when_command_is_missing() -> None:
    module = _load_module()

    def _runner(_cmd, **_kwargs):
        raise FileNotFoundError("wsl.exe")

    assert module.detect_wsl_distro(env={}, runner=_runner) == ""


def test_wsl_python_discovery_does_not_assume_usr_bin_python3() -> None:
    module = _load_module()

    class _Proc:
        def __init__(self, returncode: int, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def _runner(cmd, **_kwargs):
        candidate = cmd[cmd.index("--exec") + 1]
        if candidate == "/usr/local/bin/python3.13":
            return _Proc(0, "3.13\n")
        return _Proc(1)

    assert module.discover_wsl_python_path(distro_name="Ubuntu", runner=_runner) == "/usr/local/bin/python3.13"


def test_wsl_python_discovery_uses_one_path_probe_when_supported() -> None:
    module = _load_module()
    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = '{"path":"/opt/python/bin/python3.14","version":[3,14]}\n'
        stderr = ""

    def _runner(cmd, **_kwargs):
        calls.append(list(cmd))
        return _Proc()

    assert module.discover_wsl_python_path(distro_name="Ubuntu", runner=_runner) == "/opt/python/bin/python3.14"
    assert len(calls) == 1


def test_wsl_entry_uses_target_runtime_path_resolution_when_discovery_is_unavailable(tmp_path: Path) -> None:
    module = _load_module()

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "unavailable"

    entry = module.build_windows_wsl_stdio_entry(
        repo_root="/mnt/z/mno",
        memories_path=tmp_path / "memories.json",
        episodes_path=None,
        default_role="viewer",
        compat_mode="strict",
        mutations_enabled=False,
        distro_name="Ubuntu",
        runner=lambda *_args, **_kwargs: _Proc(),
    )
    exec_index = entry["args"].index("--exec")
    assert entry["args"][exec_index + 1:exec_index + 3] == ["/usr/bin/env", "python3"]


def test_default_memory_path_scans_selected_legacy_imports_root(tmp_path: Path) -> None:
    module = _load_module()
    nested = tmp_path / ".runtime" / "imports" / "export" / "memories.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("[]", encoding="utf-8")
    assert module.default_memory_path(repo_root=tmp_path) == nested


def test_empty_injected_environment_does_not_read_process_profile(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "ProcessUser"))
    monkeypatch.setenv("USERNAME", "ProcessUser")
    assert module._current_windows_user_dir(users_root=tmp_path / "Users", env={}) is None


def test_detect_wsl_distro_returns_empty_when_no_distro_is_available() -> None:
    module = _load_module()

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "There is no distribution with the supplied name."

    assert module.detect_wsl_distro(env={}, runner=lambda *_args, **_kwargs: _Proc()) == ""


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


def test_atomic_json_replace_failure_preserves_live_config(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    config_path = tmp_path / "claude.json"
    original = '{"mcpServers":{"working":{"command":"old"}}}\n'
    config_path.write_text(original, encoding="utf-8")
    real_replace = module.os.replace

    def _replace(source, target):
        if Path(target) == config_path:
            raise OSError("injected replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", _replace)
    try:
        module.write_json_with_backup(config_path, {"mcpServers": {"new": {"command": "new"}}})
    except OSError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("expected injected replacement failure")
    assert config_path.read_text(encoding="utf-8") == original


def test_windows_config_discovery_is_current_user_scoped_by_default(tmp_path: Path) -> None:
    module = _load_module()
    users = tmp_path / "Users"
    current = users / "Current"
    other = users / "Other"
    other_config = other / module.WINDOWS_CLAUDE_DESKTOP_REL
    other_config.parent.mkdir(parents=True)
    other_config.write_text("{}", encoding="utf-8")
    current_config = current / module.WINDOWS_CLAUDE_DESKTOP_REL
    assert module.find_windows_claude_desktop_config(
        users_root=users, env={"USERPROFILE": str(current)}
    ) == current_config
    assert module.find_windows_claude_code_config(
        users_root=users, env={"USERPROFILE": str(current)}
    ) == current / module.WINDOWS_CLAUDE_CODE_REL


def test_claude_install_stages_and_verifies_without_removing_existing_first() -> None:
    module = _load_module()
    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "add-json get remove\n"
        stderr = ""

    def _runner(cmd, **_kwargs):
        calls.append(list(cmd))
        return _Proc()

    result = module.install_claude_code_server(
        server_name="numquamoblita-live",
        entry={"type": "stdio", "command": "python3", "args": ["-m", "mno"]},
        scope="user",
        runner=_runner,
        which=lambda _binary: "claude",
    )
    assert result["stage_verified"] is True
    assert result["verified"] is True
    real_add_index = next(
        index for index, cmd in enumerate(calls)
        if cmd[:3] == ["claude", "mcp", "add-json"] and cmd[5] == "numquamoblita-live"
    )
    prior_removes = [cmd for cmd in calls[:real_add_index] if cmd[:3] == ["claude", "mcp", "remove"]]
    assert prior_removes
    assert all("-mno-stage-" in cmd[3] for cmd in prior_removes)


def test_failed_staged_add_never_removes_existing_connector() -> None:
    module = _load_module()
    calls: list[list[str]] = []

    class _Proc:
        def __init__(self, returncode=0, stdout="add-json get remove", stderr=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def _runner(cmd, **_kwargs):
        calls.append(list(cmd))
        if cmd[:3] == ["claude", "mcp", "add-json"]:
            return _Proc(1, "", "invalid entry")
        return _Proc()

    try:
        module.install_claude_code_server(
            server_name="numquamoblita-live", entry={"command": "broken"}, scope="user",
            runner=_runner, which=lambda _binary: "claude",
        )
    except RuntimeError as exc:
        assert "existing connector preserved" in str(exc)
    else:
        raise AssertionError("expected staged add failure")
    assert not any(cmd[:4] == ["claude", "mcp", "remove", "numquamoblita-live"] for cmd in calls)


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
    payload = json.loads(cmd[6])
    assert payload["type"] == "stdio"
    assert payload["command"] == "python3"

    distro = module.detect_wsl_distro(env={"WSL_DISTRO_NAME": "Ubuntu-24.04"})
    assert distro == "Ubuntu-24.04"


def test_build_http_entry_and_add_json_cmd_preserve_http_shape() -> None:
    module = _load_module()
    entry = module.build_http_entry(url="http://127.0.0.1:8765/mcp")
    assert entry["type"] == "http"
    assert entry["url"] == "http://127.0.0.1:8765/mcp"
    cmd = module.build_claude_code_add_json_cmd(
        server_name="numquamoblita_live",
        entry=entry,
        scope="user",
    )
    payload = json.loads(cmd[6])
    assert payload["type"] == "http"
    assert payload["url"] == "http://127.0.0.1:8765/mcp"


def test_run_subprocess_hidden_on_windows_adds_no_console_flags(monkeypatch) -> None:
    module = _load_module()
    calls: dict[str, object] = {}

    class _FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = None

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(module, "is_windows_platform", lambda **_kwargs: True)
    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    monkeypatch.setattr(module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(module.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(module.subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(module.subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)

    proc = module.run_subprocess_hidden_on_windows(["wsl.exe", "-l", "-q"], check=False, capture_output=True, text=True)

    assert proc.returncode == 0
    assert calls["cmd"] == ["wsl.exe", "-l", "-q"]
    kwargs = dict(calls["kwargs"])
    assert kwargs["creationflags"] == 0x08000000
    startupinfo = kwargs["startupinfo"]
    assert isinstance(startupinfo, _FakeStartupInfo)
    assert startupinfo.dwFlags == 0x00000001
    assert startupinfo.wShowWindow == 0


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
