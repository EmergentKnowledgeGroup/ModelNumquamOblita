#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.preflight import _discover_python_version, find_supported_python_command, run_preflight


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _emit(msg: str, *, quiet: bool) -> None:
    if not quiet:
        print(msg)


def _run(command: list[str], *, cwd: Path, quiet: bool) -> int:
    _emit(f"cmd={' '.join(command)}", quiet=quiet)
    proc = subprocess.run(command, cwd=cwd, check=False)
    return int(proc.returncode)


def _default_python() -> str:
    if os.name == "nt":
        py_launcher = shutil_which("py")
        if py_launcher:
            return "py"
    discovered = find_supported_python_command(
        candidates=("python3.15", "python3.14", "python3.13", "python3.12", "python3", "python", sys.executable),
        min_python="3.12",
    )
    return discovered or sys.executable


def shutil_which(tool: str) -> str | None:
    from shutil import which

    return which(tool)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _alternate_platform_venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "bin" / "python"
    return venv_dir / "Scripts" / "python.exe"


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _quarantine_incompatible_venv(venv_dir: Path) -> Path | None:
    target_python = _venv_python(venv_dir)
    if target_python.exists():
        return None
    other_platform_python = _alternate_platform_venv_python(venv_dir)
    if not other_platform_python.exists():
        return None
    quarantine_dir = venv_dir.with_name(f"{venv_dir.name}.incompatible_{_timestamp_slug()}")
    venv_dir.rename(quarantine_dir)
    return quarantine_dir


def _quarantine_unhealthy_venv(venv_dir: Path, *, min_python: str) -> tuple[Path | None, str]:
    target_python = _venv_python(venv_dir)
    if not target_python.exists():
        return None, ""
    version, detail = _discover_python_version(str(target_python))
    min_major, min_minor = (int(piece) for piece in min_python.split(".", 1))
    if version is not None and version >= (min_major, min_minor):
        return None, ""
    quarantine_dir = venv_dir.with_name(f"{venv_dir.name}.incompatible_{_timestamp_slug()}")
    venv_dir.rename(quarantine_dir)
    reason = detail or "bootstrap readiness probe failed"
    return quarantine_dir, reason


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _write_report(*, out_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    json_path = out_dir / f"setup_{stamp}.json"
    md_path = out_dir / f"setup_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Local Setup Report",
        "",
        f"- status: `{payload.get('status', 'unknown')}`",
        f"- created_at: `{payload.get('created_at', '')}`",
        f"- repo_root: `{payload.get('repo_root', '')}`",
        f"- venv: `{payload.get('venv', '')}`",
        "",
        "## Steps",
    ]
    for step in payload.get("steps", []):
        lines.append(f"- `{step.get('name', 'step')}`: `{step.get('status', 'unknown')}`")
        detail = str(step.get("detail", "")).strip()
        if detail:
            lines.append(f"  - {detail}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="One-command local setup for NumquamOblita.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--venv", default=".venv")
    parser.add_argument("--python-cmd", default=_default_python())
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--out-dir", default="runtime/setup")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    venv_dir = (repo_root / args.venv).resolve()
    out_dir = (repo_root / args.out_dir).resolve()
    if not _is_within(venv_dir, repo_root):
        print(f"error=--venv must resolve under repo root: {repo_root}")
        return 2
    if not _is_within(out_dir, repo_root):
        print(f"error=--out-dir must resolve under repo root: {repo_root}")
        return 2
    created_at = datetime.now(timezone.utc).isoformat()
    steps: list[dict[str, str]] = []

    preflight = run_preflight(
        repo_root=repo_root,
        mode="setup",
        min_python="3.12",
        python_cmd=str(args.python_cmd),
        require_gh=False,
    )
    steps.append(
        {
            "name": "preflight",
            "status": str(preflight["status"]),
            "detail": f"failures={preflight['failure_count']} warnings={preflight['warning_count']}",
        }
    )
    if not preflight["ok"]:
        report_payload = {
            "status": "fail",
            "created_at": created_at,
            "repo_root": str(repo_root),
            "venv": str(venv_dir),
            "steps": steps,
            "preflight": preflight,
        }
        json_path, md_path = _write_report(out_dir=out_dir, payload=report_payload)
        _emit("setup_status=fail", quiet=args.quiet)
        _emit(f"report_json={json_path}", quiet=args.quiet)
        _emit(f"report_md={md_path}", quiet=args.quiet)
        return 2

    venv_python = _venv_python(venv_dir)
    commands = [
        ["python-cmd", args.python_cmd, "-m", "venv", str(venv_dir)],
        ["venv-pip-upgrade", str(venv_python), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"],
        ["venv-install-editable", str(venv_python), "-m", "pip", "install", "-e", "."],
        ["venv-install-pytest", str(venv_python), "-m", "pip", "install", "pytest"],
    ]
    if not args.skip_smoke:
        commands.append(
            [
                "smoke-test",
                str(venv_python),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_config.py",
            ]
        )

    if args.plan_only or args.preflight_only:
        status = "pass"
        if args.preflight_only:
            _emit("mode=preflight_only", quiet=args.quiet)
        else:
            _emit("mode=plan_only", quiet=args.quiet)
            for command in commands:
                _emit(f"plan_step={command[0]} cmd={' '.join(command[1:])}", quiet=args.quiet)
        report_payload = {
            "status": status,
            "created_at": created_at,
            "repo_root": str(repo_root),
            "venv": str(venv_dir),
            "steps": steps,
            "preflight": preflight,
            "planned_commands": commands,
        }
        json_path, md_path = _write_report(out_dir=out_dir, payload=report_payload)
        _emit(f"report_json={json_path}", quiet=args.quiet)
        _emit(f"report_md={md_path}", quiet=args.quiet)
        return 0

    quarantined_venv = _quarantine_incompatible_venv(venv_dir) if venv_dir.exists() else None
    if quarantined_venv is not None:
        steps.append(
            {
                "name": "quarantine_incompatible_venv",
                "status": "pass",
                "detail": f"moved incompatible venv to {quarantined_venv}",
            }
        )
    unhealthy_venv, unhealthy_detail = _quarantine_unhealthy_venv(venv_dir, min_python="3.12") if venv_dir.exists() else (None, "")
    if unhealthy_venv is not None:
        steps.append(
            {
                "name": "quarantine_unhealthy_venv",
                "status": "pass",
                "detail": f"moved unhealthy venv to {unhealthy_venv} ({unhealthy_detail})",
            }
        )

    if not venv_python.exists():
        rc = _run([args.python_cmd, "-m", "venv", str(venv_dir)], cwd=repo_root, quiet=args.quiet)
        steps.append(
            {
                "name": "create_venv",
                "status": "pass" if rc == 0 else "fail",
                "detail": f"venv={venv_dir}",
            }
        )
        if rc != 0:
            report_payload = {
                "status": "fail",
                "created_at": created_at,
                "repo_root": str(repo_root),
                "venv": str(venv_dir),
                "steps": steps,
                "preflight": preflight,
            }
            json_path, md_path = _write_report(out_dir=out_dir, payload=report_payload)
            _emit("setup_status=fail", quiet=args.quiet)
            _emit(f"report_json={json_path}", quiet=args.quiet)
            _emit(f"report_md={md_path}", quiet=args.quiet)
            return rc
    else:
        steps.append({"name": "create_venv", "status": "pass", "detail": "existing venv reused"})

    pip_ready = _run([str(venv_python), "-m", "pip", "--version"], cwd=repo_root, quiet=True)
    if pip_ready == 0:
        steps.append({"name": "bootstrap_venv_pip", "status": "pass", "detail": "pip already available"})
    else:
        rc = _run([str(venv_python), "-m", "ensurepip", "--upgrade", "--default-pip"], cwd=repo_root, quiet=args.quiet)
        steps.append(
            {
                "name": "bootstrap_venv_pip",
                "status": "pass" if rc == 0 else "fail",
                "detail": f"{venv_python} -m ensurepip --upgrade --default-pip",
            }
        )
        if rc != 0:
            report_payload = {
                "status": "fail",
                "created_at": created_at,
                "repo_root": str(repo_root),
                "venv": str(venv_dir),
                "steps": steps,
                "preflight": preflight,
            }
            json_path, md_path = _write_report(out_dir=out_dir, payload=report_payload)
            _emit("setup_status=fail", quiet=args.quiet)
            _emit(f"report_json={json_path}", quiet=args.quiet)
            _emit(f"report_md={md_path}", quiet=args.quiet)
            return rc

    action_commands = [
        ("venv_pip_upgrade", [str(venv_python), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"]),
        ("venv_install_editable", [str(venv_python), "-m", "pip", "install", "-e", "."]),
        ("venv_install_pytest", [str(venv_python), "-m", "pip", "install", "pytest"]),
    ]
    if not args.skip_smoke:
        action_commands.append(
            ("smoke_test", [str(venv_python), "-m", "pytest", "-q", "tests/unit/test_config.py"])
        )

    for name, command in action_commands:
        rc = _run(command, cwd=repo_root, quiet=args.quiet)
        steps.append({"name": name, "status": "pass" if rc == 0 else "fail", "detail": " ".join(command)})
        if rc != 0:
            report_payload = {
                "status": "fail",
                "created_at": created_at,
                "repo_root": str(repo_root),
                "venv": str(venv_dir),
                "steps": steps,
                "preflight": preflight,
            }
            json_path, md_path = _write_report(out_dir=out_dir, payload=report_payload)
            _emit("setup_status=fail", quiet=args.quiet)
            _emit(f"report_json={json_path}", quiet=args.quiet)
            _emit(f"report_md={md_path}", quiet=args.quiet)
            return rc

    report_payload = {
        "status": "pass",
        "created_at": created_at,
        "repo_root": str(repo_root),
        "venv": str(venv_dir),
        "steps": steps,
        "preflight": preflight,
    }
    json_path, md_path = _write_report(out_dir=out_dir, payload=report_payload)
    _emit("setup_status=pass", quiet=args.quiet)
    _emit(f"venv_python={venv_python}", quiet=args.quiet)
    _emit(f"report_json={json_path}", quiet=args.quiet)
    _emit(f"report_md={md_path}", quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
