from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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
            "kind": "sqlite_store",
            "path": str(sqlite_path),
            "is_valid": True,
        },
        "store_validation": {
            "kind": "sqlite_store",
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
    if shutil.which("npm") is None:
        pytest.skip("npm is required for the desktop shell node test suite")
    if not (DESKTOP_ROOT / "package.json").exists():
        pytest.skip("desktop shell package.json is not present in this worktree")
    result = subprocess.run(
        ["npm", "run", "desktop:test"],
        cwd=DESKTOP_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_desktop_shell_electron_smoke(tmp_path: Path) -> None:
    electron_bin = DESKTOP_ROOT / "node_modules" / ".bin" / "electron"
    if sys.platform.startswith("win"):
        electron_bin = DESKTOP_ROOT / "node_modules" / ".bin" / "electron.cmd"
    if not electron_bin.exists():
        pytest.skip("electron is not installed locally")
    command = [str(electron_bin), "."]
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
