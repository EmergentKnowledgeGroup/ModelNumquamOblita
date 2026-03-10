#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_export_path() -> Path:
    candidates = [
        REPO_ROOT / "conversations.json",
        REPO_ROOT.parent / "User Online Activity" / "conversations" / "conversations.json",
        REPO_ROOT.parent / "conversations.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _parse_kv(lines: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in lines:
        text = str(line).strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key_norm = key.strip().lower()
        if key_norm and value.strip():
            parsed[key_norm] = value.strip()
    return parsed


@dataclass(slots=True)
class StepResult:
    name: str
    status: str
    returncode: int
    started_at: str
    finished_at: str
    duration_s: float
    command: list[str]
    log_file: str
    outputs: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "command": self.command,
            "log_file": self.log_file,
            "outputs": self.outputs,
        }


def _run_step(name: str, command: list[str], log_file: Path) -> StepResult:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    started_dt = datetime.now(timezone.utc)
    started_at = started_dt.isoformat()
    streamed: list[str] = []
    with log_file.open("w", encoding="utf-8") as fp:
        fp.write(f"[{started_at}] step={name} start\n")
        fp.write(f"[{started_at}] command={' '.join(command)}\n")
        fp.flush()
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            clean = line.rstrip("\n")
            streamed.append(clean)
            stamped = f"[{datetime.now(timezone.utc).isoformat()}] {clean}"
            print(stamped)
            fp.write(stamped + "\n")
            fp.flush()
        returncode = int(proc.wait())
    finished_dt = datetime.now(timezone.utc)
    finished_at = finished_dt.isoformat()
    duration_s = max(0.0, (finished_dt - started_dt).total_seconds())
    status = "PASS" if returncode == 0 else "FAIL"
    with log_file.open("a", encoding="utf-8") as fp:
        fp.write(f"[{finished_at}] step={name} status={status} rc={returncode}\n")
    return StepResult(
        name=name,
        status=status,
        returncode=returncode,
        started_at=started_at,
        finished_at=finished_at,
        duration_s=duration_s,
        command=command,
        log_file=str(log_file),
        outputs=_parse_kv(streamed),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run full pilot workflow from raw export: import -> pilot acceptance."
    )
    parser.add_argument("--input", default=str(_default_export_path()), help="Path to conversations export JSON")
    parser.add_argument(
        "--store",
        default=str(REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3"),
        help="Path to sqlite memory store",
    )
    parser.add_argument("--run-dir", default="", help="Root directory for this live run")
    parser.add_argument("--skip-import", action="store_true", help="Skip import and run pilot on existing store")
    parser.add_argument("--requested-cases", type=int, default=12)
    parser.add_argument("--load-turns", type=int, default=12)
    parser.add_argument("--scan-budget", type=int, default=600000)
    parser.add_argument(
        "--fixture-mode",
        choices=["basic", "trust-v2", "trust-v3"],
        default="trust-v3",
        help="Fixture family generation mode for auto-generated eval truthset.",
    )
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--batch-pause-ms", type=int, default=100)
    parser.add_argument("--profile", choices=["safe", "strict"], default="safe")
    parser.add_argument("--truthset", default="", help="Optional reviewed truthset jsonl path")
    parser.add_argument("--trust-baseline-summary", default="", help="Optional baseline eval summary.json for trust drift gate.")
    parser.add_argument("--require-trust-regression-gate", action="store_true")
    parser.add_argument("--require-reviewed-truthset", action="store_true")
    parser.add_argument("--truthset-min-cases", type=int, default=6)
    parser.add_argument("--truthset-min-supported", type=int, default=3)
    parser.add_argument("--truthset-min-unsupported", type=int, default=2)
    parser.add_argument("--skip-truthset-quality-gate", action="store_true")
    parser.add_argument(
        "--max-eval-p95-latency-ms",
        type=float,
        default=None,
        help="Optional override for signoff eval p95 latency gate (ms).",
    )
    parser.add_argument(
        "--max-load-p95-latency-ms",
        type=float,
        default=None,
        help="Optional override for signoff load p95 latency gate (ms).",
    )
    parser.add_argument(
        "--max-weak-question-cases",
        type=int,
        default=0,
        help="Maximum allowed weak judged-eval truthset questions before signoff fails.",
    )
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--fail-on-gate", action="store_true")
    args = parser.parse_args()

    export_path = Path(args.input).expanduser().resolve()
    store_path = Path(args.store).expanduser().resolve()
    if not args.skip_import and not export_path.exists():
        print(f"error=input path not found: {export_path}")
        return 2

    run_dir = (
        Path(args.run_dir).expanduser().resolve()
        if args.run_dir
        else REPO_ROOT / "runtime" / "live_runs" / f"live_{_stamp()}"
    )
    logs_dir = run_dir / "logs"
    import_dir = run_dir / "import"
    pilot_dir = run_dir / "pilot"
    run_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    steps: list[StepResult] = []
    python_exe = sys.executable

    if not args.skip_import:
        import_cmd = [
            python_exe,
            str(REPO_ROOT / "tools" / "import_memories.py"),
            "--input",
            str(export_path),
            "--store",
            str(store_path),
            "--out-dir",
            str(import_dir),
        ]
        steps.append(_run_step("import_memories", import_cmd, logs_dir / "01_import.log"))
        if steps[-1].status != "PASS":
            decision = "FAIL"
            manifest = {
                "generated_at": _now_iso(),
                "decision": decision,
                "input_path": str(export_path),
                "skip_import": False,
                "store_path": str(store_path),
                "run_dir": str(run_dir),
                "steps": [item.to_dict() for item in steps],
                "failed_steps": [steps[-1].name],
            }
            manifest_path = run_dir / "live_manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            print(f"decision={decision}")
            print(f"manifest={manifest_path}")
            print(f"import_dir={import_dir}")
            return 2

    pilot_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_pilot_acceptance.py"),
        "--memories",
        str(store_path),
        "--out-dir",
        str(pilot_dir),
        "--requested-cases",
        str(int(args.requested_cases)),
        "--load-turns",
        str(int(args.load_turns)),
        "--scan-budget",
        str(int(args.scan_budget)),
        "--fixture-mode",
        str(args.fixture_mode),
        "--batch-size",
        str(int(args.batch_size)),
        "--batch-pause-ms",
        str(int(args.batch_pause_ms)),
        "--profile",
        str(args.profile),
        "--truthset-min-cases",
        str(int(args.truthset_min_cases)),
        "--truthset-min-supported",
        str(int(args.truthset_min_supported)),
        "--truthset-min-unsupported",
        str(int(args.truthset_min_unsupported)),
    ]
    if args.truthset:
        pilot_cmd.extend(["--truthset", str(Path(args.truthset).expanduser().resolve())])
    if args.trust_baseline_summary:
        pilot_cmd.extend(["--trust-baseline-summary", str(Path(args.trust_baseline_summary).expanduser().resolve())])
    if args.require_trust_regression_gate:
        pilot_cmd.append("--require-trust-regression-gate")
    if args.require_reviewed_truthset:
        pilot_cmd.append("--require-reviewed-truthset")
    if args.skip_truthset_quality_gate:
        pilot_cmd.append("--skip-truthset-quality-gate")
    if args.max_eval_p95_latency_ms is not None:
        pilot_cmd.extend(["--max-eval-p95-latency-ms", str(float(args.max_eval_p95_latency_ms))])
    if args.max_load_p95_latency_ms is not None:
        pilot_cmd.extend(["--max-load-p95-latency-ms", str(float(args.max_load_p95_latency_ms))])
    pilot_cmd.extend(["--max-weak-question-cases", str(max(0, int(args.max_weak_question_cases)))])
    if args.allow_empty:
        pilot_cmd.append("--allow-empty")
    if args.fail_on_gate:
        pilot_cmd.append("--fail-on-gate")
    steps.append(_run_step("pilot_acceptance", pilot_cmd, logs_dir / "02_pilot.log"))

    pilot_manifest_raw = str((steps[-1].outputs or {}).get("manifest") or "").strip()
    pilot_manifest_path = Path(pilot_manifest_raw).expanduser().resolve() if pilot_manifest_raw else (pilot_dir / "pilot_manifest.json")
    release_gate_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_release_gate.py"),
        "--pilot-manifest",
        str(pilot_manifest_path),
        "--out-dir",
        str(run_dir / "release_gate"),
    ]
    if args.require_trust_regression_gate:
        release_gate_cmd.append("--require-trust-regression")
    steps.append(_run_step("release_gate", release_gate_cmd, logs_dir / "03_release_gate.log"))

    failed = [item.name for item in steps if item.status != "PASS"]
    decision = "PASS" if not failed else "FAIL"
    manifest_path = run_dir / "live_manifest.json"
    release_outputs = steps[-1].outputs if steps and steps[-1].name == "release_gate" else {}
    release_gate_decision = str((release_outputs or {}).get("decision") or "").strip().upper()
    release_gate_report_json = str((release_outputs or {}).get("report_json") or "").strip()
    release_gate_report_md = str((release_outputs or {}).get("report_md") or "").strip()
    release_gate_reasons = str((release_outputs or {}).get("reasons") or "").strip()
    runtime_launch_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_live_runtime.py"),
        "--from-live-manifest",
        str(manifest_path),
    ]
    manifest = {
        "generated_at": _now_iso(),
        "decision": decision,
        "input_path": str(export_path) if not args.skip_import else "",
        "skip_import": bool(args.skip_import),
        "store_path": str(store_path),
        "run_dir": str(run_dir),
        "steps": [item.to_dict() for item in steps],
        "failed_steps": failed,
        "release_gate": {
            "decision": release_gate_decision,
            "report_json": release_gate_report_json,
            "report_md": release_gate_report_md,
            "reasons": release_gate_reasons,
            "required_trust_regression": bool(args.require_trust_regression_gate),
        },
        "runtime_launch": {
            "command": runtime_launch_cmd,
            "powershell": f"tools\\run_live_runtime.ps1 -FromLiveManifest \"{manifest_path}\"",
            "batch": f"tools\\run_live_runtime.bat -FromLiveManifest \"{manifest_path}\"",
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"decision={decision}")
    print(f"manifest={manifest_path}")
    print(f"pilot_dir={pilot_dir}")
    if release_gate_decision:
        print(f"release_gate_decision={release_gate_decision}")
    if release_gate_report_json:
        print(f"release_gate_report_json={release_gate_report_json}")
    if release_gate_report_md:
        print(f"release_gate_report_md={release_gate_report_md}")
    print(f"runtime_launch_cmd={' '.join(runtime_launch_cmd)}")
    if not args.skip_import:
        print(f"import_dir={import_dir}")
    return 0 if decision == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
