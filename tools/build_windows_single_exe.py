#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_kv(key: str, value: str) -> None:
    print(f"{key}={value}")


def _build_command(
    *,
    exe_name: str,
    entrypoint: Path,
    dist_dir: Path,
    build_dir: Path,
    spec_dir: Path,
    onefile: bool,
) -> list[str]:
    data_sep = ";" if os.name == "nt" else ":"
    ui_source = REPO_ROOT / "engine" / "runtime" / "ui"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        exe_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(spec_dir),
        "--add-data",
        f"{ui_source}{data_sep}engine/runtime/ui",
    ]
    if bool(onefile):
        command.append("--onefile")
    command.append(str(entrypoint))
    return command


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Windows-friendly single-exe runtime package via PyInstaller."
    )
    parser.add_argument("--name", default="NumquamOblitaRuntime", help="Executable name")
    parser.add_argument(
        "--entrypoint",
        default=str(REPO_ROOT / "tools" / "run_live_runtime.py"),
        help="Python entrypoint to package",
    )
    parser.add_argument(
        "--out-root",
        default=str(REPO_ROOT / "runtime" / "packaging"),
        help="Root directory for packaging runs",
    )
    parser.add_argument(
        "--onefile",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Build a single-file executable",
    )
    parser.add_argument("--dry-run", action="store_true", help="Emit command + manifest without invoking PyInstaller")
    args = parser.parse_args()

    entrypoint = Path(args.entrypoint).expanduser().resolve()
    if not entrypoint.exists():
        print(f"error=entrypoint not found: {entrypoint}")
        return 2

    stamp = _utc_stamp()
    run_dir = Path(args.out_root).expanduser().resolve() / f"windows_{stamp}"
    build_dir = run_dir / "build"
    dist_dir = run_dir / "dist"
    spec_dir = run_dir / "spec"
    logs_dir = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    command = _build_command(
        exe_name=str(args.name),
        entrypoint=entrypoint,
        dist_dir=dist_dir,
        build_dir=build_dir,
        spec_dir=spec_dir,
        onefile=bool(args.onefile),
    )
    command_text = " ".join(command)

    manifest_path = run_dir / "packaging_manifest.json"
    log_path = logs_dir / "pyinstaller.log"
    exe_filename = f"{args.name}.exe" if os.name == "nt" else str(args.name)
    expected_exe = (
        dist_dir / exe_filename
        if bool(args.onefile)
        else dist_dir / str(args.name) / exe_filename
    )
    manifest = {
        "schema": "numquamoblita.packaging.windows.v1",
        "generated_at": _utc_iso(),
        "run_dir": str(run_dir),
        "entrypoint": str(entrypoint),
        "command": command,
        "command_text": command_text,
        "onefile": bool(args.onefile),
        "log_path": str(log_path),
        "expected_executable": str(expected_exe),
        "status": "pending",
    }

    if bool(args.dry_run):
        manifest["status"] = "dry_run"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        _emit_kv("status", "dry_run")
        _emit_kv("run_dir", str(run_dir))
        _emit_kv("packaging_manifest_json", str(manifest_path))
        _emit_kv("expected_executable", str(expected_exe))
        _emit_kv("build_command", command_text)
        return 0

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"[{_utc_iso()}] command={command_text}\n")
        log_file.flush()
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.stdout:
            log_file.write(completed.stdout)
        if completed.stderr:
            log_file.write("\n[stderr]\n")
            log_file.write(completed.stderr)

    manifest["exit_code"] = int(completed.returncode)
    manifest["status"] = "success" if completed.returncode == 0 else "failed"
    manifest["executable_exists"] = bool(expected_exe.exists())
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    _emit_kv("status", str(manifest["status"]))
    _emit_kv("run_dir", str(run_dir))
    _emit_kv("packaging_manifest_json", str(manifest_path))
    _emit_kv("pyinstaller_log", str(log_path))
    _emit_kv("expected_executable", str(expected_exe))
    _emit_kv("build_command", command_text)
    if completed.returncode != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
