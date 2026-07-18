#!/usr/bin/env python3
"""Prepare a privacy-bounded MNO support ticket and optionally submit it."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any, Sequence
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.memory.content_safety import scrub_content


DEFAULT_REPOSITORY = "EmergentKnowledgeGroup/ModelNumquamOblita"
MAX_LOG_BYTES = 128 * 1024


def _quick_check_argv() -> list[str]:
    probe = (
        "import json; "
        "from engine.runtime import server; "
        "from engine.memory import SqliteAtomStore; "
        "assert (server.UI_ROOT / 'index.html').is_file(); "
        "assert server.PACKAGING_GUIDE_PATH.is_file(); "
        "print(json.dumps({'version': server._project_version(), 'runtime_root': str(server.RUNTIME_ROOT)}))"
    )
    return [sys.executable, "-c", probe]


def _source_suite_available(repo_root: Path) -> bool:
    return (repo_root / "pyproject.toml").is_file() and (repo_root / "tests").is_dir()


def _version() -> str:
    try:
        return importlib_metadata.version("modelnumquamoblita")
    except importlib_metadata.PackageNotFoundError:
        return "source-checkout"


def _default_output_root() -> Path:
    override = str(os.environ.get("MNO_RUNTIME_STATE_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve() / "reports" / "support"
    repo_root = REPO_ROOT
    if (repo_root / "pyproject.toml").is_file():
        return repo_root / "runtime" / "reports" / "support"
    if os.name == "nt":
        base = str(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or "").strip()
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "ModelNumquamOblita" / "reports" / "support"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ModelNumquamOblita" / "reports" / "support"
    state = str(os.environ.get("XDG_STATE_HOME") or "").strip()
    return (Path(state).expanduser() if state else Path.home() / ".local" / "state") / "modelnumquamoblita" / "reports" / "support"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_check(argv: Sequence[str], *, cwd: Path, timeout_s: float) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            list(argv), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, check=False, shell=False,
        )
        combined = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
        return {
            "argv": list(argv),
            "exit_code": int(result.returncode),
            "status": "passed" if result.returncode == 0 else "failed",
            "output": scrub_content(combined[-12_000:]),
            "started_at": started.isoformat(),
        }
    except subprocess.TimeoutExpired:
        return {"argv": list(argv), "exit_code": None, "status": "timeout", "output": "", "started_at": started.isoformat()}
    except OSError as exc:
        return {"argv": list(argv), "exit_code": None, "status": "unavailable", "output": scrub_content(str(exc)), "started_at": started.isoformat()}


def _collect_log(path: Path, *, attachments: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    row: dict[str, Any] = {"source_name": resolved.name, "included": False}
    try:
        raw = resolved.read_bytes()[:MAX_LOG_BYTES]
        text = raw.decode("utf-8", errors="replace")
        redacted = str(scrub_content(text))
        target = attachments / f"{len(list(attachments.glob('*'))):02d}-{resolved.name}.redacted.log"
        _atomic_write(target, redacted)
        row.update({"included": True, "attachment": target.name, "source_bytes_read": len(raw), "truncated": resolved.stat().st_size > len(raw)})
    except OSError as exc:
        row["error"] = str(scrub_content(str(exc)))
    return row


def _render_issue(ticket: dict[str, Any]) -> str:
    checks = list(ticket.get("checks") or [])
    logs = list(ticket.get("logs") or [])
    check_lines = [f"- `{ ' '.join(row['argv']) }`: **{row['status']}** (exit `{row['exit_code']}`)" for row in checks]
    log_lines = [f"- `{row.get('source_name')}`: {row.get('attachment') if row.get('included') else row.get('error', 'not included')}" for row in logs]
    return "\n".join([
        f"# {ticket['title']}", "", "## Summary", str(ticket["summary"]), "",
        "## Reproduction steps", str(ticket["steps"]), "", "## Expected behavior", str(ticket["expected"]), "",
        "## Actual behavior", str(ticket["actual"]), "", "## Environment", "```json",
        json.dumps(ticket["environment"], indent=2), "```", "", "## Checks run",
        *(check_lines or ["- Not requested. Run `mno-report ... --check quick` for the bounded compatibility suite."]), "",
        "## Redacted attachments", *(log_lines or ["- None. Attach logs explicitly with `--log PATH`; MNO never sweeps memory/runtime files automatically."]), "",
        "## Agent notes", str(ticket.get("agent_notes") or "Not provided."), "",
        "> Privacy: this report was generated with bounded secret redaction. Review it before submission; do not attach memory stores, WAL/SHM files, WSS data, credentials, or private datasets.", "",
    ])


def build_ticket(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    output_root = Path(args.output_dir).expanduser().resolve() if args.output_dir else _default_output_root()
    ticket_dir = output_root / f"ticket_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    attachments = ticket_dir / "attachments"
    attachments.mkdir(parents=True, exist_ok=False)
    environment = {
        "mno_version": _version(), "python": platform.python_version(), "python_executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(), "machine": platform.machine(), "command": "mno-report",
    }
    checks: list[dict[str, Any]] = []
    repo_root = REPO_ROOT
    if args.check in {"quick", "full"}:
        checks.append(_run_check(_quick_check_argv(), cwd=repo_root, timeout_s=float(args.timeout)))
    if args.check == "full":
        if _source_suite_available(repo_root):
            checks.append(_run_check([sys.executable, "-m", "pytest", "-q"], cwd=repo_root, timeout_s=float(args.timeout)))
        else:
            checks.append({
                "argv": ["pytest", "<source-checkout-suite>"],
                "exit_code": None,
                "status": "unavailable",
                "output": "Full repository tests require a source checkout; the installed-product smoke check still ran.",
                "started_at": datetime.now(timezone.utc).isoformat(),
            })
    logs = [_collect_log(Path(value), attachments=attachments) for value in list(args.log or [])]
    ticket = scrub_content({
        "schema": "mno.support_ticket.v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": args.repository, "title": args.title, "summary": args.summary, "steps": args.steps,
        "expected": args.expected, "actual": args.actual, "agent_notes": args.agent_notes,
        "environment": environment, "checks": checks, "logs": logs,
    })
    issue_body = _render_issue(ticket)
    _atomic_write(ticket_dir / "ticket.json", json.dumps(ticket, indent=2) + "\n")
    _atomic_write(ticket_dir / "issue.md", issue_body)
    _atomic_write(ticket_dir / "README.txt", "Review issue.md and redacted attachments before submission. Never add memory databases or private datasets.\n")
    return ticket_dir, ticket


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a redacted, reproducible MNO bug report for an agent or human.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--steps", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--agent-notes", default="")
    parser.add_argument("--log", action="append", default=[], help="Explicit log file to copy in redacted, bounded form; repeatable.")
    parser.add_argument("--check", choices=("none", "quick", "full"), default="quick")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--submit", action="store_true", help="After local report creation, submit with authenticated GitHub CLI.")
    args = parser.parse_args()
    ticket_dir, ticket = build_ticket(args)
    result: dict[str, Any] = {"ok": True, "ticket_dir": str(ticket_dir), "issue_body": str(ticket_dir / "issue.md"), "submitted": False}
    if args.submit:
        if shutil.which("gh") is None:
            result.update({"ok": False, "error": "GITHUB_CLI_NOT_AVAILABLE"})
            print(json.dumps(result, indent=2))
            return 2
        submitted = subprocess.run(
            ["gh", "issue", "create", "--repo", str(args.repository), "--title", str(ticket["title"]), "--body-file", str(ticket_dir / "issue.md")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False,
        )
        if submitted.returncode != 0:
            result.update({"ok": False, "error": "GITHUB_SUBMISSION_FAILED", "detail": scrub_content(submitted.stderr[-2000:])})
            print(json.dumps(result, indent=2))
            return int(submitted.returncode or 1)
        result.update({"submitted": True, "issue_url": submitted.stdout.strip()})
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
