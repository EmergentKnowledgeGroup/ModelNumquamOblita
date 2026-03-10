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
        salience=0.7,
    )


def _build_store(path: Path) -> None:
    store = SqliteAtomStore(path)
    try:
        store.add_candidate(
            _seed_candidate(
                "c1",
                "On Tuesday evening we discussed the migration checklist and confirmed rollback safeguards.",
                "conv_1",
            )
        )
        store.add_candidate(
            _seed_candidate(
                "c2",
                "You said the weekly planning ritual should start with priorities before implementation details.",
                "conv_2",
            )
        )
        store.add_candidate(
            _seed_candidate(
                "c3",
                "We agreed citations must accompany recall claims whenever confidence is low.",
                "conv_3",
            )
        )
    finally:
        store.close()


def test_validate_truthset_questions_script(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    eval_dir = tmp_path / "eval"

    eval_run = subprocess.run(
        [
            sys.executable,
            "tools/run_truthset_eval.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--out-dir",
            str(eval_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert eval_run.returncode == 0, eval_run.stdout + "\n" + eval_run.stderr

    quality_dir = tmp_path / "quality"
    quality_run = subprocess.run(
        [
            sys.executable,
            "tools/validate_truthset_questions.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(eval_dir / "truthset.generated.jsonl"),
            "--out-dir",
            str(quality_dir),
            "--max-weak-cases",
            "3",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert quality_run.returncode == 0, quality_run.stdout + "\n" + quality_run.stderr
    summary = json.loads((quality_dir / "question_validation_summary.json").read_text(encoding="utf-8"))
    assert summary["decision"] == "PASS"
    assert int(summary.get("weak_cases") or 0) <= 3
    assert int(summary.get("blocking_defect_cases") or 0) == 0


def test_validate_truthset_questions_script_flags_weak_prompt(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    truthset_path = tmp_path / "truthset.jsonl"
    truthset_path.write_text(
        json.dumps(
            {
                "case_id": "tc_0001",
                "case_type": "supported_recall",
                "fixture_family": "supported_recall",
                "query": "What do you remember about this?",
                "retrieval_query": "past task this and that",
                "expected_decision": "PASS",
                "expected_citations": ["conv_1#c1_msg"],
                "expected_atom_ids": ["atom:c1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "quality"
    result = subprocess.run(
        [
            sys.executable,
            "tools/validate_truthset_questions.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(truthset_path),
            "--out-dir",
            str(out_dir),
            "--max-weak-cases",
            "0",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 3
    summary = json.loads((out_dir / "question_validation_summary.json").read_text(encoding="utf-8"))
    assert summary["decision"] == "FAIL"
    assert summary["weak_cases"] >= 1


def test_validate_truthset_questions_emits_blocking_defect_tags(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    truthset_path = tmp_path / "truthset_blocking.jsonl"
    truthset_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "tc_0001",
                        "case_type": "supported_recall",
                        "fixture_family": "supported_recall",
                        "query": "What do you remember about Lyra when migration checklist?",
                        "retrieval_query": "Lyra migration checklist rollback safeguards",
                        "expected_decision": "PASS",
                        "expected_citations": ["conv_1#c1_msg"],
                        "expected_atom_ids": ["atom:c1"],
                    }
                ),
                json.dumps(
                    {
                        "case_id": "tc_0002",
                        "case_type": "routine_chat",
                        "fixture_family": "routine_chat",
                        "query": "No recall required here, just a normal reply.",
                        "retrieval_query": "normal chat",
                        "expected_decision": "PASS",
                        "expected_citations": [],
                        "expected_atom_ids": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "quality_blocking"
    result = subprocess.run(
        [
            sys.executable,
            "tools/validate_truthset_questions.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(truthset_path),
            "--out-dir",
            str(out_dir),
            "--max-weak-cases",
            "10",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 3
    summary = json.loads((out_dir / "question_validation_summary.json").read_text(encoding="utf-8"))
    assert summary["decision"] == "FAIL"
    assert int(summary.get("blocking_defect_cases") or 0) >= 1
    counts = summary.get("defect_tag_counts") or {}
    assert "malformed_when_clause" in counts or "instruction_like_routine_probe" in counts
    rows = json.loads((out_dir / "question_validation_cases.json").read_text(encoding="utf-8"))
    assert any("blocking_defect_tags" in row for row in rows if isinstance(row, dict))


def test_validate_truthset_questions_accepts_tc0009_and_tc0004_shapes(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    truthset_path = tmp_path / "truthset_tc0009_tc0004.jsonl"
    truthset_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "tc_0009",
                        "case_type": "semantic_correction",
                        "fixture_family": "semantic_correction",
                        "query": 'I might be mixing this up. Was this memory right: "Ill be my full furry self when you become fully"?',
                        "retrieval_query": "furry self becoming fully context cue for correction alignment",
                        "expected_decision": "PASS",
                        "expected_citations": [],
                        "expected_atom_ids": [],
                    }
                ),
                json.dumps(
                    {
                        "case_id": "tc_0004",
                        "case_type": "routine_chat",
                        "fixture_family": "routine_chat",
                        "query": "Random check-in: what are you in the mood to talk about?",
                        "retrieval_query": "",
                        "expected_decision": "PASS",
                        "expected_citations": [],
                        "expected_atom_ids": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "quality_tc0009_tc0004"
    result = subprocess.run(
        [
            sys.executable,
            "tools/validate_truthset_questions.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(truthset_path),
            "--out-dir",
            str(out_dir),
            "--max-weak-cases",
            "0",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    summary = json.loads((out_dir / "question_validation_summary.json").read_text(encoding="utf-8"))
    assert summary["decision"] == "PASS"
    assert int(summary.get("weak_cases") or 0) == 0
    assert int(summary.get("weak_non_routine_cases") or 0) == 0
    assert int(summary.get("weak_routine_cases") or 0) == 0
    assert int(summary.get("blocking_defect_cases") or 0) == 0
    rows = json.loads((out_dir / "question_validation_cases.json").read_text(encoding="utf-8"))
    rows_by_id = {str(row.get("case_id")): row for row in rows if isinstance(row, dict)}
    assert rows_by_id["tc_0009"]["defect_tags"] == []
    assert rows_by_id["tc_0009"]["blocking_defect_tags"] == []
    assert rows_by_id["tc_0009"]["weak"] is False
    assert rows_by_id["tc_0004"]["defect_tags"] == []
    assert rows_by_id["tc_0004"]["blocking_defect_tags"] == []
    assert rows_by_id["tc_0004"]["weak"] is False


def test_run_episode_latency_compare_script(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "compare"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_episode_latency_compare.py",
            "--memories",
            str(sqlite_path),
            "--build-episodes",
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    compare = json.loads((out_dir / "episode_latency_compare.json").read_text(encoding="utf-8"))
    assert "baseline" in compare
    assert "episodic" in compare
    assert "delta" in compare
    assert (out_dir / "episode_latency_compare.md").exists()
