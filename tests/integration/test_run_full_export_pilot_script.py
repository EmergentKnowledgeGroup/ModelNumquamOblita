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


def test_run_full_export_pilot_script_skip_import(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "live"
    _build_store(sqlite_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_full_export_pilot.py",
            "--skip-import",
            "--store",
            str(sqlite_path),
            "--run-dir",
            str(out_dir),
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
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "decision=PASS" in result.stdout

    manifest_path = out_dir / "live_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["decision"] == "PASS"
    assert manifest["skip_import"] is True
    assert {step["name"] for step in manifest["steps"]} == {"pilot_acceptance", "release_gate"}
    release_gate = manifest.get("release_gate") or {}
    assert str(release_gate.get("decision") or "") == "PASS"
    release_gate_report_json = str(release_gate.get("report_json") or "").strip()
    release_gate_report_md = str(release_gate.get("report_md") or "").strip()
    assert release_gate_report_json
    assert release_gate_report_md
    assert Path(release_gate_report_json).exists()
    assert Path(release_gate_report_md).exists()
    runtime_launch = manifest.get("runtime_launch")
    assert isinstance(runtime_launch, dict)
    assert isinstance(runtime_launch.get("command"), list)
    assert "--from-live-manifest" in runtime_launch.get("command")
    assert "run_live_runtime.ps1" in str(runtime_launch.get("powershell") or "")
    assert "run_live_runtime.bat" in str(runtime_launch.get("batch") or "")

    pilot_manifest = out_dir / "pilot" / "pilot_manifest.json"
    assert pilot_manifest.exists()
    logs_dir = out_dir / "logs"
    assert (logs_dir / "02_pilot.log").exists()
    assert (logs_dir / "03_release_gate.log").exists()


def test_run_full_export_pilot_forwards_latency_overrides_to_pilot_step(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "live"
    _build_store(sqlite_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_full_export_pilot.py",
            "--skip-import",
            "--store",
            str(sqlite_path),
            "--run-dir",
            str(out_dir),
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
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    manifest = json.loads((out_dir / "live_manifest.json").read_text(encoding="utf-8"))
    pilot_step = next(item for item in manifest["steps"] if item["name"] == "pilot_acceptance")
    pilot_cmd = [str(part) for part in pilot_step["command"]]
    assert "--max-eval-p95-latency-ms" in pilot_cmd
    assert "--max-load-p95-latency-ms" in pilot_cmd
    assert "25000.0" in pilot_cmd
    assert "26000.0" in pilot_cmd


def test_run_full_export_pilot_script_requires_input_when_import_enabled(tmp_path: Path) -> None:
    out_dir = tmp_path / "live"
    missing_input = tmp_path / "missing_conversations.json"
    result = subprocess.run(
        [
            sys.executable,
            "tools/run_full_export_pilot.py",
            "--input",
            str(missing_input),
            "--run-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    assert "error=input path not found" in result.stdout


def test_run_full_export_pilot_script_fails_when_required_trust_baseline_missing(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    out_dir = tmp_path / "live_fail"
    _build_store(sqlite_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_full_export_pilot.py",
            "--skip-import",
            "--store",
            str(sqlite_path),
            "--run-dir",
            str(out_dir),
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
            "--require-trust-regression-gate",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2

    manifest_path = out_dir / "live_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["decision"] == "FAIL"
    assert "pilot_acceptance" in [str(name) for name in (manifest.get("failed_steps") or [])]
    assert {step["name"] for step in manifest["steps"]} == {"pilot_acceptance", "release_gate"}
    assert (out_dir / "logs" / "03_release_gate.log").exists()
