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


def test_build_truthset_review_pack_and_compile(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "review_pack"
    _build_store(sqlite_path)

    generated = subprocess.run(
        [
            sys.executable,
            "tools/build_truthset_review_pack.py",
            "--memories",
            str(sqlite_path),
            "--total-cases",
            "6",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "candidate_cases=6" in generated.stdout
    candidates = out_dir / "truthset.candidates.jsonl"
    review_tsv = out_dir / "truthset.review.tsv"
    guide_md = out_dir / "truthset.review.md"
    assert candidates.exists()
    assert review_tsv.exists()
    assert guide_md.exists()

    lines = review_tsv.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 3
    lines[1] = lines[1].replace("\tPENDING\t", "\tACCEPT\t")
    for idx in range(2, len(lines)):
        lines[idx] = lines[idx].replace("\tPENDING\t", "\tREJECT\t")
    review_tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    compiled_dir = tmp_path / "compiled"
    compiled = subprocess.run(
        [
            sys.executable,
            "tools/build_truthset_review_pack.py",
            "--compile-reviewed",
            str(review_tsv),
            "--out-dir",
            str(compiled_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "reviewed_cases=1" in compiled.stdout
    reviewed_path = compiled_dir / "truthset.reviewed.jsonl"
    assert reviewed_path.exists()
    reviewed_rows = [json.loads(line) for line in reviewed_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(reviewed_rows) == 1
    assert reviewed_rows[0]["case_id"]


def test_build_truthset_review_pack_rejects_unknown_status(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "review_pack"
    _build_store(sqlite_path)

    subprocess.run(
        [
            sys.executable,
            "tools/build_truthset_review_pack.py",
            "--memories",
            str(sqlite_path),
            "--total-cases",
            "4",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    review_tsv = out_dir / "truthset.review.tsv"
    lines = review_tsv.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2
    lines[1] = lines[1].replace("\tPENDING\t", "\tACCEPTED\t")
    review_tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    compiled_dir = tmp_path / "compiled_invalid"
    compiled = subprocess.run(
        [
            sys.executable,
            "tools/build_truthset_review_pack.py",
            "--compile-reviewed",
            str(review_tsv),
            "--out-dir",
            str(compiled_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert compiled.returncode == 1
    assert "invalid status" in compiled.stderr
