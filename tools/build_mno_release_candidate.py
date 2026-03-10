#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_markdown(manifest: dict[str, Any]) -> str:
    packaging = manifest.get("packaging") or {}
    return_code = packaging.get("return_code")
    return_code_text = "" if return_code is None else str(return_code)
    lines = [
        "# MNO Release Candidate",
        "",
        f"- decision: `{str(manifest.get('decision') or 'FAIL')}`",
        f"- status: `{str(manifest.get('status') or '')}`",
        f"- generated_at: `{str(manifest.get('generated_at') or '')}`",
        f"- signing_owner: `{str(manifest.get('signing_owner') or '')}`",
        "",
        "## Packaging",
        f"- command: `{str(packaging.get('command_text') or '')}`",
        f"- return_code: `{return_code_text}`",
        f"- expected_executable: `{str(packaging.get('expected_executable') or '')}`",
        "",
        "## Signing Handoff",
        f"- artifact_hash_sha256: `{str((manifest.get('signing_handoff') or {}).get('artifact_hash_sha256') or '')}`",
        f"- candidate_path: `{str((manifest.get('signing_handoff') or {}).get('candidate_path') or '')}`",
        f"- signing_status: `{str((manifest.get('signing_handoff') or {}).get('signing_status') or '')}`",
        f"- signer_identity: `{str((manifest.get('signing_handoff') or {}).get('signer_identity') or '')}`",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a pilot MNO release candidate manifest.")
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--python-cmd", default=sys.executable)
    parser.add_argument("--out-root", default="runtime/releases/candidates")
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--signing-owner", default="ProfessahX/Xander")
    args = parser.parse_args()

    repo_root = _repo_root()
    run_dir = (repo_root / str(args.out_root)).resolve() / f"mno_candidate_{_timestamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    packaging_out_root = run_dir / "packaging"
    command = [
        str(args.python_cmd),
        "tools/build_windows_single_exe.py",
        "--out-root",
        str(packaging_out_root),
    ]
    if str(args.mode) == "dry-run":
        command.append("--dry-run")
    else:
        command.append("--onefile")

    proc_return = 2
    proc_stdout = ""
    proc_stderr = ""
    timed_out = False
    try:
        proc = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(args.timeout_sec)),
        )
        proc_return = int(proc.returncode)
        proc_stdout = str(proc.stdout or "")
        proc_stderr = str(proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        proc_return = 124
        proc_stdout = str(exc.stdout or "")
        proc_stderr = str(exc.stderr or "")
    except FileNotFoundError as exc:
        proc_return = 127
        proc_stderr = str(exc)

    kv = _parse_kv(proc_stdout)
    expected_executable_raw = str(kv.get("expected_executable") or "").strip()
    expected_executable = Path(expected_executable_raw).expanduser() if expected_executable_raw else None

    artifact_hash = ""
    candidate_path = ""
    if expected_executable is not None and expected_executable.exists() and expected_executable.is_file():
        artifact_hash = _sha256(expected_executable)
        candidate_path = str(expected_executable)

    status = "built" if (proc_return == 0 and str(args.mode) == "build") else "dry_run"
    if proc_return != 0:
        status = "failed"

    manifest = {
        "schema": "numquamoblita.release.candidate.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "decision": "PASS" if proc_return == 0 else "FAIL",
        "mode": str(args.mode),
        "run_dir": str(run_dir),
        "signing_owner": str(args.signing_owner),
        "packaging": {
            "command": command,
            "command_text": " ".join(command),
            "return_code": proc_return,
            "timed_out": timed_out,
            "stdout_tail": "\n".join(proc_stdout.splitlines()[-30:]),
            "stderr_tail": "\n".join(proc_stderr.splitlines()[-30:]),
            "packaging_manifest_json": str(kv.get("packaging_manifest_json") or ""),
            "expected_executable": str(expected_executable) if expected_executable is not None else "",
            "build_command": str(kv.get("build_command") or ""),
        },
        "signing_handoff": {
            "artifact_hash_sha256": artifact_hash,
            "candidate_path": candidate_path,
            "signing_status": "pending",
            "signer_identity": "",
        },
    }

    manifest_json = run_dir / "mno_release_candidate_manifest.json"
    manifest_md = run_dir / "mno_release_candidate_manifest.md"
    manifest_json.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest_md.write_text(_render_markdown(manifest), encoding="utf-8")

    print(f"decision={manifest['decision']}")
    print(f"status={manifest['status']}")
    print(f"manifest_json={manifest_json}")
    print(f"manifest_md={manifest_md}")
    print(f"run_dir={run_dir}")
    print(f"signing_owner={args.signing_owner}")
    if proc_return != 0:
        print(f"error=packaging_failed_rc_{proc_return}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
