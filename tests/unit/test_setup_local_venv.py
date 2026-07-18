from __future__ import annotations

from pathlib import Path
import subprocess

from tools import setup_local


def test_quarantine_unhealthy_venv_moves_bootstrap_broken_environment(tmp_path, monkeypatch) -> None:
    venv_dir = tmp_path / ".venv"
    target_python = setup_local._venv_python(venv_dir)
    target_python.parent.mkdir(parents=True)
    target_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    monkeypatch.setattr(
        setup_local,
        "_discover_python_version",
        lambda _python_cmd: (None, "ImportError: broken pyexpat"),
    )

    quarantined, detail = setup_local._quarantine_unhealthy_venv(venv_dir, min_python="3.12")

    assert quarantined is not None
    assert quarantined.exists()
    assert not venv_dir.exists()
    assert detail == "ImportError: broken pyexpat"


def test_quarantine_unhealthy_venv_keeps_healthy_environment(tmp_path, monkeypatch) -> None:
    venv_dir = tmp_path / ".venv"
    target_python = setup_local._venv_python(venv_dir)
    target_python.parent.mkdir(parents=True)
    target_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    monkeypatch.setattr(
        setup_local,
        "_discover_python_version",
        lambda _python_cmd: ((3, 14), ""),
    )

    quarantined, detail = setup_local._quarantine_unhealthy_venv(venv_dir, min_python="3.12")

    assert quarantined is None
    assert detail == ""
    assert venv_dir.exists()


def test_create_venv_uses_uv_seed_when_interpreter_has_no_ensurepip(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []
    interpreter = tmp_path / "managed" / "python"
    monkeypatch.setattr(setup_local, "shutil_which", lambda tool: "/usr/bin/uv" if tool == "uv" else None)
    monkeypatch.setattr(
        setup_local.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout=str(interpreter) + "\n", stderr=""),
    )
    monkeypatch.setattr(setup_local, "_run", lambda command, **_kwargs: calls.append(command) or 0)

    result = setup_local._create_venv(
        python_argv=["py", "-3.12"],
        venv_dir=tmp_path / ".venv",
        repo_root=tmp_path,
        quiet=True,
    )

    assert result == 0
    assert calls == [["/usr/bin/uv", "venv", "--seed", "--python", str(interpreter), str(tmp_path / ".venv")]]
