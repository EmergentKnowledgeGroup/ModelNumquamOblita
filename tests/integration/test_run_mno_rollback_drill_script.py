from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _write_manifest(path: Path, artifact: Path, *, include_hash: bool = True) -> None:
    payload = {
        "schema": "numquamoblita.release.candidate.v1",
        "decision": "PASS",
        "signing_handoff": {
            "candidate_path": str(artifact),
            "artifact_hash_sha256": _sha256(artifact) if include_hash else "",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_run_mno_rollback_drill_plan_only_pass(tmp_path: Path) -> None:
    candidate_artifact = tmp_path / "candidate.bin"
    stable_artifact = tmp_path / "stable.bin"
    candidate_artifact.write_bytes(b"candidate")
    stable_artifact.write_bytes(b"stable")

    candidate_manifest = tmp_path / "candidate_manifest.json"
    stable_manifest = tmp_path / "stable_manifest.json"
    _write_manifest(candidate_manifest, candidate_artifact)
    _write_manifest(stable_manifest, stable_artifact)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_mno_rollback_drill.py",
            "--candidate-manifest",
            str(candidate_manifest),
            "--stable-manifest",
            str(stable_manifest),
            "--plan-only",
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    kv = _parse_kv(result.stdout)
    assert str(kv.get("decision") or "") == "PASS"
    report_json = Path(str(kv.get("report_json") or ""))
    assert report_json.exists()
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert str(payload.get("schema") or "") == "numquamoblita.rollback_drill.v1"


def test_run_mno_rollback_drill_executes_smoke_commands(tmp_path: Path) -> None:
    candidate_artifact = tmp_path / "candidate.bin"
    stable_artifact = tmp_path / "stable.bin"
    candidate_artifact.write_bytes(b"candidate")
    stable_artifact.write_bytes(b"stable")

    candidate_manifest = tmp_path / "candidate_manifest.json"
    stable_manifest = tmp_path / "stable_manifest.json"
    _write_manifest(candidate_manifest, candidate_artifact)
    _write_manifest(stable_manifest, stable_artifact)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_mno_rollback_drill.py",
            "--candidate-manifest",
            str(candidate_manifest),
            "--stable-manifest",
            str(stable_manifest),
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    kv = _parse_kv(result.stdout)
    report_json = Path(str(kv.get("report_json") or ""))
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    steps = list(payload.get("steps") or [])
    smoke = [item for item in steps if str(item.get("name") or "").endswith("smoke")]
    assert len(smoke) == 3
    assert all(str(item.get("status") or "") == "pass" for item in smoke)


def test_run_mno_rollback_drill_fails_when_manifest_missing_hash(tmp_path: Path) -> None:
    candidate_artifact = tmp_path / "candidate.bin"
    stable_artifact = tmp_path / "stable.bin"
    candidate_artifact.write_bytes(b"candidate")
    stable_artifact.write_bytes(b"stable")

    candidate_manifest = tmp_path / "candidate_manifest.json"
    stable_manifest = tmp_path / "stable_manifest.json"
    _write_manifest(candidate_manifest, candidate_artifact, include_hash=False)
    _write_manifest(stable_manifest, stable_artifact)

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_mno_rollback_drill.py",
            "--candidate-manifest",
            str(candidate_manifest),
            "--stable-manifest",
            str(stable_manifest),
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    kv = _parse_kv(result.stdout)
    assert str(kv.get("decision") or "") == "FAIL"
    assert "candidate:missing_artifact_hash" in str(kv.get("failures") or "")


def test_run_mno_rollback_drill_handles_invalid_json_manifest(tmp_path: Path) -> None:
    candidate_manifest = tmp_path / "candidate_manifest.json"
    stable_manifest = tmp_path / "stable_manifest.json"
    candidate_manifest.write_text("{bad json", encoding="utf-8")
    stable_manifest.write_text("{bad json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_mno_rollback_drill.py",
            "--candidate-manifest",
            str(candidate_manifest),
            "--stable-manifest",
            str(stable_manifest),
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    kv = _parse_kv(result.stdout)
    assert str(kv.get("decision") or "") == "FAIL"
    failures = str(kv.get("failures") or "")
    assert "candidate_manifest_invalid_json" in failures
    assert "stable_manifest_invalid_json" in failures
