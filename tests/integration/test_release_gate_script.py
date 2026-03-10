from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_signoff_manifest(path: Path, *, decision: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"decision": decision}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_pilot_manifest(path: Path, *, signoff_dir: Path, pilot_decision: str, trust_enabled: bool, trust_decision: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "decision": pilot_decision,
        "artifacts": {"signoff_dir": str(signoff_dir)},
        "trust_regression": {"enabled": trust_enabled, "decision": trust_decision},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_run_release_gate_script_passes_with_trust_regression(tmp_path: Path) -> None:
    signoff_dir = tmp_path / "signoff"
    _write_signoff_manifest(signoff_dir / "signoff_manifest.json", decision="PASS")
    pilot_manifest = _write_pilot_manifest(
        tmp_path / "pilot_manifest.json",
        signoff_dir=signoff_dir,
        pilot_decision="PASS",
        trust_enabled=True,
        trust_decision="PASS",
    )
    out_dir = tmp_path / "release_gate"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_release_gate.py",
            "--pilot-manifest",
            str(pilot_manifest),
            "--require-trust-regression",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "decision=PASS" in result.stdout
    payload = json.loads((out_dir / "release_gate_report.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "PASS"


def test_run_release_gate_script_fails_when_trust_regression_missing(tmp_path: Path) -> None:
    signoff_dir = tmp_path / "signoff"
    _write_signoff_manifest(signoff_dir / "signoff_manifest.json", decision="PASS")
    pilot_manifest = _write_pilot_manifest(
        tmp_path / "pilot_manifest.json",
        signoff_dir=signoff_dir,
        pilot_decision="PASS",
        trust_enabled=False,
        trust_decision="SKIP",
    )
    out_dir = tmp_path / "release_gate"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_release_gate.py",
            "--pilot-manifest",
            str(pilot_manifest),
            "--require-trust-regression",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "decision=FAIL" in result.stdout
    payload = json.loads((out_dir / "release_gate_report.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "FAIL"
    assert "trust_regression_not_enabled" in payload["reasons"]
