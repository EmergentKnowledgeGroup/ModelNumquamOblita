#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GH_METADATA_TIMEOUT_SEC = 20


def _run(cmd: list[str], *, cwd: Path) -> int:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, check=False)
    return int(proc.returncode)


def _coderabbit_review_count(*, pr: int, repo_root: Path) -> int | None:
    cmd = [
        "gh",
        "pr",
        "view",
        str(int(pr)),
        "--json",
        "reviews",
        "--jq",
        "([.reviews[] | select(.author.login==\"coderabbitai\")] | length)",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            check=False,
            timeout=GH_METADATA_TIMEOUT_SEC,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if int(proc.returncode) != 0:
        return None
    try:
        return int(str(proc.stdout or "").strip())
    except Exception:
        return None


def _resolve_gate_args(args: argparse.Namespace, *, repo_root: Path) -> tuple[argparse.Namespace, dict[str, Any]]:
    gate_args = argparse.Namespace(**vars(args))
    requested_mode = str(getattr(args, "gate_mode", "auto") or "auto").strip().lower()
    review_count = _coderabbit_review_count(pr=int(args.pr), repo_root=repo_root)
    effective_mode = requested_mode
    if requested_mode == "auto":
        effective_mode = "post-fix" if int(review_count or 0) > 0 else "initial"
    if effective_mode == "post-fix":
        gate_args.require_submitted_review = False
        gate_args.allow_no_review = True
        gate_args.once = True
        gate_args.disable_auto_nudge = True
        gate_args.auto_nudge_after_sec = 0
        gate_args.gate_timeout_sec = min(int(gate_args.gate_timeout_sec), 120)
    metadata = {
        "gate_mode_requested": requested_mode,
        "gate_mode_effective": effective_mode,
        "coderabbit_review_count": review_count,
    }
    return gate_args, metadata


def _gate_command(args: argparse.Namespace, *, repo_root: Path) -> list[str]:
    gate_script = repo_root / "tools" / "pr_feedback_gate.py"
    cmd = [
        sys.executable,
        str(gate_script),
        "--repo",
        str(args.repo),
        "--pr",
        str(args.pr),
        "--repo-root",
        str(repo_root),
        "--timeout-sec",
        str(int(args.gate_timeout_sec)),
        "--poll-sec",
        str(int(args.gate_poll_sec)),
        "--check-signal-settle-sec",
        str(int(args.check_signal_settle_sec)),
        "--auto-nudge-after-sec",
        str(int(args.auto_nudge_after_sec)),
        "--nudge-comment-body",
        str(args.nudge_comment_body),
    ]
    if bool(args.allow_no_review):
        cmd.append("--allow-no-review")
    if bool(args.require_submitted_review):
        cmd.append("--require-submitted-review")
    if bool(args.disable_auto_nudge):
        cmd.append("--disable-auto-nudge")
    if bool(args.once):
        cmd.append("--once")
    return cmd


def _merge_command(args: argparse.Namespace) -> list[str]:
    method = str(args.merge_method).strip().lower()
    if method not in {"squash", "merge", "rebase"}:
        raise ValueError(f"unsupported merge method: {method}")
    cmd = ["gh", "pr", "merge", str(args.pr), f"--{method}"]
    if bool(args.delete_branch):
        cmd.append("--delete-branch")
    return cmd


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_report(*, report_dir: Path, pr: int, payload: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"pr_workflow_pr{int(pr)}_{stamp}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the standard PR gate workflow (optional merge after gate pass).",
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument("--repo-root", default=".", help="repository root")
    parser.add_argument(
        "--gate-mode",
        choices=["auto", "initial", "post-fix"],
        default="auto",
        help="gate policy mode: auto selects initial (no prior CR review) or post-fix (prior CR review exists)",
    )
    parser.add_argument(
        "--post-fix-no-resubmit",
        action="store_true",
        help="shortcut for --gate-mode post-fix",
    )
    parser.add_argument("--gate-timeout-sec", type=int, default=900)
    parser.add_argument("--gate-poll-sec", type=int, default=30)
    parser.add_argument(
        "--check-signal-settle-sec",
        type=int,
        default=180,
        help="minimum settle window for check-only review signal before gate pass",
    )
    parser.add_argument("--auto-nudge-after-sec", type=int, default=600)
    parser.add_argument(
        "--require-submitted-review",
        dest="require_submitted_review",
        action="store_true",
        default=True,
        help="require submitted CodeRabbit review on current head (default on)",
    )
    parser.add_argument(
        "--allow-check-signal",
        dest="require_submitted_review",
        action="store_false",
        help="allow successful CodeRabbit check signal when submitted review is missing",
    )
    parser.add_argument("--disable-auto-nudge", action="store_true")
    parser.add_argument("--nudge-comment-body", default="@coderabbitai review")
    parser.add_argument("--allow-no-review", action="store_true")
    parser.add_argument("--once", action="store_true", help="run gate once instead of polling")
    parser.add_argument(
        "--fallback-on-timeout",
        dest="fallback_on_timeout",
        action="store_true",
        default=True,
        help="if strict gate times out, run one fallback gate pass with --allow-no-review --once",
    )
    parser.add_argument(
        "--no-fallback-on-timeout",
        dest="fallback_on_timeout",
        action="store_false",
        help="disable timeout fallback and fail immediately when strict gate times out",
    )
    parser.add_argument(
        "--fallback-timeout-sec",
        type=int,
        default=120,
        help="timeout used for fallback gate pass",
    )
    parser.add_argument(
        "--report-dir",
        default="runtime/reports",
        help="directory where workflow report json is written",
    )
    parser.add_argument(
        "--request-review-comment",
        action="store_true",
        help="post @coderabbitai review comment before running gate",
    )
    parser.add_argument("--merge", action="store_true", help="merge PR after gate passes")
    parser.add_argument("--merge-method", default="squash", choices=["squash", "merge", "rebase"])
    parser.add_argument(
        "--delete-branch",
        action="store_true",
        default=True,
        help="delete remote branch on merge (default on)",
    )
    parser.add_argument(
        "--keep-branch",
        dest="delete_branch",
        action="store_false",
        help="keep branch after merge",
    )
    args = parser.parse_args(argv)
    if bool(args.post_fix_no_resubmit):
        args.gate_mode = "post-fix"

    repo_root = Path(args.repo_root).resolve()
    report_dir = (repo_root / str(args.report_dir)).resolve()
    started = time.time()
    report_payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "repo": str(args.repo),
        "pr": int(args.pr),
        "repo_root": str(repo_root),
        "status": "running",
        "steps": [],
    }

    if bool(args.request_review_comment):
        comment_cmd = ["gh", "pr", "comment", str(args.pr), "--body", str(args.nudge_comment_body)]
        print(f"[run_pr_workflow] {' '.join(comment_cmd)}")
        code = _run(comment_cmd, cwd=repo_root)
        report_payload["steps"].append(
            {
                "name": "request_review_comment",
                "command": comment_cmd,
                "returncode": int(code),
            }
        )
        if code != 0:
            report_payload["status"] = "failed"
            report_payload["duration_s"] = round(max(0.0, time.time() - started), 3)
            report_path = _write_report(report_dir=report_dir, pr=int(args.pr), payload=report_payload)
            print(f"[run_pr_workflow] report={report_path}")
            return code

    gate_args, gate_meta = _resolve_gate_args(args, repo_root=repo_root)
    report_payload["gate_mode"] = gate_meta
    gate_cmd = _gate_command(gate_args, repo_root=repo_root)
    print(f"[run_pr_workflow] {' '.join(gate_cmd)}")
    code = _run(gate_cmd, cwd=repo_root)
    report_payload["steps"].append(
        {
            "name": "gate_primary",
            "command": gate_cmd,
            "returncode": int(code),
        }
    )
    primary_is_post_fix_once = bool(gate_args.allow_no_review) and bool(gate_args.once)
    if code != 0 and bool(args.fallback_on_timeout) and int(code) == 3 and not primary_is_post_fix_once:
        fallback_args = argparse.Namespace(**vars(args))
        fallback_args.allow_no_review = True
        fallback_args.once = True
        fallback_args.gate_timeout_sec = int(max(5, int(args.fallback_timeout_sec)))
        fallback_cmd = _gate_command(fallback_args, repo_root=repo_root)
        print(f"[run_pr_workflow] fallback {' '.join(fallback_cmd)}")
        fallback_code = _run(fallback_cmd, cwd=repo_root)
        report_payload["steps"].append(
            {
                "name": "gate_fallback_allow_no_review_once",
                "command": fallback_cmd,
                "returncode": int(fallback_code),
            }
        )
        code = int(fallback_code)
    if code != 0:
        report_payload["status"] = "failed"
        report_payload["duration_s"] = round(max(0.0, time.time() - started), 3)
        report_path = _write_report(report_dir=report_dir, pr=int(args.pr), payload=report_payload)
        print(f"[run_pr_workflow] report={report_path}")
        return code

    if bool(args.merge):
        merge_cmd = _merge_command(args)
        print(f"[run_pr_workflow] {' '.join(merge_cmd)}")
        merge_code = _run(merge_cmd, cwd=repo_root)
        report_payload["steps"].append(
            {
                "name": "merge",
                "command": merge_cmd,
                "returncode": int(merge_code),
            }
        )
        report_payload["status"] = "ok" if merge_code == 0 else "failed"
        report_payload["duration_s"] = round(max(0.0, time.time() - started), 3)
        report_path = _write_report(report_dir=report_dir, pr=int(args.pr), payload=report_payload)
        print(f"[run_pr_workflow] report={report_path}")
        return int(merge_code)

    report_payload["status"] = "ok"
    report_payload["duration_s"] = round(max(0.0, time.time() - started), 3)
    report_path = _write_report(report_dir=report_dir, pr=int(args.pr), payload=report_payload)
    print(f"[run_pr_workflow] report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
