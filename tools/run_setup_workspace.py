#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.preflight import _discover_python_version, find_supported_python_argv, python_command_argv, python_command_display


def _default_python() -> str:
    current_version, _ = _discover_python_version((sys.executable,))
    if current_version is not None and current_version >= (3, 12):
        return python_command_display((sys.executable,))
    override = str(os.environ.get("MNO_PYTHON") or "").strip()
    discovered = find_supported_python_argv(
        candidates=tuple(item for item in (override, (sys.executable,), ("py", "-3.15"), ("py", "-3.14"), ("py", "-3.13"), ("py", "-3.12"), "python3.15", "python3.14", "python3.13", "python3.12", "/usr/bin/python3", "python3", "python") if item),
        min_python="3.12",
    )
    return python_command_display(discovered or (sys.executable or "python3",))


def _resolve_npm(*, target_os: str, which=shutil.which) -> str:
    candidates = ("npm.cmd", "npm") if target_os == "nt" else ("npm",)
    for candidate in candidates:
        resolved = which(candidate)
        if not resolved:
            continue
        normalized = resolved.replace("\\", "/").lower()
        if target_os != "nt" and (normalized.endswith((".cmd", ".bat", ".exe")) or normalized.startswith("/mnt/c/")):
            continue
        return resolved
    return ""


def _default_npm() -> str:
    return _resolve_npm(target_os=os.name)


def _run(command: list[str], *, cwd: Path, plan_only: bool) -> int:
    print("cmd=" + " ".join(command))
    if plan_only:
        return 0
    proc = subprocess.run(command, cwd=cwd, check=False)
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare local dependencies and open the MNO setup workspace.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--python-cmd", default="")
    parser.add_argument("--npm-cmd", default=_default_npm())
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-setup", action="store_true")
    parser.add_argument("--skip-desktop-install", action="store_true")
    args = parser.parse_args()
    args.python_cmd = str(args.python_cmd or _default_python())
    python_argv = list(python_command_argv(args.python_cmd))

    repo_root = Path(args.repo_root).expanduser().resolve()
    desktop_root = repo_root / "app" / "desktop"

    if not repo_root.exists():
        print(f"error=repo root not found: {repo_root}")
        return 2
    if not desktop_root.exists():
        print(f"error=desktop root not found: {desktop_root}")
        return 2
    if not args.skip_setup and (not python_argv or (not shutil.which(python_argv[0]) and not Path(python_argv[0]).exists())):
        print(f"error=python command not found: {args.python_cmd}")
        return 2
    if not str(args.npm_cmd).strip() or (not shutil.which(str(args.npm_cmd)) and not Path(str(args.npm_cmd)).exists()):
        target = "Windows" if os.name == "nt" else "Linux/WSL"
        print(f"error={target}-native npm command not found; refusing a cross-environment npm shim")
        return 2

    commands: list[tuple[str, list[str], Path]] = []
    if not args.skip_setup:
        commands.append(("setup_local", [*python_argv, str(repo_root / "tools" / "setup_local.py")], repo_root))
    if not args.skip_desktop_install:
        commands.append(("desktop_install", [str(args.npm_cmd), "install", "--prefix", str(desktop_root)], repo_root))
    commands.append(("desktop_dev", [str(args.npm_cmd), "run", "desktop:dev", "--prefix", str(desktop_root)], repo_root))

    for name, command, cwd in commands:
        print(f"step={name}")
        rc = _run(command, cwd=cwd, plan_only=bool(args.plan_only))
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
