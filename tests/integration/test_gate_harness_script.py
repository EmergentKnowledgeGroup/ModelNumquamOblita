from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_run_gate_harness_script_generates_reports(tmp_path: Path) -> None:
    records_path = tmp_path / "records.json"
    failure_path = tmp_path / "failure.json"
    counts_path = tmp_path / "counts.json"
    out_dir = tmp_path / "out"

    records = [
        {
            "query_id": f"q{i}",
            "query_class": "factual",
            "memory_age_bucket": "recent",
            "memory_claims": 1,
            "unsupported_claims": 0,
            "recall_hit": True,
            "temporal_correct": True,
            "high_severity_false_memory": False,
            "verifier_blocked_unsupported": True,
            "conflict_prompt": False,
            "uncertainty_emitted": True,
            "abstain_expected": False,
            "abstain_emitted": False,
            "latency_ms": 500,
            "unsupported_on_gold_trace": False,
        }
        for i in range(700)
    ]
    failure = {
        "FC-04": True,
        "FC-08": True,
        "FC-10": True,
        "FC-20": True,
        "FC-21": True,
        "FC-22": True,
        "FC-23": True,
        "FC-25": True,
    }
    counts = {"gold": 500, "contradiction": 200, "adversarial": 180, "drift": 120, "recognition": 140}
    records_path.write_text(json.dumps(records), encoding="utf-8")
    failure_path.write_text(json.dumps(failure), encoding="utf-8")
    counts_path.write_text(json.dumps(counts), encoding="utf-8")

    cmd = [
        sys.executable,
        "tools/run_gate_harness.py",
        "--records",
        str(records_path),
        "--failure-results",
        str(failure_path),
        "--dataset-counts",
        str(counts_path),
        "--out-dir",
        str(out_dir),
    ]
    repo_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(cmd, cwd=repo_root, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    reports = sorted(out_dir.glob("gate_report_*.json"))
    assert reports
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["decision"] == "PASS"
