#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _default_memory_path() -> Path:
    sqlite_default = REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3"
    if sqlite_default.exists():
        return sqlite_default
    imports_dir = REPO_ROOT / ".runtime" / "imports"
    if imports_dir.exists():
        candidates = sorted(imports_dir.rglob("memories.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return sqlite_default


def _default_reviewed_truthset_path() -> Path | None:
    truthset_root = REPO_ROOT / "runtime" / "truthset"
    if not truthset_root.exists():
        return None
    candidates = sorted(
        truthset_root.rglob("truthset.reviewed.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _count_truthset_cases(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as fp:
        for raw in fp:
            if raw.strip():
                count += 1
    return count


def _summarize_truthset(path: Path) -> dict[str, int]:
    total_cases = 0
    supported_cases = 0
    unsupported_cases = 0
    unknown_cases = 0
    with path.open("r", encoding="utf-8", errors="replace") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            total_cases += 1
            try:
                row = json.loads(line)
            except Exception:
                unknown_cases += 1
                continue
            if not isinstance(row, dict):
                unknown_cases += 1
                continue
            case_type = str(row.get("case_type") or "").strip().lower()
            expected_decision = str(row.get("expected_decision") or "").strip().upper()
            if case_type == "supported_recall" or expected_decision == "PASS":
                supported_cases += 1
            elif case_type == "unsupported_trap" or expected_decision in {"ABSTAIN", "CLARIFY"}:
                unsupported_cases += 1
            else:
                unknown_cases += 1
    return {
        "total_cases": total_cases,
        "supported_cases": supported_cases,
        "unsupported_cases": unsupported_cases,
        "unknown_cases": unknown_cases,
    }


def _evaluate_truthset_quality(
    *,
    truthset_path: str,
    enabled: bool,
    min_cases: int,
    min_supported: int,
    min_unsupported: int,
) -> dict[str, Any]:
    thresholds = {
        "min_cases": int(max(0, min_cases)),
        "min_supported": int(max(0, min_supported)),
        "min_unsupported": int(max(0, min_unsupported)),
    }
    if not enabled or not truthset_path:
        return {
            "enabled": False,
            "decision": "SKIP",
            "reasons": [],
            "thresholds": thresholds,
            "counts": {
                "total_cases": 0,
                "supported_cases": 0,
                "unsupported_cases": 0,
                "unknown_cases": 0,
            },
        }
    counts = _summarize_truthset(Path(truthset_path))
    reasons: list[str] = []
    if int(counts["total_cases"]) < int(thresholds["min_cases"]):
        reasons.append("truthset_min_cases_not_met")
    if int(counts["supported_cases"]) < int(thresholds["min_supported"]):
        reasons.append("truthset_min_supported_not_met")
    if int(counts["unsupported_cases"]) < int(thresholds["min_unsupported"]):
        reasons.append("truthset_min_unsupported_not_met")
    decision = "PASS" if not reasons else "FAIL"
    return {
        "enabled": True,
        "decision": decision,
        "reasons": reasons,
        "thresholds": thresholds,
        "counts": counts,
    }


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
        }


def _run_step(name: str, command: list[str], log_file: Path) -> StepResult:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    started_dt = datetime.now(timezone.utc)
    started_at = started_dt.isoformat()
    with log_file.open("w", encoding="utf-8") as fp:
        fp.write(f"[{started_at}] step={name} start\n")
        fp.write(f"[{started_at}] command={' '.join(command)}\n")
        fp.flush()
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=fp,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    finished_dt = datetime.now(timezone.utc)
    finished_at = finished_dt.isoformat()
    duration_s = max(0.0, (finished_dt - started_dt).total_seconds())
    status = "PASS" if completed.returncode == 0 else "FAIL"
    with log_file.open("a", encoding="utf-8") as fp:
        fp.write(f"[{finished_at}] step={name} status={status} rc={completed.returncode}\n")
    return StepResult(
        name=name,
        status=status,
        returncode=int(completed.returncode),
        started_at=started_at,
        finished_at=finished_at,
        duration_s=duration_s,
        command=command,
        log_file=str(log_file),
    )


def _bundle_support(out_dir: Path, bundle_path: Path, manifest_path: Path) -> None:
    with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        if manifest_path.exists():
            archive.write(manifest_path, arcname="pilot_manifest.json")
        for rel_dir in ["logs", "eval", "load", "signoff"]:
            root = out_dir / rel_dir
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=str(path.relative_to(out_dir)))
        metadata = {
            "generated_at": _now_iso(),
            "repo_root": str(REPO_ROOT),
            "python": sys.version,
            "platform": platform.platform(),
            "pid": os.getpid(),
        }
        metadata_path = out_dir / "bundle_metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        archive.write(metadata_path, arcname="bundle_metadata.json")


def _load_signoff_decision(signoff_dir: Path) -> str:
    manifest_path = signoff_dir / "signoff_manifest.json"
    if not manifest_path.exists():
        return "UNKNOWN"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return "UNKNOWN"
    return str(payload.get("decision") or "UNKNOWN").strip().upper() or "UNKNOWN"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _build_pilot_report(
    *,
    overall: str,
    signoff_decision: str,
    manifest: dict[str, Any],
    bundle_path: Path,
    truthset_mode: str,
    truthset_path: str,
    truthset_case_count: int,
    truthset_quality: dict[str, Any],
    trust_regression: dict[str, Any],
) -> dict[str, Any]:
    signoff_dir_raw = str(manifest.get("artifacts", {}).get("signoff_dir") or "").strip()
    signoff_dir = Path(signoff_dir_raw) if signoff_dir_raw else None
    signoff_manifest = _read_json(signoff_dir / "signoff_manifest.json") if signoff_dir is not None else {}

    eval_summary_raw = str(signoff_manifest.get("eval", {}).get("summary_json") or "").strip()
    load_summary_raw = str(signoff_manifest.get("load", {}).get("summary_json") or "").strip()
    eval_summary_path = Path(eval_summary_raw) if eval_summary_raw else None
    load_summary_path = Path(load_summary_raw) if load_summary_raw else None
    eval_summary = _read_json(eval_summary_path) if eval_summary_path is not None else {}
    load_summary = _read_json(load_summary_path) if load_summary_path is not None else {}

    eval_cases = int(eval_summary.get("cases") or 0)
    supported_cases = int(eval_summary.get("supported_cases") or 0)
    unsupported_cases = int(eval_summary.get("unsupported_cases") or 0)
    load_turns = int(load_summary.get("turns") or 0)
    failed_turns = int(load_summary.get("failed_turns") or 0)
    attempted_turns = load_turns + failed_turns
    failed_turn_rate = (float(failed_turns) / float(attempted_turns)) if attempted_turns > 0 else 0.0

    recommendation = "Ready for pilot handoff."
    if overall != "PASS":
        recommendation = "Review failed step logs and signoff reasons before rerun."
    elif signoff_decision != "PASS":
        recommendation = "Investigate signoff decision details before pilot handoff."
    elif bool(trust_regression.get("enabled")) and str(trust_regression.get("decision") or "SKIP").upper() != "PASS":
        recommendation = "Trust regression gate failed. Review drift artifacts before pilot handoff."

    report: dict[str, Any] = {
        "generated_at": _now_iso(),
        "decision": overall,
        "signoff_decision": signoff_decision,
        "recommendation": recommendation,
        "truthset_mode": truthset_mode,
        "truthset_path": truthset_path,
        "truthset_case_count": int(truthset_case_count),
        "truthset_quality": truthset_quality,
        "trust_regression": trust_regression,
        "support_bundle": str(bundle_path),
        "failed_steps": list(manifest.get("failed_steps") or []),
        "signoff_reasons": list(signoff_manifest.get("reasons") or []),
        "metrics": {
            "eval": {
                "cases": eval_cases,
                "supported_cases": supported_cases,
                "unsupported_cases": unsupported_cases,
                "decision_accuracy": float(eval_summary.get("decision_accuracy") or 0.0),
                "citation_hit_rate": float(eval_summary.get("citation_hit_rate") or 0.0),
                "false_memory_rate": float(eval_summary.get("false_memory_rate") or 0.0),
                "latency_p95_ms": float(eval_summary.get("p95_latency_ms") or 0.0),
            },
            "load": {
                "turns": load_turns,
                "failed_turns": failed_turns,
                "failed_turn_rate": failed_turn_rate,
                "latency_p95_ms": float(load_summary.get("latency_p95_ms") or 0.0),
            },
        },
        "artifacts": {
            "signoff_manifest_json": str(signoff_dir / "signoff_manifest.json") if signoff_dir else "",
            "eval_summary_json": str(eval_summary_path) if eval_summary_path else "",
            "load_summary_json": str(load_summary_path) if load_summary_path else "",
        },
    }
    return report


def _render_pilot_report_md(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    eval_metrics = metrics.get("eval", {})
    load_metrics = metrics.get("load", {})
    lines = [
        "# Pilot Report",
        "",
        f"- decision: `{report.get('decision', 'UNKNOWN')}`",
        f"- signoff_decision: `{report.get('signoff_decision', 'UNKNOWN')}`",
        f"- recommendation: {report.get('recommendation', 'n/a')}",
        f"- truthset_mode: `{report.get('truthset_mode', 'generated')}`",
        f"- truthset_path: `{report.get('truthset_path', '') or '(auto generated)'}`",
        f"- truthset_case_count: `{int(report.get('truthset_case_count') or 0)}`",
        f"- truthset_quality: `{str((report.get('truthset_quality') or {}).get('decision') or 'SKIP')}`",
        f"- trust_regression: `{str((report.get('trust_regression') or {}).get('decision') or 'SKIP')}`",
        f"- support_bundle: `{report.get('support_bundle', '')}`",
        "",
        "## Eval metrics",
        f"- cases: `{int(eval_metrics.get('cases') or 0)}`",
        f"- supported_cases: `{int(eval_metrics.get('supported_cases') or 0)}`",
        f"- unsupported_cases: `{int(eval_metrics.get('unsupported_cases') or 0)}`",
        f"- decision_accuracy: `{float(eval_metrics.get('decision_accuracy') or 0.0):.4f}`",
        f"- citation_hit_rate: `{float(eval_metrics.get('citation_hit_rate') or 0.0):.4f}`",
        f"- false_memory_rate: `{float(eval_metrics.get('false_memory_rate') or 0.0):.4f}`",
        f"- latency_p95_ms: `{float(eval_metrics.get('latency_p95_ms') or 0.0):.2f}`",
        "",
        "## Load metrics",
        f"- turns: `{int(load_metrics.get('turns') or 0)}`",
        f"- failed_turns: `{int(load_metrics.get('failed_turns') or 0)}`",
        f"- failed_turn_rate: `{float(load_metrics.get('failed_turn_rate') or 0.0):.4f}`",
        f"- latency_p95_ms: `{float(load_metrics.get('latency_p95_ms') or 0.0):.2f}`",
        "",
        "## Reasons",
    ]
    reasons = list(report.get("signoff_reasons") or [])
    if reasons:
        lines.extend(f"- {item}" for item in reasons)
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def _render_pilot_report_txt(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    eval_metrics = metrics.get("eval", {})
    load_metrics = metrics.get("load", {})
    reasons = list(report.get("signoff_reasons") or [])
    reasons_text = ", ".join(reasons) if reasons else "none"
    return (
        f"Decision: {report.get('decision', 'UNKNOWN')}\n"
        f"Signoff decision: {report.get('signoff_decision', 'UNKNOWN')}\n"
        f"Recommendation: {report.get('recommendation', 'n/a')}\n"
        f"Truthset mode: {report.get('truthset_mode', 'generated')}\n"
        f"Truthset path: {report.get('truthset_path', '') or '(auto generated)'}\n"
        f"Truthset case count: {int(report.get('truthset_case_count') or 0)}\n"
        f"Truthset quality: {str((report.get('truthset_quality') or {}).get('decision') or 'SKIP')}\n"
        f"Trust regression: {str((report.get('trust_regression') or {}).get('decision') or 'SKIP')}\n"
        f"Eval cases: {int(eval_metrics.get('cases') or 0)}\n"
        f"Citation hit rate: {float(eval_metrics.get('citation_hit_rate') or 0.0):.4f}\n"
        f"False memory rate: {float(eval_metrics.get('false_memory_rate') or 0.0):.4f}\n"
        f"Load turns: {int(load_metrics.get('turns') or 0)}\n"
        f"Load failed turn rate: {float(load_metrics.get('failed_turn_rate') or 0.0):.4f}\n"
        f"Reasons: {reasons_text}\n"
        f"Support bundle: {report.get('support_bundle', '')}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pilot acceptance workflow with support bundle artifacts.")
    parser.add_argument("--memories", default=str(_default_memory_path()), help="Path to sqlite store or memories.json")
    parser.add_argument("--out-dir", default="", help="Output directory for pilot artifacts")
    parser.add_argument("--requested-cases", type=int, default=12, help="Requested eval cases")
    parser.add_argument("--load-turns", type=int, default=12, help="Requested load turns")
    parser.add_argument("--scan-budget", type=int, default=600000, help="Scan budget for eval/load")
    parser.add_argument(
        "--fixture-mode",
        choices=["basic", "trust-v2", "trust-v3"],
        default="trust-v3",
        help="Fixture family generation mode when auto-generating truthset.",
    )
    parser.add_argument("--batch-size", type=int, default=2, help="Eval chunk size for safe execution")
    parser.add_argument("--batch-pause-ms", type=int, default=100, help="Pause between eval batches")
    parser.add_argument("--profile", choices=["safe", "strict"], default="safe", help="Signoff profile")
    parser.add_argument("--truthset", default="", help="Optional reviewed truthset jsonl path.")
    parser.add_argument(
        "--require-reviewed-truthset",
        action="store_true",
        help="Fail if a reviewed truthset is not explicitly provided or auto-detected.",
    )
    parser.add_argument("--truthset-min-cases", type=int, default=6, help="Minimum reviewed truthset case count.")
    parser.add_argument("--truthset-min-supported", type=int, default=3, help="Minimum supported recall cases.")
    parser.add_argument("--truthset-min-unsupported", type=int, default=2, help="Minimum unsupported trap cases.")
    parser.add_argument(
        "--skip-truthset-quality-gate",
        action="store_true",
        help="Skip truthset composition quality gate checks.",
    )
    parser.add_argument("--trust-baseline-summary", default="", help="Optional baseline eval summary.json for trust drift checks.")
    parser.add_argument(
        "--require-trust-regression-gate",
        action="store_true",
        help="Fail early if --trust-baseline-summary is missing.",
    )
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
    parser.add_argument("--allow-empty", action="store_true", help="Allow zero-case eval exits")
    parser.add_argument("--fail-on-gate", action="store_true", help="Fail signoff command when gate decision is FAIL")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else REPO_ROOT / "runtime" / "pilot" / f"pilot_{_stamp()}"
    logs_dir = out_dir / "logs"
    eval_dir = out_dir / "eval"
    load_dir = out_dir / "load"
    signoff_dir = out_dir / "signoff"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    truthset_mode = "generated"
    truthset_path = ""
    truthset_case_count = 0
    if args.truthset:
        candidate = Path(args.truthset).expanduser().resolve()
        if not candidate.exists():
            print(f"error=truthset path not found: {candidate}")
            return 2
        truthset_path = str(candidate)
        truthset_mode = "explicit"
        truthset_case_count = _count_truthset_cases(candidate)
    else:
        auto_truthset = _default_reviewed_truthset_path()
        if auto_truthset is not None and auto_truthset.exists():
            truthset_path = str(auto_truthset.resolve())
            truthset_mode = "auto_reviewed"
            truthset_case_count = _count_truthset_cases(auto_truthset)

    if args.require_reviewed_truthset and not truthset_path:
        print("error=reviewed truthset required but none was provided or auto-detected")
        return 2

    trust_baseline_path = ""
    if args.trust_baseline_summary:
        baseline = Path(args.trust_baseline_summary).expanduser().resolve()
        if not baseline.exists():
            print(f"error=trust baseline summary not found: {baseline}")
            return 2
        trust_baseline_path = str(baseline)
    if args.require_trust_regression_gate and not trust_baseline_path:
        print("error=trust regression gate required but --trust-baseline-summary is missing")
        return 2

    truthset_quality_enabled = bool(truthset_path) and not bool(args.skip_truthset_quality_gate)
    truthset_quality = _evaluate_truthset_quality(
        truthset_path=truthset_path,
        enabled=truthset_quality_enabled,
        min_cases=int(args.truthset_min_cases),
        min_supported=int(args.truthset_min_supported),
        min_unsupported=int(args.truthset_min_unsupported),
    )

    python_exe = sys.executable
    steps: list[StepResult] = []

    plan_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_truthset_eval.py"),
        "--memories",
        str(memories_path),
        "--requested-cases",
        str(int(args.requested_cases)),
        "--scan-budget",
        str(int(args.scan_budget)),
        "--fixture-mode",
        str(args.fixture_mode),
        "--plan-only",
        "--log-file",
        str(logs_dir / "01_plan.log"),
    ]
    if truthset_path:
        plan_cmd.extend(["--truthset", truthset_path])
    if args.allow_empty:
        plan_cmd.append("--allow-empty")
    steps.append(_run_step("plan_only", plan_cmd, logs_dir / "01_plan.log"))

    eval_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_truthset_eval.py"),
        "--memories",
        str(memories_path),
        "--requested-cases",
        str(int(args.requested_cases)),
        "--scan-budget",
        str(int(args.scan_budget)),
        "--fixture-mode",
        str(args.fixture_mode),
        "--batch-size",
        str(int(args.batch_size)),
        "--batch-pause-ms",
        str(int(args.batch_pause_ms)),
        "--write-partial-artifacts",
        "--out-dir",
        str(eval_dir),
        "--log-file",
        str(logs_dir / "02_eval.log"),
    ]
    if truthset_path:
        eval_cmd.extend(["--truthset", truthset_path])
    if args.allow_empty:
        eval_cmd.append("--allow-empty")
    steps.append(_run_step("truthset_eval", eval_cmd, logs_dir / "02_eval.log"))

    load_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_runtime_load.py"),
        "--memories",
        str(memories_path),
        "--requested-turns",
        str(int(args.load_turns)),
        "--scan-budget",
        str(int(args.scan_budget)),
        "--out-dir",
        str(load_dir),
        "--log-file",
        str(logs_dir / "03_load.log"),
    ]
    steps.append(_run_step("load_harness", load_cmd, logs_dir / "03_load.log"))

    signoff_cmd = [
        python_exe,
        str(REPO_ROOT / "tools" / "run_phase7_signoff.py"),
        "--memories",
        str(memories_path),
        "--eval-cases",
        str(int(args.requested_cases)),
        "--load-turns",
        str(int(args.load_turns)),
        "--scan-budget",
        str(int(args.scan_budget)),
        "--fixture-mode",
        str(args.fixture_mode),
        "--profile",
        str(args.profile),
        "--out-dir",
        str(signoff_dir),
    ]
    if truthset_path:
        signoff_cmd.extend(["--truthset", truthset_path])
    if args.fail_on_gate:
        signoff_cmd.append("--fail-on-gate")
    if args.max_eval_p95_latency_ms is not None:
        signoff_cmd.extend(["--max-eval-p95-latency-ms", str(float(args.max_eval_p95_latency_ms))])
    if args.max_load_p95_latency_ms is not None:
        signoff_cmd.extend(["--max-load-p95-latency-ms", str(float(args.max_load_p95_latency_ms))])
    signoff_cmd.extend(["--max-weak-question-cases", str(max(0, int(args.max_weak_question_cases)))])
    steps.append(_run_step("phase7_signoff", signoff_cmd, logs_dir / "04_signoff.log"))

    trust_regression: dict[str, Any] = {
        "enabled": bool(trust_baseline_path),
        "baseline_summary": trust_baseline_path,
        "candidate_summary": "",
        "decision": "SKIP",
        "regressions": [],
        "report_json": "",
        "report_md": "",
    }
    if trust_baseline_path:
        candidate_summary = signoff_dir / "eval" / "summary.json"
        trust_regression["candidate_summary"] = str(candidate_summary)
        drift_cmd = [
            python_exe,
            str(REPO_ROOT / "tools" / "run_eval_drift.py"),
            "--baseline",
            trust_baseline_path,
            "--candidate",
            str(candidate_summary),
            "--out-dir",
            str(out_dir / "drift"),
            "--fail-on-regression",
        ]
        steps.append(_run_step("trust_regression", drift_cmd, logs_dir / "05_trust_regression.log"))
        drift_log = Path(steps[-1].log_file)
        drift_lines = drift_log.read_text(encoding="utf-8", errors="replace").splitlines() if drift_log.exists() else []
        drift_outputs: dict[str, str] = {}
        for raw in drift_lines:
            text = str(raw).strip()
            if "] " in text:
                text = text.split("] ", 1)[1].strip()
            if "=" not in text:
                continue
            key, value = text.split("=", 1)
            key_norm = key.strip().lower()
            if key_norm:
                drift_outputs[key_norm] = value.strip()
        drift_step_status = str(getattr(steps[-1], "status", "FAIL")).strip().upper()
        derived_decision = "PASS" if drift_step_status == "PASS" else "FAIL"
        drift_decision = str(drift_outputs.get("decision") or derived_decision).strip().upper() or derived_decision
        if drift_step_status != "PASS" and drift_decision == "PASS":
            drift_decision = "FAIL"
        trust_regression["decision"] = drift_decision
        trust_regression["report_json"] = str(drift_outputs.get("report_json") or "")
        trust_regression["report_md"] = str(drift_outputs.get("report_md") or "")
        regressions_raw = str(drift_outputs.get("regressions") or "").strip()
        if regressions_raw and regressions_raw.lower() != "none":
            trust_regression["regressions"] = [item.strip() for item in regressions_raw.split(",") if item.strip()]

    signoff_decision = _load_signoff_decision(signoff_dir)
    failed_steps = [step.name for step in steps if step.status != "PASS"]
    overall = "PASS"
    if failed_steps:
        overall = "FAIL"
    elif str(truthset_quality.get("decision") or "SKIP").upper() == "FAIL":
        overall = "FAIL"
    elif bool(trust_regression.get("enabled")) and str(trust_regression.get("decision") or "SKIP").upper() != "PASS":
        overall = "FAIL"
    elif signoff_decision == "FAIL":
        overall = "FAIL"
    elif signoff_decision == "UNKNOWN":
        overall = "FAIL"

    manifest = {
        "generated_at": _now_iso(),
        "decision": overall,
        "signoff_decision": signoff_decision,
        "truthset": {
            "mode": truthset_mode,
            "path": truthset_path,
            "case_count": int(truthset_case_count),
            "require_reviewed_truthset": bool(args.require_reviewed_truthset),
            "quality": truthset_quality,
        },
        "trust_regression": trust_regression,
        "memories_path": str(memories_path),
        "out_dir": str(out_dir),
        "steps": [item.to_dict() for item in steps],
        "failed_steps": failed_steps,
        "artifacts": {
            "eval_dir": str(eval_dir),
            "load_dir": str(load_dir),
            "signoff_dir": str(signoff_dir),
            "logs_dir": str(logs_dir),
        },
    }
    manifest_path = out_dir / "pilot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    bundle_path = out_dir / f"support_bundle_{_stamp()}.zip"
    _bundle_support(out_dir, bundle_path, manifest_path)

    pilot_report = _build_pilot_report(
        overall=overall,
        signoff_decision=signoff_decision,
        manifest=manifest,
        bundle_path=bundle_path,
        truthset_mode=truthset_mode,
        truthset_path=truthset_path,
        truthset_case_count=truthset_case_count,
        truthset_quality=truthset_quality,
        trust_regression=trust_regression,
    )
    report_json_path = out_dir / "pilot_report.json"
    report_md_path = out_dir / "pilot_report.md"
    report_txt_path = out_dir / "pilot_report.txt"
    report_json_path.write_text(json.dumps(pilot_report, indent=2) + "\n", encoding="utf-8")
    report_md_path.write_text(_render_pilot_report_md(pilot_report), encoding="utf-8")
    report_txt_path.write_text(_render_pilot_report_txt(pilot_report), encoding="utf-8")
    manifest["pilot_report"] = {
        "json": str(report_json_path),
        "markdown": str(report_md_path),
        "text": str(report_txt_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    md_lines = [
        "# Pilot Acceptance Summary",
        "",
        f"- decision: `{overall}`",
        f"- signoff_decision: `{signoff_decision}`",
        f"- truthset_quality: `{str(truthset_quality.get('decision') or 'SKIP')}`",
        f"- trust_regression: `{str(trust_regression.get('decision') or 'SKIP')}`",
        f"- memories_path: `{memories_path}`",
        f"- support_bundle: `{bundle_path}`",
        "",
        "## Steps",
    ]
    for step in steps:
        md_lines.append(
            f"- {step.name}: `{step.status}` (rc={step.returncode}, duration={step.duration_s:.2f}s)"
        )
    (out_dir / "pilot_manifest.md").write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")
    (out_dir / "pilot_brief.txt").write_text(
        "\n".join(
            [
                f"Decision: {overall}",
                f"Signoff decision: {signoff_decision}",
                f"Truthset mode: {truthset_mode}",
                f"Truthset path: {truthset_path or '(auto generated)'}",
                f"Truthset quality: {str(truthset_quality.get('decision') or 'SKIP')}",
                f"Trust regression: {str(trust_regression.get('decision') or 'SKIP')}",
                f"Pilot report: {report_json_path}",
                f"Support bundle: {bundle_path}",
                f"Manifest: {manifest_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"decision={overall}")
    print(f"manifest={manifest_path}")
    print(f"pilot_report_json={report_json_path}")
    print(f"support_bundle={bundle_path}")
    if overall != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
