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


def test_build_human_eval_readout_script(tmp_path: Path) -> None:
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
        timeout=120,
    )
    assert eval_run.returncode == 0, eval_run.stdout + "\n" + eval_run.stderr

    readout_path = eval_dir / "human_readout.md"
    readout_run = subprocess.run(
        [
            sys.executable,
            "tools/build_human_eval_readout.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(eval_dir / "truthset.generated.jsonl"),
            "--records",
            str(eval_dir / "records.json"),
            "--summary",
            str(eval_dir / "summary.json"),
            "--out",
            str(readout_path),
            "--max-cases",
            "4",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert readout_run.returncode == 0, readout_run.stdout + "\n" + readout_run.stderr
    assert "human_readout_md=" in readout_run.stdout
    body = readout_path.read_text(encoding="utf-8")
    assert "## Case tc_0001" in body
    assert "### Script Response" in body
    assert "### Recall Route (Script Judgment)" in body
    assert "### Speed + Cost" in body
    assert "### Context Sent To Model" in body
    assert "### Memory Cards Chosen" in body
    assert "### Memory Seed (Expected Atoms)" in body


def test_run_oneclick_eval_script_skip_import(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    run_dir = tmp_path / "oneclick"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_oneclick_eval.py",
            "--skip-import",
            "--store",
            str(sqlite_path),
            "--run-dir",
            str(run_dir),
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--readout-max-cases",
            "4",
            "--max-weak-question-cases",
            "10",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "decision=PASS" in result.stdout
    assert "safety_verdict=PASS" in result.stdout
    assert "human_quality_verdict=PASS" in result.stdout

    manifest = json.loads((run_dir / "oneclick_manifest.json").read_text(encoding="utf-8"))
    assert manifest["decision"] == "PASS"
    step_names = [str(item.get("name") or "") for item in list(manifest.get("steps") or []) if isinstance(item, dict)]
    assert "run_responder_eval" in step_names
    artifacts = manifest.get("artifacts") or {}
    readout_raw = str(artifacts.get("human_readout_md") or "").strip()
    assert readout_raw
    readout_path = Path(readout_raw)
    assert readout_path.exists()
    readout = readout_path.read_text(encoding="utf-8")
    assert "Responder Eval Readout" in readout
    assert "## Q/A Audit Table" in readout
    assert "### tc_0001" in readout
    quality_summary_raw = str(artifacts.get("question_validation_summary_json") or "").strip()
    assert quality_summary_raw
    quality_summary = Path(quality_summary_raw)
    assert quality_summary.exists()
    quality_payload = json.loads(quality_summary.read_text(encoding="utf-8"))
    assert quality_payload["decision"] == "PASS"
    episode_cards_raw = str(artifacts.get("episode_cards_json") or "").strip()
    assert episode_cards_raw
    episode_cards = Path(episode_cards_raw)
    assert episode_cards.exists()
    episode_readout_raw = str(artifacts.get("episode_readout_md") or "").strip()
    assert episode_readout_raw
    episode_readout = Path(episode_readout_raw)
    assert episode_readout.exists()
    episode_review_tsv_raw = str(artifacts.get("episode_review_tsv") or "").strip()
    assert episode_review_tsv_raw
    episode_review_tsv = Path(episode_review_tsv_raw)
    assert episode_review_tsv.exists()
    assert (run_dir / "logs" / "02a_episode_cards.log").exists()
    assert (run_dir / "logs" / "02b_episode_readout.log").exists()
    assert (run_dir / "logs" / "02c_episode_review_pack.log").exists()
    assert (run_dir / "logs" / "02_eval.log").exists()
    assert (run_dir / "logs" / "02b_question_quality.log").exists()
    assert (run_dir / "logs" / "03_readout.log").exists()
    gate_path = Path(str(artifacts.get("acceptance_gate_json") or ""))
    gate_payload = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate_payload["safety_verdict"] == "PASS"
    assert gate_payload["human_quality_verdict"] == "PASS"
    assert int((gate_payload.get("quality") or {}).get("blocking_defect_cases") or 0) == 0


def test_run_oneclick_eval_script_acceptance_gate_fail(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    run_dir = tmp_path / "oneclick_fail_gate"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_oneclick_eval.py",
            "--skip-import",
            "--store",
            str(sqlite_path),
            "--run-dir",
            str(run_dir),
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--readout-max-cases",
            "4",
            "--max-weak-question-cases",
            "10",
            "--min-citation-hit-rate",
            "1.1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 3, result.stdout + "\n" + result.stderr
    assert "decision=FAIL" in result.stdout
    assert "gate_failures=" in result.stdout

    manifest = json.loads((run_dir / "oneclick_manifest.json").read_text(encoding="utf-8"))
    assert manifest["decision"] == "FAIL"
    artifacts = manifest.get("artifacts") or {}
    gate_raw = str(artifacts.get("acceptance_gate_json") or "").strip()
    assert gate_raw
    gate_path = Path(gate_raw)
    assert gate_path.exists()
    gate_payload = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate_payload["decision"] == "FAIL"
    assert gate_payload["safety_verdict"] == "FAIL"
    assert "citation_hit_rate_below_floor" in list(gate_payload.get("safety_failures") or [])
