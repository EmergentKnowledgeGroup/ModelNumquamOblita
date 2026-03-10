from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_kv(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in str(stdout or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned = key.strip()
        if not cleaned:
            continue
        out[cleaned] = value.strip()
    return out


def test_build_mno_release_candidate_dry_run(tmp_path: Path) -> None:
    out_root = tmp_path / "candidates"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_mno_release_candidate.py",
            "--mode",
            "dry-run",
            "--out-root",
            str(out_root),
            "--signing-owner",
            "ProfessahX/Xander",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    kv = _parse_kv(result.stdout)
    assert str(kv.get("decision") or "") == "PASS"
    assert str(kv.get("status") or "") == "dry_run"
    manifest_json_raw = str(kv.get("manifest_json") or "").strip()
    assert manifest_json_raw
    manifest_json = Path(manifest_json_raw)
    assert manifest_json.exists()
    payload = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert str(payload.get("schema") or "") == "numquamoblita.release.candidate.v1"
    assert str(payload.get("signing_owner") or "") == "ProfessahX/Xander"
    assert int((payload.get("packaging") or {}).get("return_code", 1)) == 0
    assert str((payload.get("signing_handoff") or {}).get("signing_status") or "") == "pending"


def test_build_mno_release_candidate_handles_missing_python_cmd(tmp_path: Path) -> None:
    out_root = tmp_path / "candidates"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_mno_release_candidate.py",
            "--mode",
            "dry-run",
            "--python-cmd",
            "/definitely/missing/python",
            "--out-root",
            str(out_root),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 2
    kv = _parse_kv(result.stdout)
    assert str(kv.get("decision") or "") == "FAIL"
    manifest_json_raw = str(kv.get("manifest_json") or "").strip()
    assert manifest_json_raw
    manifest_json = Path(manifest_json_raw)
    assert manifest_json.exists()
    payload = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert str(payload.get("status") or "") == "failed"
    assert int((payload.get("packaging") or {}).get("return_code") or 0) == 127
