from __future__ import annotations

from tools import run_setup_workspace


def test_wsl_npm_resolution_rejects_windows_cmd_shim() -> None:
    def fake_which(command: str) -> str | None:
        assert command == "npm"
        return "/mnt/c/Program Files/nodejs/npm.cmd"

    assert run_setup_workspace._resolve_npm(target_os="posix", which=fake_which) == ""


def test_windows_npm_resolution_accepts_native_cmd() -> None:
    assert run_setup_workspace._resolve_npm(
        target_os="nt",
        which=lambda command: r"C:\Program Files\nodejs\npm.cmd" if command == "npm.cmd" else None,
    ).endswith("npm.cmd")
