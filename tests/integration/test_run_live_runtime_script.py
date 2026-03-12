from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import SqliteAtomStore


REPO_ROOT = Path(__file__).resolve().parents[2]


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
        topics=["integration"],
        confidence=0.9,
        salience=0.72,
    )


def _build_store(path: Path) -> None:
    store = SqliteAtomStore(path)
    try:
        store.add_candidate(_seed_candidate("c1", "You prefer tea at midnight.", "conv_1"))
    finally:
        store.close()


def test_run_live_runtime_plan_only_memories_path(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_live_runtime.py",
            "--memories",
            str(sqlite_path),
            "--host",
            "127.0.0.1",
            "--port",
            "7431",
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "mode=plan_only" in result.stdout
    assert f"memories_path={sqlite_path}" in result.stdout
    assert "store_backend=sqlite" in result.stdout
    assert "runtime_url=http://127.0.0.1:7431" in result.stdout
    assert "launch_mode=normal" in result.stdout


def test_run_live_runtime_plan_only_from_manifest(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    manifest_path = tmp_path / "live_manifest.json"
    manifest_path.write_text(json.dumps({"store_path": str(sqlite_path)}) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_live_runtime.py",
            "--from-live-manifest",
            str(manifest_path),
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert f"memories_path={sqlite_path}" in result.stdout
    assert "launch_mode=normal" in result.stdout


def test_run_live_runtime_plan_only_with_episode_cards(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    cards_path = tmp_path / "episode_cards.json"
    cards_path.write_text(json.dumps({"cards": []}) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_live_runtime.py",
            "--memories",
            str(sqlite_path),
            "--episodes",
            str(cards_path),
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert f"episode_cards_path={cards_path}" in result.stdout
    assert "launch_mode=normal" in result.stdout


def test_run_live_runtime_plan_only_setup_mode(tmp_path: Path) -> None:
    setup_store = tmp_path / "desktop_shell" / "setup_mode.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_live_runtime.py",
            "--setup-mode",
            "--setup-store",
            str(setup_store),
            "--host",
            "127.0.0.1",
            "--port",
            "7431",
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "launch_mode=setup_mode" in result.stdout
    assert f"memories_path={setup_store}" in result.stdout
    assert "episode_cards_path=" in result.stdout


def test_run_live_runtime_setup_mode_rejects_live_store_flags(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_live_runtime.py",
            "--setup-mode",
            "--memories",
            str(sqlite_path),
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    assert "--setup-mode cannot be combined with --memories or --from-live-manifest" in result.stdout


def test_run_live_runtime_manifest_requires_store_path(tmp_path: Path) -> None:
    manifest_path = tmp_path / "live_manifest.json"
    manifest_path.write_text(json.dumps({"decision": "PASS"}) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_live_runtime.py",
            "--from-live-manifest",
            str(manifest_path),
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    assert "error=live manifest missing required field: store_path" in result.stdout
