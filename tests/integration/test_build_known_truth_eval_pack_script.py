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
        store.add_candidate(_seed_candidate("c2", "Continuity requires explicit citations.", "conv_2"))
        store.add_candidate(_seed_candidate("c3", "We prioritize evidence over guesses.", "conv_3"))
    finally:
        store.close()


def test_build_known_truth_eval_pack_script(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "known_truth"
    _build_store(sqlite_path)

    result = subprocess.run(  # noqa: S603 - trusted fixed args in test harness
        [
            sys.executable,
            "tools/build_known_truth_eval_pack.py",
            "--memories",
            str(sqlite_path),
            "--cases",
            "12",
            "--fixture-mode",
            "trust-v2",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "truthset_jsonl=" in result.stdout
    truthset_path = out_dir / "truthset.known_truth.jsonl"
    summary_path = out_dir / "known_truth_summary.json"
    assert truthset_path.exists()
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert int(summary["total_cases"]) == 12
    families = summary.get("fixture_family_counts") or {}
    assert "unsupported_probe" in families
    assert "routine_chat" in families
