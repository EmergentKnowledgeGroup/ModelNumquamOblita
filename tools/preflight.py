#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import os
import shlex
import shutil
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PYTHON_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("py", "-3.15"),
    ("py", "-3.14"),
    ("py", "-3.13"),
    ("py", "-3.12"),
    ("python3.15",),
    ("python3.14",),
    ("python3.13",),
    ("python3.12",),
    ("/usr/bin/python3",),
    ("python3",),
    ("python",),
)
PYTHON_BOOTSTRAP_PROBE = (
    "import sys, venv, xml.parsers.expat; "
    "print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    remediation: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "remediation": self.remediation,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_memories(repo_root: Path) -> Path:
    canonical = repo_root / "runtime" / "imports"
    legacy = repo_root / ".runtime" / "imports"
    canonical_exists = canonical.exists()
    legacy_exists = legacy.exists()
    if canonical_exists and legacy_exists:
        warnings.warn(
            f"both canonical {canonical} and legacy {legacy} exist; using canonical runtime/ imports",
            RuntimeWarning,
            stacklevel=2,
        )
    base = canonical if canonical_exists or not legacy_exists else legacy
    sqlite_default = base / "atoms.sqlite3"
    return sqlite_default if sqlite_default.exists() else base / "memories.json"


def _status_line(check: CheckResult) -> str:
    badge = {
        "pass": "[PASS]",
        "warn": "[WARN]",
        "fail": "[FAIL]",
    }.get(check.status, "[INFO]")
    line = f"{badge} {check.name}: {check.detail}"
    if check.remediation:
        line += f" | fix: {check.remediation}"
    return line


def _parse_min_python(min_python: str) -> tuple[int, int]:
    try:
        return tuple(int(piece) for piece in min_python.split(".", 1))  # type: ignore[return-value]
    except ValueError:
        return (3, 12)


def _clean_probe_detail(raw: str) -> str:
    return " ".join(str(raw or "").strip().split())


def python_command_argv(python_cmd: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(python_cmd, (tuple, list)):
        parts = tuple(str(piece) for piece in python_cmd if str(piece).strip())
        return (str(Path(parts[0]).expanduser()), *parts[1:]) if parts else ()
    candidate = str(python_cmd or "").strip()
    if not candidate:
        return ()
    expanded = Path(candidate).expanduser()
    if expanded.exists():
        return (str(expanded),)
    try:
        parts = shlex.split(candidate, posix=os.name != "nt")
    except ValueError:
        return (candidate,)
    normalized = tuple(
        piece[1:-1] if len(piece) >= 2 and piece[0] == piece[-1] and piece[0] in {'"', "'"} else piece
        for piece in parts
    )
    return (str(Path(normalized[0]).expanduser()), *normalized[1:]) if normalized else ()


def python_command_display(argv: tuple[str, ...] | list[str]) -> str:
    return subprocess.list2cmdline(list(argv))


def _discover_python_version(python_cmd: str | tuple[str, ...] | list[str]) -> tuple[tuple[int, int] | None, str]:
    argv = python_command_argv(python_cmd)
    if not argv:
        return None, "empty candidate"
    resolved = shutil.which(argv[0])
    if not resolved and not Path(argv[0]).expanduser().exists():
        return None, "not found"
    try:
        proc = subprocess.run(
            [*argv, "-c", PYTHON_BOOTSTRAP_PROBE],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, _clean_probe_detail(str(exc))
    if proc.returncode != 0:
        detail = _clean_probe_detail(str(proc.stderr or proc.stdout or f"probe exited with {proc.returncode}"))
        return None, detail or f"probe exited with {proc.returncode}"
    raw = str(proc.stdout or "").strip()
    try:
        major_str, minor_str = raw.split(".", 1)
        return (int(major_str), int(minor_str)), ""
    except ValueError:
        return None, f"unexpected probe output: {raw or 'empty output'}"


def find_supported_python_command(
    *,
    candidates: tuple[str | tuple[str, ...], ...] = DEFAULT_PYTHON_CANDIDATES,
    min_python: str = "3.12",
) -> str | None:
    argv = find_supported_python_argv(candidates=candidates, min_python=min_python)
    return python_command_display(argv) if argv else None


def find_supported_python_argv(
    *,
    candidates: tuple[str | tuple[str, ...], ...] = DEFAULT_PYTHON_CANDIDATES,
    min_python: str = "3.12",
) -> tuple[str, ...] | None:
    min_major, min_minor = _parse_min_python(min_python)
    best_command: tuple[str, ...] | None = None
    best_score: tuple[int, int, int] | None = None
    seen: set[str] = set()
    for index, raw_candidate in enumerate(candidates):
        candidate = python_command_argv(raw_candidate)
        candidate_key = "\0".join(candidate)
        if not candidate or candidate_key in seen:
            continue
        seen.add(candidate_key)
        version, _detail = _discover_python_version(candidate)
        if version is None:
            continue
        major, minor = version
        if (major, minor) < (min_major, min_minor):
            continue
        score = (major, minor, -index)
        if best_score is None or score > best_score:
            best_score = score
            best_command = candidate
    return best_command


def _python_check(min_python: str, *, python_cmd: str = "") -> CheckResult:
    min_major, min_minor = _parse_min_python(min_python)
    candidate = python_command_argv(python_cmd) or (sys.executable,)
    candidate_display = python_command_display(candidate)
    version, probe_detail = _discover_python_version(candidate)
    if version is None:
        detail = f"unable to validate bootstrap readiness for {candidate_display}"
        if probe_detail:
            detail += f": {probe_detail}"
        return CheckResult(
            name="python_version",
            status="fail",
            detail=detail,
            remediation=(
                f"Install Python {min_major}.{min_minor}+ and point setup at a healthy interpreter "
                "with --python-cmd or MNO_PYTHON."
            ),
        )
    detail_prefix = "detected " if not str(python_cmd or "").strip() else f"detected via {candidate_display} "
    major, minor = version
    if (major, minor) < (min_major, min_minor):
        return CheckResult(
            name="python_version",
            status="fail",
            detail=f"{detail_prefix}{major}.{minor}, required >= {min_major}.{min_minor}",
            remediation=f"Install Python {min_major}.{min_minor}+ and rerun setup.",
        )
    return CheckResult(
        name="python_version",
        status="pass",
        detail=f"{detail_prefix}{major}.{minor}",
    )


def _repo_writable_check(repo_root: Path) -> CheckResult:
    runtime_dir = repo_root / "runtime"
    probe = runtime_dir / ".preflight_write_probe"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return CheckResult(
            name="repo_writable",
            status="fail",
            detail=f"unable to write under {runtime_dir}: {exc}",
            remediation="Check file permissions and ensure the project is not read-only.",
        )
    return CheckResult(
        name="repo_writable",
        status="pass",
        detail=f"write access confirmed at {runtime_dir}",
    )


def _tool_check(tool_name: str, *, required: bool) -> CheckResult:
    found = shutil.which(tool_name)
    if found:
        return CheckResult(
            name=f"tool_{tool_name}",
            status="pass",
            detail=f"found at {found}",
        )
    status = "fail" if required else "warn"
    remediation = f"Install `{tool_name}` or remove workflows that depend on it."
    return CheckResult(
        name=f"tool_{tool_name}",
        status=status,
        detail="not found in PATH",
        remediation=remediation,
    )


def _memory_path_check(memories: Path) -> CheckResult:
    suffix = memories.suffix.lower()
    if suffix not in {".sqlite3", ".sqlite", ".db", ".json"}:
        return CheckResult(
            name="memories_path",
            status="fail",
            detail=f"unsupported extension for {memories}",
            remediation="Use a sqlite store (*.sqlite3/*.db) or a memories.json file.",
        )
    if not memories.exists():
        return CheckResult(
            name="memories_path",
            status="fail",
            detail=f"missing: {memories}",
            remediation="Run import first (`python3 tools/import_memories.py --input <conversations.json>`).",
        )
    if not memories.is_file():
        return CheckResult(
            name="memories_path",
            status="fail",
            detail=f"not a file: {memories}",
            remediation="Provide a file path, not a directory.",
        )
    size = memories.stat().st_size
    if size <= 0:
        return CheckResult(
            name="memories_path",
            status="fail",
            detail=f"file is empty: {memories}",
            remediation="Re-run import and verify memory artifact generation.",
        )
    return CheckResult(
        name="memories_path",
        status="pass",
        detail=f"{memories} ({size} bytes)",
    )


def _input_path_check(input_path: Path) -> CheckResult:
    if not input_path.exists():
        return CheckResult(
            name="input_path",
            status="fail",
            detail=f"missing: {input_path}",
            remediation="Provide a valid conversations export path with --input.",
        )
    if not input_path.is_file():
        return CheckResult(
            name="input_path",
            status="fail",
            detail=f"not a file: {input_path}",
            remediation="Provide the JSON export file, not a directory.",
        )
    size = input_path.stat().st_size
    if size <= 0:
        return CheckResult(
            name="input_path",
            status="fail",
            detail=f"file is empty: {input_path}",
            remediation="Re-export your conversations and retry.",
        )
    return CheckResult(
        name="input_path",
        status="pass",
        detail=f"{input_path} ({size} bytes)",
    )


def run_preflight(
    *,
    repo_root: Path,
    mode: str,
    min_python: str,
    python_cmd: str = "",
    memories: Path | None = None,
    input_path: Path | None = None,
    require_gh: bool = False,
) -> dict[str, Any]:
    checks: list[CheckResult] = []
    checks.append(_python_check(min_python, python_cmd=python_cmd))
    checks.append(_repo_writable_check(repo_root))
    checks.append(_tool_check("git", required=False))
    checks.append(_tool_check("gh", required=require_gh))

    if mode in {"runtime", "pilot"}:
        memory_target = memories or _default_memories(repo_root)
        checks.append(_memory_path_check(memory_target.resolve()))
    if mode == "pilot":
        if input_path is None:
            checks.append(
                CheckResult(
                    name="input_path",
                    status="fail",
                    detail="missing: --input",
                    remediation="Provide a conversations export path with --input.",
                )
            )
        else:
            checks.append(_input_path_check(input_path.resolve()))

    failures = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    status = "fail" if failures else ("warn" if warnings else "pass")
    return {
        "ok": not failures,
        "status": status,
        "mode": mode,
        "repo_root": str(repo_root),
        "checks": [check.as_dict() for check in checks],
        "failure_count": len(failures),
        "warning_count": len(warnings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local preflight checks for setup/runtime workflows.")
    parser.add_argument("--mode", choices=["setup", "runtime", "pilot"], default="setup")
    parser.add_argument("--repo-root", default=str(_repo_root()), help="Project root path.")
    parser.add_argument("--memories", default="", help="Memories artifact path for runtime/pilot mode.")
    parser.add_argument("--input", default="", help="Input export path for pilot mode.")
    parser.add_argument("--min-python", default="3.12")
    parser.add_argument("--python-cmd", default="", help="Optional Python command to validate instead of the current interpreter.")
    parser.add_argument("--require-gh", action="store_true", help="Fail when gh CLI is not available.")
    parser.add_argument("--json", action="store_true", help="Emit JSON payload.")
    parser.add_argument("--out", default="", help="Optional path to write JSON report.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    memories = Path(args.memories).expanduser() if str(args.memories).strip() else None
    input_path = Path(args.input).expanduser() if str(args.input).strip() else None
    report = run_preflight(
        repo_root=repo_root,
        mode=str(args.mode),
        min_python=str(args.min_python),
        python_cmd=str(args.python_cmd or "").strip(),
        memories=memories,
        input_path=input_path,
        require_gh=bool(args.require_gh),
    )

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"report_json={out_path}")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"preflight_mode={report['mode']}")
        print(f"preflight_status={report['status']}")
        for payload in report["checks"]:
            print(_status_line(CheckResult(**payload)))
        print(f"failures={report['failure_count']} warnings={report['warning_count']}")

    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
