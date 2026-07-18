from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import SqliteAtomStore


REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_ROOT = REPO_ROOT / "app" / "desktop"
RUNTIME_MANIFEST_PATH = DESKTOP_ROOT / "runtime-bundle.manifest.json"


def _seed_candidate(candidate_id: str, text: str, source_id: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_msg",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=["desktop_shell"],
        confidence=0.9,
        salience=0.72,
    )


def _build_store(path: Path) -> None:
    store = SqliteAtomStore(path)
    try:
        store.add_candidate(_seed_candidate("desktop_c1", "You keep the desktop shell flow local and explicit.", "conv_desktop"))
    finally:
        store.close()


def _write_ready_wizard_state(wizard_runs_root: Path, sqlite_path: Path, cards_path: Path) -> None:
    run_dir = wizard_runs_root / "wizard_packaged_smoke"
    run_dir.mkdir(parents=True, exist_ok=True)
    wizard_state = {
        "selected_input": {
            "kind": "mno_store_sqlite",
            "path": str(sqlite_path),
            "is_valid": True,
        },
        "store_validation": {
            "kind": "mno_store_sqlite",
            "path": str(sqlite_path),
            "is_valid": True,
            "store_fingerprint": "packaged_smoke_fp",
        },
        "published_set": {
            "episodes_path": str(cards_path),
            "build_id": "packaged_build_001",
        },
        "verify": {
            "status": "Safe",
            "remap_required": False,
        },
        "activation": {
            "draft_override": {
                "active": False,
            }
        },
    }
    (run_dir / "wizard_state.json").write_text(f"{json.dumps(wizard_state, indent=2)}\n", encoding="utf-8")
    (wizard_runs_root / "LATEST.json").write_text(
        f"{json.dumps({'run_id': run_dir.name}, indent=2)}\n",
        encoding="utf-8",
    )


def _expected_runtime_version() -> str:
    payload = json.loads(RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8"))
    runtime_version = str(payload.get("runtime_version") or "").strip()
    if not runtime_version:
        raise AssertionError(f"missing runtime_version in {RUNTIME_MANIFEST_PATH}")
    return runtime_version


def test_desktop_shell_node_suite_runs() -> None:
    npm_bin = shutil.which("npm.cmd") or shutil.which("npm")
    if npm_bin is None:
        pytest.skip("npm is required for the desktop shell node test suite")
    if not (DESKTOP_ROOT / "package.json").exists():
        pytest.skip("desktop shell package.json is not present in this worktree")
    result = subprocess.run(
        [npm_bin, "run", "desktop:test"],
        cwd=DESKTOP_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_desktop_boot_assets_expose_inline_repair_and_wrapping_paths() -> None:
    boot_html = (DESKTOP_ROOT / "boot.html").read_text(encoding="utf-8")
    assert 'id="btnBootInlineRepair"' in boot_html
    assert 'id="btnBootOpenSetup"' in boot_html
    assert 'id="bootMcpStatus"' in boot_html
    assert 'id="bootMcpMode"' in boot_html
    assert 'id="btnBootOpenMcpLogs"' in boot_html
    assert "ModelNumquamOblita Desktop" in boot_html
    boot_css = (DESKTOP_ROOT / "boot.css").read_text(encoding="utf-8")
    assert ".boot-path-value" in boot_css
    assert "overflow-wrap: anywhere" in boot_css
    main_js = (DESKTOP_ROOT / "main.js").read_text(encoding="utf-8")
    assert "title: 'ModelNumquamOblita Desktop'" in main_js
    assert "title: 'ModelNumquamOblita Runtime'" in main_js
    assert "desktop-shell:open-runtime-workspace" in main_js
    assert "desktop-shell:show-home" in main_js
    assert "desktop-shell:open-mcp-logs" in main_js
    assert "ensureMcpSidecar" in main_js
    assert "mcp_sidecar_state.json" in main_js
    assert "mcp_sidecar_settings.json" in main_js
    assert "refreshDesktopHomeState" in main_js
    assert "expectedRuntimeVersion: expectedRuntimeHealthVersion()" in main_js
    assert "desktopTab" in main_js
    assert "startRuntime({ setupMode: false, openWorkspace: false })" in main_js
    assert "managedMcpProfileForArtifactMode" in main_js
    assert "'--mutations-enabled'" in main_js
    assert "desktop-shell:get-managed-mcp-config" in main_js
    assert "desktop-shell:save-managed-mcp-config" in main_js
    assert "desktop-shell:pick-source-files" in main_js
    assert "desktop-shell:pick-source-folders" in main_js
    preload_js = (DESKTOP_ROOT / "preload.js").read_text(encoding="utf-8")
    assert "desktopWorkspace" in preload_js
    assert "openDesktopHome" in preload_js
    assert "openMcpLogs" in preload_js
    assert "getManagedMcpConfig" in preload_js
    assert "saveManagedMcpConfig" in preload_js
    assert "pickSourceFiles" in preload_js
    assert "pickSourceFolders" in preload_js
    boot_js = (DESKTOP_ROOT / "boot.js").read_text(encoding="utf-8")
    assert "bootMcpMode" in boot_js
    assert "current role" in boot_js
    assert "saved profiles" in boot_js
    runtime_js = (REPO_ROOT / "engine" / "runtime" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "desktopTab" in runtime_js
    assert "requestedDesktopTab" in runtime_js
    assert "btnWizardPickFiles" in runtime_js
    assert "btnWizardPickFolder" in runtime_js
    assert "wizardArchiveStoreSelect" in runtime_js


def test_run_live_runtime_normal_mode_writes_and_releases_runtime_lock(tmp_path: Path) -> None:
    state_root = tmp_path / "runtime_state"
    state_root.mkdir(parents=True, exist_ok=True)
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    cards_path = tmp_path / "episode_cards.reviewed.json"
    cards_path.write_text(json.dumps({"schema": "numquamoblita.episode_cards.reviewed.v1", "cards": []}) + "\n", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "run_live_runtime.py"),
            "--memories",
            str(sqlite_path),
            "--episodes",
            str(cards_path),
            "--port",
            "7349",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "MNO_RUNTIME_STATE_ROOT": str(state_root), "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lock_path = state_root / "live_runtime.lock.json"
    runtime_url = ""
    try:
        started = False
        deadline = time.time() + 10
        while time.time() < deadline:
            line = process.stdout.readline() if process.stdout else ""
            if "runtime_url=" in line:
                started = True
                runtime_url = line.split("=", 1)[1].strip()
            if lock_path.exists():
                break
        assert started, "runtime did not report a runtime_url"
        assert lock_path.exists(), "normal desktop runtime did not create a live runtime lock"
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert str(payload.get("store_fingerprint") or "").startswith("sqlite_store:v3:")
        assert str(payload.get("episodes_path") or "") == str(cards_path.resolve())
    finally:
        if runtime_url:
            request = Request(f"{runtime_url}/api/runtime/desktop/shutdown", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            assert payload["ok"] is True
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    deadline = time.time() + 10
    while time.time() < deadline and lock_path.exists():
        time.sleep(0.1)
    assert not lock_path.exists(), "runtime lock was not released after runtime exit"


@pytest.mark.skipif(os.name != "nt", reason="CTRL_BREAK process-group contract is Windows-specific")
def test_run_live_runtime_ctrl_break_stops_and_releases_lock(tmp_path: Path) -> None:
    state_root = tmp_path / "runtime_state"
    state_root.mkdir(parents=True)
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    cards_path = tmp_path / "episode_cards.reviewed.json"
    cards_path.write_text(json.dumps({"schema": "numquamoblita.episode_cards.reviewed.v1", "cards": []}) + "\n", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "run_live_runtime.py"),
            "--memories",
            str(sqlite_path),
            "--episodes",
            str(cards_path),
            "--port",
            "0",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "MNO_RUNTIME_STATE_ROOT": str(state_root), "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    lock_path = state_root / "live_runtime.lock.json"
    try:
        deadline = time.time() + 15
        while time.time() < deadline and not lock_path.exists():
            time.sleep(0.1)
        if not lock_path.exists():
            if process.poll() is None:
                process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(f"runtime did not create its ownership lock (code={process.returncode}):\n{stdout}\n{stderr}")
        process.send_signal(signal.CTRL_BREAK_EVENT)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stdout + "\n" + stderr
        assert "runtime_shutdown_reason=signal:SIGBREAK" in stdout + stderr
        assert not lock_path.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def _electron_ci_sandbox_args() -> list[str]:
    if os.environ.get("MNO_ELECTRON_TEST_NO_SANDBOX") == "1":
        return ["--no-sandbox"]
    return []


def test_electron_ci_sandbox_args_require_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNO_ELECTRON_TEST_NO_SANDBOX", raising=False)
    assert _electron_ci_sandbox_args() == []
    monkeypatch.setenv("MNO_ELECTRON_TEST_NO_SANDBOX", "1")
    assert _electron_ci_sandbox_args() == ["--no-sandbox"]


def test_desktop_shell_electron_smoke(tmp_path: Path) -> None:
    electron_bin = DESKTOP_ROOT / "node_modules" / ".bin" / "electron"
    if sys.platform.startswith("win"):
        electron_bin = DESKTOP_ROOT / "node_modules" / ".bin" / "electron.cmd"
    if not electron_bin.exists():
        pytest.skip("electron is not installed locally")
    command = [str(electron_bin), *_electron_ci_sandbox_args(), "."]
    if sys.platform.startswith("linux"):
        if shutil.which("xvfb-run") is None:
            pytest.skip("xvfb-run is required for the local Electron smoke test")
        command = ["xvfb-run", "-a", *command]

    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    cards_path = tmp_path / "episode_cards.reviewed.json"
    cards_path.write_text(json.dumps({"cards": []}) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            *command,
            "--repo-root",
            str(REPO_ROOT),
            "--memories",
            str(sqlite_path),
            "--episodes",
            str(cards_path),
            "--smoke-exit-when-ready",
            "--boot-timeout-ms",
            "20000",
        ],
        cwd=DESKTOP_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_desktop_shell_packaged_dir_smoke_uses_bundled_repo_root(tmp_path: Path) -> None:
    if sys.platform.startswith("win"):
        pytest.skip("Windows packaged smoke is not run from this Linux lane")
    if sys.platform == "darwin":
        pytest.skip("macOS packaged smoke is not run from this Linux lane")
    if shutil.which("npm") is None:
        pytest.skip("npm is required for the packaged desktop shell smoke test")
    if sys.platform.startswith("linux") and shutil.which("xvfb-run") is None:
        pytest.skip("xvfb-run is required for the packaged Electron smoke test")

    pack_result = subprocess.run(
        ["npm", "run", "desktop:pack:dir"],
        cwd=DESKTOP_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert pack_result.returncode == 0, pack_result.stdout + "\n" + pack_result.stderr

    packaged_root = DESKTOP_ROOT / "dist" / "linux-unpacked"
    executable = packaged_root / "modelnumquamoblita-desktop-shell"
    if not executable.exists():
        pytest.skip("packaged Linux executable is not present")
    bundled_python = packaged_root / "resources" / "mno_bundle" / "runtime" / "python" / "bin" / "python3"
    assert bundled_python.exists(), "managed bundled runtime was not packaged"

    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    cards_path = tmp_path / "episode_cards.reviewed.json"
    cards_path.write_text(json.dumps({"cards": []}) + "\n", encoding="utf-8")
    state_root = tmp_path / "desktop_runtime_state"
    wizard_runs_root = state_root / "wizard_runs"
    _write_ready_wizard_state(wizard_runs_root, sqlite_path, cards_path)

    command = [
        shutil.which("xvfb-run") or "xvfb-run",
        "-a",
        str(executable),
        *_electron_ci_sandbox_args(),
        "--smoke-exit-when-ready",
        "--boot-timeout-ms",
        "30000",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=packaged_root,
            env={
                **os.environ,
                "MNO_DESKTOP_STATE_ROOT": str(state_root),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"packaged desktop smoke timed out after {exc.timeout}s\ncommand={command}\nstdout={exc.stdout}\nstderr={exc.stderr}")
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    desktop_shell_root = state_root / "desktop_shell"
    shell_logs = sorted(desktop_shell_root.glob("desktop_shell_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    assert shell_logs, "desktop shell did not emit a runtime log"
    latest_log = shell_logs[0].read_text(encoding="utf-8")
    assert f"launch command={bundled_python}" in latest_log
    expected_runtime_version = _expected_runtime_version()
    last_known_good = json.loads((desktop_shell_root / "runtime_bundle.last_known_good.json").read_text(encoding="utf-8"))
    assert last_known_good["runtime_version"] == expected_runtime_version
