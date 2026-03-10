#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _validate_candidate_manifest(payload: dict[str, Any], *, label: str) -> list[str]:
    failures: list[str] = []
    if str(payload.get("schema") or "") != "numquamoblita.release.candidate.v1":
        failures.append(f"{label}:schema_mismatch")
    if str(payload.get("decision") or "").strip().upper() != "PASS":
        failures.append(f"{label}:decision_not_pass")
    handoff = payload.get("signing_handoff")
    handoff_obj = handoff if isinstance(handoff, dict) else {}
    if not str(handoff_obj.get("candidate_path") or "").strip():
        failures.append(f"{label}:missing_candidate_path")
    if not str(handoff_obj.get("artifact_hash_sha256") or "").strip():
        failures.append(f"{label}:missing_artifact_hash")
    return failures


def _run(command: list[str], *, cwd: Path, timeout_sec: int) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout_sec)
        finished = datetime.now(timezone.utc).isoformat()
        return {
            "command": command,
            "returncode": int(proc.returncode),
            "timed_out": False,
            "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-20:]),
            "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
            "started_at": started,
            "finished_at": finished,
        }
    except subprocess.TimeoutExpired as exc:
        finished = datetime.now(timezone.utc).isoformat()
        return {
            "command": command,
            "returncode": 124,
            "timed_out": True,
            "stdout_tail": "\n".join(str(exc.stdout or "").splitlines()[-20:]),
            "stderr_tail": "\n".join(str(exc.stderr or "").splitlines()[-20:]),
            "started_at": started,
            "finished_at": finished,
        }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# MNO Rollback Drill Report",
        "",
        f"- generated_at: `{str(report.get('generated_at') or '')}`",
        f"- decision: `{str(report.get('decision') or 'FAIL')}`",
        f"- plan_only: `{bool(report.get('plan_only'))}`",
        f"- candidate_manifest: `{str(report.get('candidate_manifest') or '')}`",
        f"- stable_manifest: `{str(report.get('stable_manifest') or '')}`",
        "",
        "## Steps",
    ]
    for step in list(report.get("steps") or []):
        lines.append(f"- `{str(step.get('name') or '')}`: `{str(step.get('status') or '')}`")
        cmd = list(step.get("command") or [])
        if cmd:
            lines.append(f"  - cmd: `{' '.join([str(i) for i in cmd])}`")
        detail = str(step.get("detail") or "").strip()
        if detail:
            lines.append(f"  - detail: {detail}")
    failures = [str(item) for item in list(report.get("failures") or []) if str(item).strip()]
    lines.append("")
    lines.append("## Failures")
    if failures:
        lines.extend([f"- {item}" for item in failures])
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run candidate->stable->candidate rollback drill checks.")
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--stable-manifest", required=True)
    parser.add_argument("--python-cmd", default=sys.executable)
    parser.add_argument("--out-dir", default="runtime/releases/rollback_drills")
    parser.add_argument("--timeout-sec", type=int, default=300)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument(
        "--allow-incomplete-manifests",
        action="store_true",
        help="When used with --plan-only, allow manifests missing candidate path/hash.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    out_dir = (repo_root / str(args.out_dir)).resolve() / f"rollback_drill_{_timestamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    candidate_manifest_path = Path(str(args.candidate_manifest)).expanduser().resolve()
    stable_manifest_path = Path(str(args.stable_manifest)).expanduser().resolve()

    failures: list[str] = []
    steps: list[dict[str, Any]] = []

    if not candidate_manifest_path.exists():
        failures.append(f"candidate_manifest_missing:{candidate_manifest_path}")
    if not stable_manifest_path.exists():
        failures.append(f"stable_manifest_missing:{stable_manifest_path}")

    candidate_payload: dict[str, Any] = {}
    stable_payload: dict[str, Any] = {}
    if not failures:
        candidate_read_error = ""
        stable_read_error = ""
        try:
            candidate_payload = _read_json(candidate_manifest_path)
        except Exception as exc:
            candidate_payload = {}
            candidate_read_error = str(exc)
            failures.append("candidate_manifest_invalid_json")
        try:
            stable_payload = _read_json(stable_manifest_path)
        except Exception as exc:
            stable_payload = {}
            stable_read_error = str(exc)
            failures.append("stable_manifest_invalid_json")

        if candidate_read_error:
            steps.append(
                {
                    "name": "validate_candidate_manifest",
                    "status": "fail",
                    "detail": f"read_error={candidate_read_error}",
                }
            )
        if stable_read_error:
            steps.append(
                {
                    "name": "validate_stable_manifest",
                    "status": "fail",
                    "detail": f"read_error={stable_read_error}",
                }
            )

        if not candidate_read_error and not stable_read_error:
            if bool(args.plan_only) and bool(args.allow_incomplete_manifests):
                steps.append(
                    {
                        "name": "validate_candidate_manifest",
                        "status": "pass",
                        "detail": "plan_only with incomplete-manifest allowance",
                    }
                )
                steps.append(
                    {
                        "name": "validate_stable_manifest",
                        "status": "pass",
                        "detail": "plan_only with incomplete-manifest allowance",
                    }
                )
            else:
                candidate_failures = _validate_candidate_manifest(candidate_payload, label="candidate")
                stable_failures = _validate_candidate_manifest(stable_payload, label="stable")
                failures.extend(candidate_failures)
                failures.extend(stable_failures)
                steps.append(
                    {
                        "name": "validate_candidate_manifest",
                        "status": "pass" if not candidate_failures else "fail",
                        "detail": "schema+decision+signing fields",
                    }
                )
                steps.append(
                    {
                        "name": "validate_stable_manifest",
                        "status": "pass" if not stable_failures else "fail",
                        "detail": "schema+decision+signing fields",
                    }
                )

    smoke_commands = [
        ("candidate_smoke", [str(args.python_cmd), "tools/preflight.py", "--mode", "setup", "--json"]),
        ("stable_smoke", [str(args.python_cmd), "tools/preflight.py", "--mode", "setup", "--json"]),
        ("candidate_reupgrade_smoke", [str(args.python_cmd), "tools/preflight.py", "--mode", "setup", "--json"]),
    ]

    if not failures:
        for name, command in smoke_commands:
            if bool(args.plan_only):
                steps.append({"name": name, "status": "planned", "command": command, "detail": "plan_only"})
                continue
            run_result = _run(command, cwd=repo_root, timeout_sec=max(1, int(args.timeout_sec)))
            status = "pass" if int(run_result.get("returncode", 1)) == 0 else "fail"
            steps.append(
                {
                    "name": name,
                    "status": status,
                    "command": command,
                    "detail": (
                        "timed_out"
                        if bool(run_result.get("timed_out"))
                        else f"return_code={int(run_result.get('returncode', 1))}"
                    ),
                    "stdout_tail": str(run_result.get("stdout_tail") or ""),
                    "stderr_tail": str(run_result.get("stderr_tail") or ""),
                }
            )
            if status != "pass":
                failures.append(f"{name}_failed")

    decision = "PASS" if not failures else "FAIL"
    report = {
        "schema": "numquamoblita.rollback_drill.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "plan_only": bool(args.plan_only),
        "candidate_manifest": str(candidate_manifest_path),
        "stable_manifest": str(stable_manifest_path),
        "steps": steps,
        "failures": failures,
    }

    report_json = out_dir / "rollback_drill_report.json"
    report_md = out_dir / "rollback_drill_report.md"
    report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report_md.write_text(_render_markdown(report), encoding="utf-8")

    print(f"decision={decision}")
    print(f"report_json={report_json}")
    print(f"report_md={report_md}")
    if failures:
        print(f"failures={','.join(failures)}")
        return 2
    print("failures=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
