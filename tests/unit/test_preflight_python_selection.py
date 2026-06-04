from __future__ import annotations

import subprocess

from tools import preflight


def _completed_process(args: list[str], *, returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def test_find_supported_python_command_skips_broken_higher_version(monkeypatch) -> None:
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda tool: f"/fake/{tool}" if tool in {"python3.13", "python3.12", "python3"} else None,
    )

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        executable = command[0]
        if executable == "python3.13":
            return _completed_process(command, returncode=1, stderr="ImportError: broken pyexpat")
        if executable == "python3":
            return _completed_process(command, returncode=0, stdout="3.14\n")
        if executable == "python3.12":
            return _completed_process(command, returncode=0, stdout="3.12\n")
        return _completed_process(command, returncode=1, stderr="not found")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    selected = preflight.find_supported_python_command(
        candidates=("python3.13", "python3.12", "python3"),
        min_python="3.12",
    )

    assert selected == "python3"


def test_python_check_reports_explicit_candidate_probe_failure(monkeypatch) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda tool: f"/fake/{tool}" if tool == "python3.13" else None)
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda command, **_kwargs: _completed_process(command, returncode=1, stderr="ImportError: broken pyexpat"),
    )

    result = preflight._python_check("3.12", python_cmd="python3.13")

    assert result.status == "fail"
    assert "unable to validate bootstrap readiness for python3.13" in result.detail
