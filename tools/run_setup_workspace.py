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

from tools.preflight import find_supported_python_command


def _default_python() -> str:
    if os.name == "nt" and shutil.which("py"):
        return "py"
    discovered = find_supported_python_command(
        candidates=("python3.15", "python3.14", "python3.13", "python3.12", "python3", "python", sys.executable),
        min_python="3.12",
    )
    if discovered:
        return discovered
    return sys.executable or "python3"


def _default_npm() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm"


def _run(command: list[str], *, cwd: Path, plan_only: bool) -> int:
    print("cmd=" + " ".join(command))
    if plan_only:
        return 0
    proc = subprocess.run(command, cwd=cwd, check=False)
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare local dependencies and open the MNO setup workspace.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--python-cmd", default=_default_python())
    parser.add_argument("--npm-cmd", default=_default_npm())
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-setup", action="store_true")
    parser.add_argument("--skip-desktop-install", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    desktop_root = repo_root / "app" / "desktop"

    if not repo_root.exists():
        print(f"error=repo root not found: {repo_root}")
        return 2
    if not desktop_root.exists():
        print(f"error=desktop root not found: {desktop_root}")
        return 2
    if not args.skip_setup and not shutil.which(str(args.python_cmd)) and not Path(str(args.python_cmd)).exists():
        print(f"error=python command not found: {args.python_cmd}")
        return 2
    if not shutil.which(str(args.npm_cmd)) and not Path(str(args.npm_cmd)).exists():
        print(f"error=npm command not found: {args.npm_cmd}")
        return 2

    commands: list[tuple[str, list[str], Path]] = []
    if not args.skip_setup:
        commands.append(("setup_local", [str(args.python_cmd), str(repo_root / "tools" / "setup_local.py")], repo_root))
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
