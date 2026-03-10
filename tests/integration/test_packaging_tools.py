from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_kv(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in str(stdout or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned = key.strip()
        if not cleaned:
            continue
        out[cleaned] = value.strip()
    return out


def test_build_windows_single_exe_dry_run(tmp_path: Path) -> None:
    out_root = tmp_path / "packaging"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_windows_single_exe.py",
            "--dry-run",
            "--out-root",
            str(out_root),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    kv = _parse_kv(result.stdout)
    assert str(kv.get("status") or "") == "dry_run"
    manifest_path = Path(str(kv.get("packaging_manifest_json") or ""))
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert str(payload.get("schema") or "") == "numquamoblita.packaging.windows.v1"
    assert str(payload.get("status") or "") == "dry_run"
    assert str(payload.get("expected_executable") or "").strip()
    assert str(payload.get("command_text") or "").strip()
