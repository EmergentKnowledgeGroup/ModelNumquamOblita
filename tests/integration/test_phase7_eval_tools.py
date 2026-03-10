from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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


def _build_empty_store(path: Path) -> None:
    store = SqliteAtomStore(path)
    store.close()


def test_run_truthset_eval_script_plan_and_safe(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)

    plan = subprocess.run(
        [
            sys.executable,
            "tools/run_truthset_eval.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "120",
            "--scan-budget",
            "20",
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "effective_cases=6" in plan.stdout

    out_dir = tmp_path / "eval_out"
    safe = subprocess.run(
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
            "--write-partial-artifacts",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "chunking enabled" in safe.stdout
    assert "summary_json=" in safe.stdout
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["cases"] == 6
    assert "decision_accuracy" in summary
    assert "routine_over_recall_rate" in summary
    assert "episode_hit_rate" in summary
    assert "episode_false_recall_rate" in summary
    assert "memory_mode_case_counts" in summary
    assert (out_dir / "records.partial.json").exists()
    assert (out_dir / "progress.partial.json").exists()
    case_counts = json.loads((out_dir / "truthset.case_counts.json").read_text(encoding="utf-8"))
    assert "unsupported_probe" in case_counts
    assert "unsupported_pressure" in case_counts
    assert "routine_chat" in case_counts


def test_run_truthset_eval_script_fails_closed_on_empty_store(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "empty.sqlite3"
    _build_empty_store(sqlite_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_truthset_eval.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "error=no eval cases generated or loaded" in result.stdout

    allowed = subprocess.run(
        [
            sys.executable,
            "tools/run_truthset_eval.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
            "--allow-empty",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert allowed.returncode == 0
    assert "warning=no eval cases generated or loaded" in allowed.stdout


def test_run_truthset_eval_script_auto_chunking_when_threshold_is_forced(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "eval_auto_chunk"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_truthset_eval.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "NO_AUTO_CHUNK_ATOM_THRESHOLD": "1"},
    )
    assert "auto_chunking enabled" in result.stdout
    assert "chunking enabled" in result.stdout
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["cases"] == 6


def test_run_truthset_eval_disables_mismatched_default_episode_cards(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "eval_mismatch_cards"
    episodes_dir = REPO_ROOT / "runtime" / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    mismatch = episodes_dir / f"episode_cards_test_mismatch_{int(time.time() * 1000)}.json"
    mismatch.write_text(
        json.dumps(
            {
                "schema": "numquamoblita.episode_cards.v1",
                "source_store": str(tmp_path / "other.sqlite3"),
                "memories_path": str(tmp_path / "other.sqlite3"),
                "cards": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    future = time.time() + 60.0
    os.utime(mismatch, (future, future))
    try:
        result = subprocess.run(
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
                str(out_dir),
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        mismatch.unlink(missing_ok=True)

    assert "warning=episode_cards store mismatch, disabling episodes:" in result.stdout
    assert "episode_cards_enabled=False" in result.stdout


def test_run_runtime_load_script(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "load_out"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_runtime_load.py",
            "--memories",
            str(sqlite_path),
            "--requested-turns",
            "5",
            "--scan-budget",
            "20000",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "summary_json=" in result.stdout
    summary = json.loads((out_dir / "load_summary.json").read_text(encoding="utf-8"))
    assert summary["turns"] == 5
    assert "latency_p95_ms" in summary


def test_run_responder_eval_emits_dual_verdict_gate_and_readout(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "responder_eval"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_responder_eval.py",
            "--memories",
            str(sqlite_path),
            "--requested-cases",
            "6",
            "--scan-budget",
            "20000",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "acceptance_gate_json=" in result.stdout
    assert "human_readout_md=" in result.stdout
    gate = json.loads((out_dir / "acceptance_gate.json").read_text(encoding="utf-8"))
    assert str(gate.get("safety_verdict") or "").strip() in {"PASS", "FAIL"}
    assert str(gate.get("human_quality_verdict") or "").strip() in {"PASS", "FAIL"}
    assert str(gate.get("decision") or "").strip() in {"PASS", "FAIL"}
    readout = (out_dir / "human_readout.md")
    assert readout.exists()
    readout_text = readout.read_text(encoding="utf-8")
    assert "## Retrieval Diagnostics Summary" in readout_text

    records = json.loads((out_dir / "records.json").read_text(encoding="utf-8"))
    assert isinstance(records, list) and records
    retrieval_payloads = [
        dict(dict(row.get("retrieval") or {}).get("retrieval_diagnostics") or {})
        for row in records
        if isinstance(row, dict)
    ]
    assert any(isinstance(payload.get("selected"), list) for payload in retrieval_payloads)
    assert all(
        isinstance(payload, dict) and "raw_text_included" in payload and payload["raw_text_included"] is False
        for payload in retrieval_payloads
    )


def test_run_eval_drift_script_fails_on_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(
        json.dumps(
            {
                "decision_accuracy": 0.95,
                "citation_hit_rate": 0.99,
                "retrieval_hit_rate": 0.95,
                "abstain_precision": 0.9,
                "false_memory_rate": 0.01,
                "p95_latency_ms": 1000.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps(
            {
                "decision_accuracy": 0.90,
                "citation_hit_rate": 0.95,
                "retrieval_hit_rate": 0.91,
                "abstain_precision": 0.85,
                "false_memory_rate": 0.04,
                "p95_latency_ms": 1500.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "drift"
    result = subprocess.run(
        [
            sys.executable,
            "tools/run_eval_drift.py",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--out-dir",
            str(out_dir),
            "--fail-on-regression",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads((out_dir / "drift_report.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "FAIL"
    assert payload["regressions"]


def test_run_phase7_signoff_script(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "signoff"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_phase7_signoff.py",
            "--memories",
            str(sqlite_path),
            "--eval-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--profile",
            "safe",
            "--max-weak-question-cases",
            "3",
            "--out-dir",
            str(out_dir),
            "--fail-on-gate",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decision=PASS" in result.stdout
    assert "safety_verdict=PASS" in result.stdout
    assert "human_quality_verdict=PASS" in result.stdout
    manifest = json.loads((out_dir / "signoff_manifest.json").read_text(encoding="utf-8"))
    assert manifest["decision"] == "PASS"
    assert manifest["safety_verdict"] == "PASS"
    assert manifest["human_quality_verdict"] == "PASS"
    assert "brief" in manifest
    assert Path(manifest["brief"]["markdown"]).exists()
    assert Path(manifest["brief"]["text"]).exists()
    assert (out_dir / "eval" / "summary.json").exists()
    assert Path(manifest["judged_eval"]["acceptance_gate_json"]).exists()
    assert Path(manifest["judged_eval"]["human_readout_md"]).exists()
    assert Path(manifest["judged_eval"]["question_quality_summary_json"]).exists()
    assert (out_dir / "load" / "load_summary.json").exists()
    continuity_summary_path = out_dir / "continuity" / "continuity_summary.json"
    assert continuity_summary_path.exists()
    continuity_summary = json.loads(continuity_summary_path.read_text(encoding="utf-8"))
    assert "fixture_case_counts" in continuity_summary
    assert int(continuity_summary.get("checks") or 0) >= 1


def test_run_phase7_signoff_honors_truthset_length(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "signoff_truthset"
    truthset = tmp_path / "truthset.jsonl"
    truthset.write_text(
        json.dumps(
            {
                "case_id": "case_001",
                "case_type": "supported_recall",
                "query": "What do you remember about: You prefer tea at midnight.?",
                "retrieval_query": "You prefer tea at midnight.",
                "expected_decision": "PASS",
                "expected_citations": ["conv_1#c1_msg"],
                "expected_atom_ids": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_phase7_signoff.py",
            "--memories",
            str(sqlite_path),
            "--truthset",
            str(truthset),
            "--eval-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--profile",
            "safe",
            "--min-eval-cases",
            "1",
            "--min-supported-cases",
            "1",
            "--min-unsupported-cases",
            "0",
            "--min-retrieval-hit-rate",
            "0",
            "--min-abstain-precision",
            "0",
            "--max-weak-question-cases",
            "1",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decision=PASS" in result.stdout
    summary = json.loads((out_dir / "eval" / "summary.json").read_text(encoding="utf-8"))
    assert summary["requested_cases"] == 1
    assert summary["cases"] == 1


def test_run_phase7_signoff_can_skip_continuity_harness(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "signoff_skip_continuity"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_phase7_signoff.py",
            "--memories",
            str(sqlite_path),
            "--eval-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--profile",
            "safe",
            "--skip-continuity-harness",
            "--max-weak-question-cases",
            "3",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decision=PASS" in result.stdout
    assert not (out_dir / "continuity" / "continuity_summary.json").exists()


def test_run_phase7_signoff_requires_trust_regression_baseline(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "atoms.sqlite3"
    _build_store(sqlite_path)
    out_dir = tmp_path / "signoff_require_trust"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_phase7_signoff.py",
            "--memories",
            str(sqlite_path),
            "--eval-cases",
            "6",
            "--load-turns",
            "4",
            "--scan-budget",
            "20000",
            "--profile",
            "safe",
            "--require-trust-regression-gate",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "error=trust regression gate required but --drift-baseline is missing" in result.stdout
