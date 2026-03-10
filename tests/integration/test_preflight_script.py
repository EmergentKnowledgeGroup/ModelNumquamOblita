from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_preflight_setup_mode_json_payload() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "tools/preflight.py",
            "--mode",
            "setup",
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "setup"
    assert payload["status"] in {"pass", "warn"}
    assert payload["failure_count"] == 0


def test_preflight_runtime_missing_memories_returns_actionable_failure(tmp_path: Path) -> None:
    missing_memories = tmp_path / "missing.sqlite3"
    result = subprocess.run(
        [
            sys.executable,
            "tools/preflight.py",
            "--mode",
            "runtime",
            "--memories",
            str(missing_memories),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    assert "preflight_status=fail" in result.stdout
    assert "memories_path" in result.stdout
    assert "Run import first" in result.stdout


def test_preflight_pilot_requires_input_even_with_memories(tmp_path: Path) -> None:
    memories = tmp_path / "memories.json"
    memories.write_text('{"ok": true}\n', encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "tools/preflight.py",
            "--mode",
            "pilot",
            "--memories",
            str(memories),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    assert "preflight_status=fail" in result.stdout
    assert "input_path" in result.stdout
    assert "Provide a conversations export path with --input" in result.stdout
