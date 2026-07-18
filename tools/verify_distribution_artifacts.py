#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


RUNTIME_SKELETON_FILES = {
    "runtime/README.md",
    "runtime/desktop_shell/.gitkeep",
    "runtime/diagnostics/.gitkeep",
    "runtime/episodes/.gitkeep",
    "runtime/imports/.gitkeep",
    "runtime/live_runs/.gitkeep",
    "runtime/packaging/.gitkeep",
    "runtime/reports/.gitkeep",
    "runtime/setup/.gitkeep",
    "runtime/state/.gitkeep",
    "runtime/stores/.gitkeep",
    "runtime/tmp/.gitkeep",
    "runtime/wizard_runs/.gitkeep",
}
FORBIDDEN_SUFFIXES = (
    ".sqlite3", ".sqlite3-wal", ".sqlite3-shm",
    ".sqlite", ".sqlite-wal", ".sqlite-shm",
    ".db", ".db-wal", ".db-shm",
)


def _artifact(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {pattern} artifact, found: {matches}")
    return matches[0]


def _normalized_sdist_members(path: Path) -> set[str]:
    with tarfile.open(path, "r:gz") as archive:
        raw = [PurePosixPath(item.name) for item in archive.getmembers() if item.isfile()]
    roots = {parts.parts[0] for parts in raw if parts.parts}
    if len(roots) != 1:
        raise AssertionError(f"sdist must have one root directory, found: {sorted(roots)}")
    root = next(iter(roots))
    return {PurePosixPath(*item.parts[1:]).as_posix() for item in raw if item.parts and item.parts[0] == root}


def _assert_no_private_paths(names: set[str], *, artifact: str) -> None:
    for name in names:
        lowered = name.lower()
        if lowered.endswith(FORBIDDEN_SUFFIXES):
            raise AssertionError(f"{artifact} contains SQLite state: {name}")
        if any(part in {"checkpoints", "wizard_uploads", "research_clones", "external"} for part in PurePosixPath(lowered).parts):
            raise AssertionError(f"{artifact} contains private/generated path: {name}")


def verify_manifests(dist_dir: Path) -> tuple[Path, Path]:
    wheel = _artifact(dist_dir, "*.whl")
    sdist = _artifact(dist_dir, "*.tar.gz")
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
        entry_points_name = next((name for name in wheel_names if name.endswith(".dist-info/entry_points.txt")), "")
        if not entry_points_name:
            raise AssertionError("wheel has no console entry-point metadata")
        entry_points = archive.read(entry_points_name).decode("utf-8")
    required_wheel = {
        "engine/runtime/ui/index.html",
        "engine/runtime/ui/app.js",
        "engine/runtime/ui/styles.css",
        "engine/runtime/resources/QUICKSTART.md",
        "tools/run_live_runtime.py",
        "tools/run_mcp_server.py",
        "tools/run_claude_live_mcp.py",
        "tools/import_memories.py",
        "tools/setup_local.py",
        "tools/report_issue.py",
    }
    missing_wheel = sorted(required_wheel - wheel_names)
    if missing_wheel:
        raise AssertionError(f"wheel missing runnable product files: {missing_wheel}")
    for script in ("mno-runtime", "mno-mcp", "mno-agent-mcp", "mno-setup", "mno-import", "mno-report"):
        if f"{script} = " not in entry_points:
            raise AssertionError(f"wheel missing console entry point: {script}")
    _assert_no_private_paths(wheel_names, artifact="wheel")

    sdist_names = _normalized_sdist_members(sdist)
    required_sdist = {
        "README.md",
        "LLMS.md",
        "app/desktop/package.json",
        "docs/QUICKSTART.md",
        "tests/unit/test_pyproject_packaging.py",
        "tools/run_live_runtime.py",
        "launch_setup_workspace.ps1",
        *RUNTIME_SKELETON_FILES,
    }
    missing_sdist = sorted(required_sdist - sdist_names)
    if missing_sdist:
        raise AssertionError(f"sdist missing public source files: {missing_sdist}")
    runtime_members = {name for name in sdist_names if name.startswith("runtime/")}
    unexpected_runtime = sorted(runtime_members - RUNTIME_SKELETON_FILES)
    if unexpected_runtime:
        raise AssertionError(f"sdist contains non-skeleton runtime files: {unexpected_runtime[:20]}")
    _assert_no_private_paths(sdist_names, artifact="sdist")
    return wheel, sdist


def verify_isolated_wheel(wheel: Path, *, work_root: Path) -> dict[str, object]:
    install_root = work_root / "wheel-target"
    profile_root = work_root / "fresh-profile"
    install_root.mkdir(parents=True, exist_ok=True)
    profile_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--target", str(install_root), str(wheel)],
        check=True,
        cwd=work_root,
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(install_root),
        "HOME": str(profile_root),
        "USERPROFILE": str(profile_root),
        "LOCALAPPDATA": str(profile_root / "local-app-data"),
        "APPDATA": str(profile_root / "app-data"),
        "XDG_STATE_HOME": str(profile_root / "xdg-state"),
    }
    env.pop("MNO_RUNTIME_STATE_ROOT", None)
    probe = f"""
import sys
sys.path.insert(0, {str(install_root)!r})
import json
from pathlib import Path
from engine.runtime import server
payload = {{
    'version': server._project_version(),
    'ui': (server.UI_ROOT / 'index.html').is_file(),
    'guide': server.PACKAGING_GUIDE_PATH.is_file(),
    'runtime_root': str(server.RUNTIME_ROOT),
    'install_root': str(Path(__import__('engine').__file__).resolve().parents[1]),
}}
print(json.dumps(payload))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe],
        check=True,
        cwd=profile_root,
        env=env,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if payload["version"] != "0.2.1":
        raise AssertionError(f"installed wheel reports wrong release version: {payload}")
    if not payload["ui"] or not payload["guide"]:
        raise AssertionError(f"installed wheel assets unavailable: {payload}")
    runtime_root = Path(str(payload["runtime_root"])).resolve()
    installed_root = Path(str(payload["install_root"])).resolve()
    if runtime_root == installed_root or installed_root in runtime_root.parents:
        raise AssertionError(f"mutable runtime state is inside installation: {payload}")
    for module in (
        "tools.run_live_runtime",
        "tools.run_mcp_server",
        "tools.setup_local",
        "tools.import_memories",
        "tools.report_issue",
    ):
        module_probe = (
            "import runpy,sys;"
            f"sys.path.insert(0,{str(install_root)!r});"
            f"sys.argv=[{module!r},'--help'];"
            f"runpy.run_module({module!r},run_name='__main__')"
        )
        subprocess.run(
            [sys.executable, "-I", "-S", "-c", module_probe],
            check=True,
            cwd=profile_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    report_root = profile_root / "support-ticket-proof"
    report_probe = (
        "import runpy,sys;"
        f"sys.path.insert(0,{str(install_root)!r});"
        "sys.argv=['mno-report','--title','Artifact smoke','--summary','Installed command proof',"
        "'--steps','Run installed mno-report','--expected','A passing package-native smoke check',"
        "'--actual','Command completed','--check','quick','--output-dir',"
        f"{str(report_root)!r}];"
        "runpy.run_module('tools.report_issue',run_name='__main__')"
    )
    subprocess.run(
        [sys.executable, "-I", "-S", "-c", report_probe],
        check=True,
        cwd=profile_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    tickets = sorted(report_root.glob("ticket_*/ticket.json"))
    if len(tickets) != 1:
        raise AssertionError(f"installed mno-report did not create exactly one ticket: {tickets}")
    ticket = json.loads(tickets[0].read_text(encoding="utf-8"))
    checks = list(ticket.get("checks") or [])
    if len(checks) != 1 or checks[0].get("status") != "passed":
        raise AssertionError(f"installed mno-report quick check failed: {checks}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify MNO wheel/sdist contents and isolated installed behavior.")
    parser.add_argument("--dist-dir", required=True)
    parser.add_argument("--work-root", default="")
    args = parser.parse_args()
    dist_dir = Path(args.dist_dir).expanduser().resolve()
    wheel, sdist = verify_manifests(dist_dir)
    if args.work_root:
        work_root = Path(args.work_root).expanduser().resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        payload = verify_isolated_wheel(wheel, work_root=work_root)
    else:
        with tempfile.TemporaryDirectory(prefix="mno-artifact-proof-") as temp_dir:
            payload = verify_isolated_wheel(wheel, work_root=Path(temp_dir))
    print(json.dumps({"ok": True, "wheel": wheel.name, "sdist": sdist.name, "installed": payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
