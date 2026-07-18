from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "tools" / "run_mcp_connector_gui.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_mcp_connector_gui", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load run_mcp_connector_gui module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _make_repo(tmp_path: Path) -> Path:
    runtime_stores = tmp_path / "runtime" / "stores"
    runtime_stores.mkdir(parents=True, exist_ok=True)
    (runtime_stores / "claude_no.sqlite3").write_text("", encoding="utf-8")
    episodes_dir = tmp_path / "runtime" / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    (episodes_dir / "episode_cards.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_panel_preview_builds_client_payloads(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path="python3",
        which=lambda binary: "claude" if binary == "claude" else None,
    )

    preview = panel.build_preview(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "local",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
            "mutations_enabled": False,
        }
    )

    assert preview["server_name"] == "numquamoblita_live"
    assert preview["posix_entry"]["command"] == "python3"
    assert preview["windows_entry"]["command"] == r"C:\Windows\System32\wsl.exe"
    assert preview["claude_code_add_cmd"][:3] == ["claude", "mcp", "add-json"]
    assert preview["posix_entry"]["args"][0].endswith("/tools/run_claude_live_mcp.py")


def test_panel_install_claude_desktop_merges_and_backs_up(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path / "repo")
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text('{"mcpServers":{"filesystem":{"command":"npx"}}}', encoding="utf-8")
    module.find_windows_claude_desktop_config = lambda: config_path  # type: ignore[assignment]

    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")
    result = panel.install_claude_desktop(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "local",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        }
    )

    assert result["config_path"] == str(config_path)
    assert result["backup_path"]
    payload = module.load_json_object(config_path)
    assert payload["mcpServers"]["filesystem"]["command"] == "npx"
    assert payload["mcpServers"]["numquamoblita_live"]["command"] == r"C:\Windows\System32\wsl.exe"


def test_panel_remove_claude_desktop_updates_config(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path / "repo")
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(
        '{"mcpServers":{"filesystem":{"command":"npx"},"numquamoblita_live":{"command":"python3"}}}',
        encoding="utf-8",
    )
    module.find_windows_claude_desktop_config = lambda: config_path  # type: ignore[assignment]

    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")
    result = panel.remove_claude_desktop(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "local",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        }
    )

    assert result["removed"] is True
    payload = module.load_json_object(config_path)
    assert "numquamoblita_live" not in payload["mcpServers"]
    assert payload["mcpServers"]["filesystem"]["command"] == "npx"


def test_panel_install_claude_code_uses_shared_installer(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    captured = {}

    def _fake_install(*, server_name, entry, scope, claude_bin="claude", runner=None, which=None):
        captured["server_name"] = server_name
        captured["entry"] = entry
        captured["scope"] = scope
        return {"add_returncode": 0, "scope": scope}

    module.install_claude_code_server = _fake_install  # type: ignore[assignment]
    module.is_windows_platform = lambda: False  # type: ignore[assignment]
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path="python3",
        which=lambda binary: "claude" if binary == "claude" else None,
    )
    result = panel.install_claude_code(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "user",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        }
    )

    assert captured["server_name"] == "numquamoblita_live"
    assert captured["entry"]["command"] == "python3"
    assert captured["scope"] == "user"
    assert result["claude_code_add_cmd"][:3] == ["claude", "mcp", "add-json"]


def test_panel_export_bundle_builds_generic_sidecar_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")

    bundle = panel.export_bundle(
        {
            "target": "generic_sidecar",
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "user",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        }
    )

    assert bundle["target"] == "generic_sidecar"
    assert bundle["target_display"] == "Generic sidecar bundle"
    assert "launch_runtime.sh" in bundle["artifacts"]
    assert "generic_sidecar_bundle.json" in bundle["artifacts"]


def test_panel_save_export_bundle_writes_bundle_and_companion_files(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path / "repo")
    export_dir = tmp_path / "exported"
    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")

    result = panel.save_export_bundle(
        {
            "target": "openclaw",
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "user",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        },
        export_path=export_dir,
    )

    assert Path(result["export_path"]).exists()
    artifact_paths = [Path(item) for item in result["artifact_paths"]]
    assert any(path.name == "launch_runtime.sh" for path in artifact_paths)
    assert any(path.name == "openclaw_bundle.json" for path in artifact_paths)


def test_panel_remove_claude_code_uses_shared_remover(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    captured = {}

    def _fake_remove(*, server_name, scope, claude_bin="claude", runner=None, which=None):
        captured["server_name"] = server_name
        captured["scope"] = scope
        captured["claude_bin"] = claude_bin
        return {"remove_returncode": 0, "removed": True, "scope": scope}

    module.remove_claude_code_server = _fake_remove  # type: ignore[assignment]
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path="python3",
        which=lambda binary: "/usr/bin/claude" if binary == "claude" else None,
    )
    result = panel.remove_claude_code(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "user",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        }
    )

    assert captured["server_name"] == "numquamoblita_live"
    assert captured["scope"] == "user"
    assert result["removed"] is True


def test_current_state_prefers_native_windows_claude_code(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)

    class _Proc:
        def __init__(self, stdout: str = "", returncode: int = 0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    monkeypatch.setattr(module, "is_windows_platform", lambda: True)
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path=r"C:\Python313\python.exe",
        which=lambda binary: r"C:\Users\tester\AppData\Local\Programs\Claude\claude.exe"
        if binary in {"claude", "claude.exe", "claude.cmd", "claude.bat"}
        else None,
        runner=lambda *_args, **_kwargs: _Proc("Ubuntu-24.04\n"),
    )

    state = panel.current_state()

    assert state["claude_code_install_context"] == "native-windows-claude"
    assert state["claude_code_display"] == "native Windows CLI"
    assert state["claude_code_available"] is True
    assert state["claude_code_scope"] == "user"


def test_install_claude_code_prefers_native_windows_cli_entry(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    captured = {}
    native_claude = r"C:\Users\tester\AppData\Local\Programs\Claude\claude.exe"

    def _fake_install(*, server_name, entry, scope, claude_bin="claude", runner=None, which=None):
        captured["server_name"] = server_name
        captured["entry"] = entry
        captured["scope"] = scope
        captured["claude_bin"] = claude_bin
        captured["which_result"] = which("claude") if which is not None else None
        return {"add_returncode": 0, "scope": scope}

    monkeypatch.setattr(module, "is_windows_platform", lambda: True)
    monkeypatch.setattr(module, "install_claude_code_server", _fake_install)
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path=r"C:\Python313\python.exe",
        which=lambda binary: native_claude if binary in {"claude", "claude.exe", "claude.cmd", "claude.bat"} else None,
    )

    result = panel.install_claude_code(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "user",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        }
    )

    assert captured["server_name"] == "numquamoblita_live"
    assert captured["entry"]["command"] == r"C:\Windows\System32\wsl.exe"
    assert captured["entry"]["type"] == "stdio"
    assert "--exec" in captured["entry"]["args"]
    python_index = captured["entry"]["args"].index("--exec") + 1
    selected = captured["entry"]["args"][python_index:python_index + 2]
    assert selected[0].startswith("/")
    assert "python3" in selected[0] or selected == ["/usr/bin/env", "python3"]
    assert "tools/run_claude_live_mcp.py" in captured["entry"]["args"]
    assert captured["scope"] == "user"
    assert captured["claude_bin"] == native_claude
    assert captured["which_result"] == native_claude
    assert result["install_context"] == "native-windows-claude"


def test_install_claude_code_prefers_http_sidecar_for_native_windows_cli_when_managed(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    captured = {}
    native_claude = r"C:\Users\tester\AppData\Local\Programs\Claude\claude.exe"

    def _fake_install(*, server_name, entry, scope, claude_bin="claude", runner=None, which=None):
        captured["server_name"] = server_name
        captured["entry"] = entry
        captured["scope"] = scope
        captured["claude_bin"] = claude_bin
        return {"add_returncode": 0, "scope": scope}

    monkeypatch.setattr(module, "is_windows_platform", lambda: True)
    monkeypatch.setattr(module, "install_claude_code_server", _fake_install)
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path=r"C:\Python313\python.exe",
        which=lambda binary: native_claude if binary in {"claude", "claude.exe", "claude.cmd", "claude.bat"} else None,
    )

    result = panel.install_claude_code(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "user",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
            "mcp_http_url": "http://127.0.0.1:8765/mcp",
            "mcp_http_managed": True,
            "mcp_http_status": "ready",
        }
    )

    assert captured["server_name"] == "numquamoblita_live"
    assert captured["entry"]["type"] == "http"
    assert captured["entry"]["url"] == "http://127.0.0.1:8765/mcp"
    assert captured["scope"] == "user"
    assert captured["claude_bin"] == native_claude
    assert result["install_context"] == "native-windows-claude"


def test_native_windows_install_normalizes_pythonw_to_python(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    captured = {}
    native_claude = r"C:\Users\tester\AppData\Local\Programs\Claude\claude.exe"

    def _fake_install(*, server_name, entry, scope, claude_bin="claude", runner=None, which=None):
        captured["entry"] = entry
        captured["claude_bin"] = claude_bin
        return {"add_returncode": 0, "scope": scope}

    monkeypatch.setattr(module, "is_windows_platform", lambda: True)
    monkeypatch.setattr(module, "install_claude_code_server", _fake_install)
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path=r"C:\Python313\pythonw.exe",
        which=lambda binary: native_claude if binary in {"claude", "claude.exe", "claude.cmd", "claude.bat"} else None,
    )

    panel.install_claude_code(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "user",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        }
    )

    assert captured["entry"]["type"] == "stdio"
    assert captured["entry"]["command"] == r"C:\Windows\System32\wsl.exe"
    python_index = captured["entry"]["args"].index("--exec") + 1
    selected = captured["entry"]["args"][python_index:python_index + 2]
    assert selected[0].startswith("/")
    assert "python3" in selected[0] or selected == ["/usr/bin/env", "python3"]
    assert "tools/run_claude_live_mcp.py" in captured["entry"]["args"]


def test_default_native_windows_python_path_uses_sys_executable(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)

    monkeypatch.setattr(module, "is_windows_platform", lambda: True)
    monkeypatch.setattr(module.sys, "executable", r"C:\Python313\pythonw.exe", raising=False)
    panel = module.ConnectorControlPanel(repo_root=repo_root)

    assert panel.python_path == r"C:\Python313\python.exe"


def test_normalize_host_input_path_converts_windows_drive_path_on_posix_host(tmp_path: Path) -> None:
    module = _load_module()
    module.is_windows_platform = lambda: False  # type: ignore[assignment]
    repo_root = _make_repo(tmp_path)
    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")
    resolved = panel._normalize_host_input_path(r"Z:\mno-workspace\runtime\stores\claude_no.sqlite3")

    assert resolved == "/mnt/z/mno-workspace/runtime/stores/claude_no.sqlite3"


def test_resolve_payload_normalizes_windows_episode_path_on_posix_host(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    module.is_windows_platform = lambda: False  # type: ignore[assignment]
    repo_root = _make_repo(tmp_path)
    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")
    captured: dict[str, str] = {}
    episode_path = repo_root / "runtime" / "episodes" / "episode_cards.reviewed.json"
    episode_path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(panel, "_resolve_existing_path", lambda _raw: repo_root / "runtime" / "stores" / "claude_no.sqlite3")

    def _fake_resolve_episode_cards_path(raw: str, *, repo_root: Path):
        captured["raw"] = raw
        return episode_path

    monkeypatch.setattr(module, "resolve_episode_cards_path", _fake_resolve_episode_cards_path)

    panel._resolve_payload(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "episodes_path": r"Z:\mno-workspace\runtime\episodes\episode_cards.reviewed.json",
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "local",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
            "mutations_enabled": False,
        }
    )

    assert captured["raw"] == "/mnt/z/mno-workspace/runtime/episodes/episode_cards.reviewed.json"


def test_help_text_and_filetypes_cover_required_fields() -> None:
    module = _load_module()
    assert {"default_role", "claude_code_scope", "compat_mode", "mutations_enabled", "episode_cards"} <= set(module.HELP_TEXT)
    assert any("*.sqlite3" in pattern for _label, pattern in module.MEMORY_FILETYPES)
    assert module.EXPORT_FILETYPES[0][0] == "JSON files"


def test_panel_rejects_raw_ia_db_json(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path / "repo")
    ia_db = tmp_path / "claude_db.json"
    ia_db.write_text(
        '{"generated_at":"2026-03-09T00:00:00Z","conversations":[{"id":"c1","messages":[{"role":"user","text":"hello"}]}]}',
        encoding="utf-8",
    )
    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")

    try:
        panel.build_preview(
            {
                "memories_path": str(ia_db),
                "server_name": "numquamoblita_live",
                "default_role": "viewer",
                "claude_code_scope": "local",
                "compat_mode": "strict",
                "wsl_distro": "Ubuntu-24.04",
                "mutations_enabled": False,
            }
        )
    except ValueError as exc:
        assert "IA transcript archive" in str(exc)
    else:
        raise AssertionError("expected IA db.json validation failure")


def test_export_bundle_writes_signature_and_backup(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path / "repo")
    export_path = tmp_path / "bundle.json"
    export_path.write_text('{"hello":"world"}', encoding="utf-8")
    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")

    result = panel.save_export_bundle(
        {
            "memories_path": str(repo_root / "runtime" / "stores" / "claude_no.sqlite3"),
            "server_name": "numquamoblita_live",
            "default_role": "viewer",
            "claude_code_scope": "local",
            "compat_mode": "strict",
            "wsl_distro": "Ubuntu-24.04",
        },
        export_path=export_path,
    )

    assert result["export_path"] == str(export_path)
    assert result["backup_path"]
    assert panel.export_bundle_has_connector_signature(export_path) is True


def test_build_wsl_proxy_launch_cmd_and_launcher_flow() -> None:
    module = _load_module()
    assert module.build_wsl_proxy_launch_cmd(cmd_windows_path=r"Z:\repo\tools\run_mcp_connector_gui.cmd") == [
        "cmd.exe",
        "/c",
        "start",
        "",
        r"Z:\repo\tools\run_mcp_connector_gui.cmd",
    ]

    calls = []

    class _Proc:
        def __init__(self, stdout: str = "", returncode: int = 0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    def _runner(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[:2] == ["wslpath", "-w"]:
            return _Proc(r"Z:\repo\tools\run_mcp_connector_gui.cmd\n")
        return _Proc("")

    result = module.launch_windows_gui_from_wsl(cmd_path=Path("/mnt/z/repo/tools/run_mcp_connector_gui.cmd"), runner=_runner)
    assert result["ok"] is True
    assert calls[0][:2] == ["wslpath", "-w"]
    assert calls[1][:4] == ["cmd.exe", "/c", "start", ""]


def test_current_state_exposes_help_and_candidates(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)
    panel = module.ConnectorControlPanel(repo_root=repo_root, python_path="python3")
    state = panel.current_state()
    assert state["memory_candidates"]
    assert "help_text" in state
    assert state["memory_candidates"][0]["display_label"]


def test_current_state_treats_missing_wsl_as_unavailable(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    repo_root = _make_repo(tmp_path)

    def _runner(_cmd, **_kwargs):
        raise FileNotFoundError("wsl.exe")

    monkeypatch.setattr(module, "is_windows_platform", lambda: True)
    panel = module.ConnectorControlPanel(
        repo_root=repo_root,
        python_path=r"C:\Python313\python.exe",
        runner=_runner,
        which=lambda _binary: None,
    )

    state = panel.current_state()

    assert state["wsl_distro"] == ""
    assert state["claude_code_available"] is False
    assert state["claude_code_install_context"] == "missing"
