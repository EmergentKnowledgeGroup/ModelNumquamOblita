from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_run_setup_workspace_plan_only_prints_steps() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "tools/run_setup_workspace.py",
            "--plan-only",
            "--npm-cmd",
            sys.executable,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "step=setup_local" in result.stdout
    assert "step=desktop_install" in result.stdout
    assert "step=desktop_dev" in result.stdout
    assert "tools/run_setup_workspace.py" not in result.stdout
