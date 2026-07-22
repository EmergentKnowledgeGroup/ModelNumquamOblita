from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "run_headless_curation_mcp.py"


def test_headless_curation_launcher_plan_is_run_bound_and_non_mutating() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--runtime-base-url",
            "http://127.0.0.1:7340",
            "--run-id",
            "wizard_bound_123",
            "--plan-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "run_id=wizard_bound_123" in result.stdout
    assert "tool_profile=headless_curation" in result.stdout
    assert "mutations_enabled=true" in result.stdout


def test_headless_curation_launcher_rejects_unauthenticated_http() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--runtime-base-url",
            "http://127.0.0.1:7340",
            "--run-id",
            "wizard_bound_123",
            "--transport",
            "http",
            "--plan-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "requires at least one auth token" in result.stderr


def test_headless_curation_launcher_rejects_non_loopback_runtime() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--runtime-base-url",
            "http://192.168.1.50:7340",
            "--run-id",
            "wizard_bound_123",
            "--plan-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "loopback-only" in result.stderr

