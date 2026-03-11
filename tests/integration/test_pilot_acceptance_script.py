from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import SqliteAtomStore
from tests.integration.helpers.truthset import build_truthset


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

def test_run_pilot_acceptance_script(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "pilot"
    _build_store(sqlite_path)

    result = subprocess.run(  # noqa: S603 - trusted fixed args in test harness
        [
            sys.executable,
            "tools/run_pilot_acceptance.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--max-weak-question-cases",
            "6",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decision=PASS" in result.stdout
    manifest_path = out_dir / "pilot_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["decision"] == "PASS"
    assert len(manifest["steps"]) == 4
    assert {step["name"] for step in manifest["steps"]} == {
        "plan_only",
        "truthset_eval",
        "load_harness",
        "phase7_signoff",
    }
    pilot_report = manifest.get("pilot_report") or {}
    assert pilot_report
    assert Path(str(pilot_report.get("json") or "")).exists()
    assert Path(str(pilot_report.get("markdown") or "")).exists()
    assert Path(str(pilot_report.get("text") or "")).exists()

    support_bundle = list(out_dir.glob("support_bundle_*.zip"))
    assert support_bundle
    assert (out_dir / "pilot_manifest.md").exists()
    assert (out_dir / "pilot_brief.txt").exists()
    report_payload = json.loads((out_dir / "pilot_report.json").read_text(encoding="utf-8"))
    assert report_payload["decision"] == "PASS"
    assert "recommendation" in report_payload


def test_run_pilot_acceptance_forwards_latency_overrides_to_signoff(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "pilot"
    _build_store(sqlite_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_pilot_acceptance.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--max-eval-p95-latency-ms",
            "25000",
            "--max-load-p95-latency-ms",
            "26000",
            "--max-weak-question-cases",
            "6",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decision=PASS" in result.stdout
    manifest = json.loads((out_dir / "pilot_manifest.json").read_text(encoding="utf-8"))
    signoff_step = next(item for item in manifest["steps"] if item["name"] == "phase7_signoff")
    signoff_cmd = [str(part) for part in signoff_step["command"]]
    assert "--max-eval-p95-latency-ms" in signoff_cmd
    assert "--max-load-p95-latency-ms" in signoff_cmd
    assert "25000.0" in signoff_cmd
    assert "26000.0" in signoff_cmd


def test_run_pilot_acceptance_script_with_reviewed_truthset(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    truthset_path = tmp_path / "truthset.reviewed.jsonl"
    out_dir = tmp_path / "pilot"
    _build_store(sqlite_path)
    build_truthset(sqlite_path, truthset_path, total_cases=6)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_pilot_acceptance.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(truthset_path),
            "--require-reviewed-truthset",
            "--requested-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--max-weak-question-cases",
            "6",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decision=PASS" in result.stdout
    assert "pilot_report_json=" in result.stdout

    manifest = json.loads((out_dir / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert manifest["truthset"]["mode"] == "explicit"
    assert Path(manifest["truthset"]["path"]) == truthset_path
    assert int(manifest["truthset"]["case_count"]) == 6
    assert manifest["truthset"]["quality"]["decision"] == "PASS"
    step_commands = {str(step["name"]): [str(part) for part in list(step["command"])] for step in manifest["steps"]}
    for step_name in ("plan_only", "truthset_eval", "phase7_signoff"):
        command = step_commands[step_name]
        assert "--truthset" in command
        assert str(truthset_path) in command

    report_payload = json.loads((out_dir / "pilot_report.json").read_text(encoding="utf-8"))
    assert report_payload["truthset_mode"] == "explicit"
    assert Path(report_payload["truthset_path"]) == truthset_path
    assert int(report_payload["truthset_case_count"]) == 6
    assert report_payload["truthset_quality"]["decision"] == "PASS"


def test_run_pilot_acceptance_truthset_quality_gate_fails(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    truthset_path = tmp_path / "truthset.reviewed.jsonl"
    out_dir = tmp_path / "pilot"
    _build_store(sqlite_path)
    build_truthset(sqlite_path, truthset_path, total_cases=4)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_pilot_acceptance.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(truthset_path),
            "--requested-cases",
            "4",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--truthset-min-cases",
            "8",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "decision=FAIL" in result.stdout
    manifest = json.loads((out_dir / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert manifest["decision"] == "FAIL"
    quality = manifest["truthset"]["quality"]
    assert quality["decision"] == "FAIL"
    assert "truthset_min_cases_not_met" in quality["reasons"]


def test_run_pilot_acceptance_trust_regression_gate_fails(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "pilot"
    baseline = tmp_path / "baseline_summary.json"
    _build_store(sqlite_path)
    baseline.write_text(
        json.dumps(
            {
                "decision_accuracy": 1.0,
                "citation_hit_rate": 1.0,
                "retrieval_hit_rate": 1.0,
                "abstain_precision": 1.0,
                "false_memory_rate": -1.0,
                "p95_latency_ms": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_pilot_acceptance.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--batch-size",
            "2",
            "--batch-pause-ms",
            "0",
            "--trust-baseline-summary",
            str(baseline),
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "decision=FAIL" in result.stdout
    manifest = json.loads((out_dir / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert manifest["decision"] == "FAIL"
    trust = manifest.get("trust_regression") or {}
    assert trust.get("enabled") is True
    assert str(trust.get("decision") or "") == "FAIL"
    step_names = [str(item.get("name") or "") for item in manifest.get("steps") or []]
    assert "trust_regression" in step_names
