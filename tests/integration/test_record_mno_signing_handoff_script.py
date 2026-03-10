from __future__ import annotations

import hashlib
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
        key_clean = key.strip()
        if not key_clean:
            continue
        out[key_clean] = value.strip()
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seed_manifest(path: Path, artifact: Path, *, candidate_path: str | None = None, include_hash: bool = True) -> None:
    payload = {
        "schema": "numquamoblita.release.candidate.v1",
        "signing_owner": "ProfessahX/Xander",
        "signing_handoff": {
            "artifact_hash_sha256": _sha256(artifact) if include_hash else "",
            "candidate_path": str(candidate_path if candidate_path is not None else artifact),
            "signing_status": "pending",
            "signer_identity": "",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_record_mno_signing_handoff_signed_pass(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.bin"
    artifact.write_bytes(b"candidate")
    manifest = tmp_path / "manifest.json"
    _seed_manifest(manifest, artifact)

    result = subprocess.run(
        [
            sys.executable,
            "tools/record_mno_signing_handoff.py",
            "--manifest",
            str(manifest),
            "--status",
            "signed",
            "--signer-identity",
            "ProfessahX",
            "--signature-reference",
            "ticket-123",
            "--certificate-fingerprint",
            "ABC123",
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
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    handoff = payload.get("signing_handoff") or {}
    assert str(handoff.get("signing_status") or "") == "signed"
    assert str(handoff.get("signer_identity") or "") == "ProfessahX"
    assert str(handoff.get("signature_reference") or "") == "ticket-123"
    assert str(handoff.get("certificate_fingerprint") or "") == "ABC123"
    assert bool(handoff.get("integrity_match")) is True


def test_record_mno_signing_handoff_hash_mismatch_fails(tmp_path: Path) -> None:
    original = tmp_path / "original.bin"
    original.write_bytes(b"original")
    signed = tmp_path / "signed.bin"
    signed.write_bytes(b"different")
    manifest = tmp_path / "manifest.json"
    _seed_manifest(manifest, original)

    result = subprocess.run(
        [
            sys.executable,
            "tools/record_mno_signing_handoff.py",
            "--manifest",
            str(manifest),
            "--status",
            "signed",
            "--signer-identity",
            "ProfessahX",
            "--signed-artifact",
            str(signed),
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
    assert "artifact_hash_mismatch" in str(kv.get("reasons") or "")


def test_record_mno_signing_handoff_missing_signer_fails(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.bin"
    artifact.write_bytes(b"candidate")
    manifest = tmp_path / "manifest.json"
    _seed_manifest(manifest, artifact)

    result = subprocess.run(
        [
            sys.executable,
            "tools/record_mno_signing_handoff.py",
            "--manifest",
            str(manifest),
            "--status",
            "signed",
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
    assert "missing_signer_identity" in str(kv.get("reasons") or "")


def test_record_mno_signing_handoff_missing_original_hash_fails(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.bin"
    artifact.write_bytes(b"candidate")
    manifest = tmp_path / "manifest.json"
    _seed_manifest(manifest, artifact, include_hash=False)

    result = subprocess.run(
        [
            sys.executable,
            "tools/record_mno_signing_handoff.py",
            "--manifest",
            str(manifest),
            "--status",
            "signed",
            "--signer-identity",
            "ProfessahX",
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
    assert "missing_original_artifact_hash" in str(kv.get("reasons") or "")


def test_record_mno_signing_handoff_resolves_relative_candidate_path(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.bin"
    artifact.write_bytes(b"candidate")
    manifest = tmp_path / "manifest.json"
    _seed_manifest(manifest, artifact, candidate_path="candidate.bin")

    result = subprocess.run(
        [
            sys.executable,
            "tools/record_mno_signing_handoff.py",
            "--manifest",
            str(manifest),
            "--status",
            "signed",
            "--signer-identity",
            "ProfessahX",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    handoff = payload.get("signing_handoff") or {}
    assert str(handoff.get("signed_artifact_path") or "") == str(artifact.resolve())
    assert bool(handoff.get("integrity_match")) is True
