from __future__ import annotations

from pathlib import Path

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
