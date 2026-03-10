from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_audit_standalone_boundary_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "tools/audit_standalone_boundary.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = json.loads(result.stdout)
    assert str(payload.get("decision") or "") == "PASS"
    assert list(payload.get("failures") or []) == []
