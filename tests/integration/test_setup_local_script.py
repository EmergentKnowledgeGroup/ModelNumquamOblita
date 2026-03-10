from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_setup_local_plan_only_prints_steps() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "tools/setup_local.py",
            "--plan-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "mode=plan_only" in result.stdout
    assert "plan_step=" in result.stdout
    assert "report_json=" in result.stdout
    assert "report_md=" in result.stdout


def test_setup_local_preflight_only_succeeds() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "tools/setup_local.py",
            "--preflight-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "mode=preflight_only" in result.stdout
    assert "report_json=" in result.stdout
    assert "report_md=" in result.stdout


def test_setup_local_rejects_venv_outside_repo() -> None:
    outside_venv = (Path(tempfile.gettempdir()) / "numquamoblita-outside").resolve()
    result = subprocess.run(
        [
            sys.executable,
            "tools/setup_local.py",
            "--plan-only",
            "--venv",
            str(outside_venv),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    assert "error=--venv must resolve under repo root" in result.stdout
