from __future__ import annotations

import json
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


def test_desktop_shell_node_suite_runs() -> None:
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
    if shutil.which("xvfb-run") is None:
        pytest.skip("xvfb-run is required for the local Electron smoke test")

    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    cards_path = tmp_path / "episode_cards.reviewed.json"
    cards_path.write_text(json.dumps({"cards": []}) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            "xvfb-run",
            "-a",
            str(electron_bin),
            ".",
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
