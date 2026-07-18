from __future__ import annotations

import subprocess

import pytest

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


def test_python_discovery_preserves_launcher_arguments_and_does_not_require_ensurepip(monkeypatch) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda tool: f"/fake/{tool}" if tool == "py" else None)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return _completed_process(command, returncode=0, stdout="3.12\n")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    selected = preflight.find_supported_python_argv(candidates=(("py", "-3.12"),), min_python="3.12")

    assert selected == ("py", "-3.12")
    assert calls[0][:2] == ["py", "-3.12"]
    assert "ensurepip" not in calls[0][-1]


def test_python_command_argv_expands_home_only_on_executable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = str(tmp_path / "My Python" / "python3")
    assert preflight.python_command_argv("'~/My Python/python3' --flag=~/literal") == (
        expected,
        "--flag=~/literal",
    )
    assert preflight.python_command_argv(("~/My Python/python3", "~/literal")) == (
        expected,
        "~/literal",
    )


def test_default_memories_prefers_runtime_and_warns_when_legacy_also_exists(tmp_path) -> None:
    canonical = tmp_path / "runtime" / "imports"
    legacy = tmp_path / ".runtime" / "imports"
    canonical.mkdir(parents=True)
    legacy.mkdir(parents=True)
    (canonical / "atoms.sqlite3").write_text("canonical", encoding="utf-8")
    (legacy / "atoms.sqlite3").write_text("legacy", encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="using canonical"):
        selected = preflight._default_memories(tmp_path)
    assert selected == canonical / "atoms.sqlite3"
