from __future__ import annotations

import json
import os
from types import SimpleNamespace
from pathlib import Path

import pytest

from tools import hermes_adapter_installer as installer


class HermesRunner:
    def __init__(self) -> None:
        self.state = "neither"
        self.calls: list[list[str]] = []
        self.enabled: list[str] = []
        self.disabled: list[str] = []

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if command[1:] == ["--version"]:
            return SimpleNamespace(
                returncode=0,
                stdout="Hermes Agent v0.19.0 (2026.7.20) · upstream 588b7059\n",
                stderr="",
            )
        if command[1:4] == ["plugins", "list", "--json"]:
            rows = [] if self.state == "neither" else [{"name": installer.PLUGIN_NAME, "status": self.state}]
            return SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")
        if command[1:3] == ["plugins", "enable"]:
            self.state = "enabled"
            self.enabled = [*sorted(set(self.enabled) | {installer.PLUGIN_NAME})]
            self.disabled = [item for item in self.disabled if item != installer.PLUGIN_NAME]
        elif command[1:3] == ["plugins", "disable"]:
            self.state = "disabled"
            self.enabled = [item for item in self.enabled if item != installer.PLUGIN_NAME]
            self.disabled = [*sorted(set(self.disabled) | {installer.PLUGIN_NAME})]
        elif command[1:4] == ["config", "get", "plugins.disabled"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.disabled), stderr="")
        elif command[1:3] == ["config", "unset"]:
            key = command[3]
            if key.startswith("plugins.disabled."):
                self.disabled.pop(int(key.rsplit(".", 1)[1]))
                if installer.PLUGIN_NAME not in self.enabled and installer.PLUGIN_NAME not in self.disabled:
                    self.state = "neither"
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class FailingStateRunner(HermesRunner):
    def __init__(self, *, fail_action: str) -> None:
        super().__init__()
        self.fail_action = fail_action
        self.fail_enabled = False

    def __call__(self, command, **kwargs):
        if self.fail_enabled and command[1:3] == ["plugins", self.fail_action]:
            self.calls.append(list(command))
            return SimpleNamespace(returncode=1, stdout="", stderr="injected")
        return super().__call__(command, **kwargs)


def test_home_precedence_prefers_argument_then_environment_then_native_windows_default(tmp_path: Path) -> None:
    explicit = installer.resolve_hermes_home(tmp_path / "explicit", env={"HERMES_HOME": str(tmp_path / "env")})
    assert explicit == (tmp_path / "explicit").resolve()
    from_env = installer.resolve_hermes_home(None, env={"HERMES_HOME": str(tmp_path / "env")})
    assert from_env == (tmp_path / "env").resolve()
    native = installer.resolve_hermes_home(None, env={"LOCALAPPDATA": str(tmp_path / "local")}, platform="win32")
    assert native == (tmp_path / "local" / "hermes").resolve()


def test_version_parser_uses_product_version_not_build_date(tmp_path: Path) -> None:
    assert installer._hermes_version(tmp_path, runner=HermesRunner()) == "0.19.0"


def test_containment_rejects_escape_and_reparse_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "hermes"
    home.mkdir()
    with pytest.raises(installer.HermesInstallError, match="escapes"):
        installer._contained(home, tmp_path / "outside")

    linked = home / "linked"
    linked.mkdir()
    real_is_reparse = installer._is_reparse
    monkeypatch.setattr(
        installer,
        "_is_reparse",
        lambda path: path == linked or real_is_reparse(path),
    )
    with pytest.raises(installer.HermesInstallError, match="symlink, junction, or reparse"):
        installer._contained(home, linked / "plugin.yaml")


def _healthy_probe(_config, *, token: str) -> dict[str, object]:
    assert token
    return {
        "health": {"status": "ok"},
        "capabilities": {
            "operations": [
                {"name": name, "available": True, "authorized": name in installer.ALLOWED_OPERATIONS}
                for name in (*installer.ALLOWED_OPERATIONS, "writeback.resolve")
            ]
        },
    }


def test_install_records_hashes_and_uninstall_restores_prior_enabled_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    runner = HermesRunner()
    runner.state = "disabled"
    home = tmp_path / "hermes"
    result = installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "not-printed"})
    assert result["status"] == "installed"
    state = json.loads((home / "mno" / "install-state.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == installer.STATE_SCHEMA
    assert state["prior_plugin_state"] == "disabled"
    assert all(len(value) == 64 for value in state["owned_hashes"].values())
    assert len(state["credential_ownership_id"]) == 32
    assert len(state["owned_credential_sha256"]) == 64
    assert runner.state == "enabled"
    credential = json.loads((home / "mno" / "adapter-token").read_text(encoding="utf-8"))
    assert credential["token"] == "not-printed"
    doctor = installer.doctor(home=home, runner=runner, environ={})
    assert doctor["status"] == "healthy"
    assert doctor["credential_source"] == "credential_file"
    removed = installer.uninstall(home=home, runner=runner)
    assert removed["status"] == "uninstalled"
    assert runner.state == "disabled"
    assert not (home / "plugins" / installer.PLUGIN_NAME).exists()
    assert not (home / "mno" / "adapter-token").exists()


def test_install_and_uninstall_dry_run_are_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    runner = HermesRunner()
    home = tmp_path / "hermes"
    before = installer.install(
        home=home,
        runner=runner,
        dry_run=True,
        environ={installer.DEFAULT_TOKEN_ENV: "token"},
    )
    assert before["status"] == "dry_run"
    assert not (home / "plugins" / installer.PLUGIN_NAME).exists()
    assert runner.state == "neither"

    installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "token"})
    state_before = (home / "mno" / "install-state.json").read_bytes()
    plugin_before = (home / "plugins" / installer.PLUGIN_NAME / "adapter.py").read_bytes()
    calls_before = list(runner.calls)
    after = installer.uninstall(home=home, runner=runner, dry_run=True)
    assert after["status"] == "dry_run"
    assert (home / "mno" / "install-state.json").read_bytes() == state_before
    assert (home / "plugins" / installer.PLUGIN_NAME / "adapter.py").read_bytes() == plugin_before
    assert runner.calls == calls_before
    assert runner.state == "enabled"


def test_update_preserves_original_neither_state_and_uninstall_removes_tombstone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    runner = HermesRunner()
    home = tmp_path / "hermes"
    installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "not-printed"})
    installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "not-printed"})
    state = json.loads((home / "mno" / "install-state.json").read_text(encoding="utf-8"))
    assert state["prior_plugin_state"] == "neither"
    installer.uninstall(home=home, runner=runner)
    assert runner.state == "neither"
    assert installer.PLUGIN_NAME not in runner.enabled
    assert installer.PLUGIN_NAME not in runner.disabled


def test_install_refuses_unowned_or_modified_paths_unless_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    runner = HermesRunner()
    home = tmp_path / "hermes"
    unowned = home / "plugins" / installer.PLUGIN_NAME
    unowned.mkdir(parents=True)
    (unowned / "plugin.yaml").write_text("unowned", encoding="utf-8")
    with pytest.raises(installer.HermesInstallError, match="unowned"):
        installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "not-printed"})
    shutil_target = home / "plugins" / installer.PLUGIN_NAME
    for child in shutil_target.iterdir():
        child.unlink()
    shutil_target.rmdir()
    installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "not-printed"})
    (home / "plugins" / installer.PLUGIN_NAME / "adapter.py").write_text("changed", encoding="utf-8")
    with pytest.raises(installer.HermesInstallError, match="changed"):
        installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "not-printed"})
    installer.install(home=home, runner=runner, force=True, environ={installer.DEFAULT_TOKEN_ENV: "not-printed"})


def test_install_refuses_unowned_credential_file(tmp_path: Path) -> None:
    home = tmp_path / "hermes"
    token_path = home / "mno" / "adapter-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("somebody-elses-secret", encoding="utf-8")

    with pytest.raises(installer.HermesInstallError, match="unowned.*credential"):
        installer.install(
            home=home,
            runner=HermesRunner(),
            environ={installer.DEFAULT_TOKEN_ENV: "replacement"},
        )

    assert token_path.read_text(encoding="utf-8") == "somebody-elses-secret"


def test_update_and_uninstall_refuse_changed_owned_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    home = tmp_path / "hermes"
    runner = HermesRunner()
    env = {installer.DEFAULT_TOKEN_ENV: "original-token"}
    installer.install(home=home, runner=runner, environ=env)
    token_path = home / "mno" / "adapter-token"
    credential = json.loads(token_path.read_text(encoding="utf-8"))
    credential["token"] = "replaced-token"
    token_path.write_text(json.dumps(credential, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(installer.HermesInstallError, match="credential changed"):
        installer.install(home=home, runner=runner, environ=env)
    with pytest.raises(installer.HermesInstallError, match="credential changed"):
        installer.uninstall(home=home, runner=runner)

    assert json.loads(token_path.read_text(encoding="utf-8"))["token"] == "replaced-token"


def test_doctor_reports_credential_source_when_live_probe_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    home = tmp_path / "hermes"
    runner = HermesRunner()
    installer.install(
        home=home,
        runner=runner,
        environ={installer.DEFAULT_TOKEN_ENV: "token"},
    )
    monkeypatch.setattr(
        installer,
        "_live_probe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            installer.HermesProbeError("runtime_unavailable", "offline")
        ),
    )

    result = installer.doctor(home=home, runner=runner, environ={})

    assert result["status"] == "runtime_unavailable"
    assert result["credential_source"] == "credential_file"


@pytest.mark.skipif(os.name == "nt", reason="POSIX credential permissions")
def test_doctor_rejects_permissions_the_posix_plugin_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    home = tmp_path / "hermes"
    runner = HermesRunner()
    installer.install(
        home=home,
        runner=runner,
        environ={installer.DEFAULT_TOKEN_ENV: "token"},
    )
    (home / "mno" / "adapter-token").chmod(0o644)

    result = installer.doctor(home=home, runner=runner, environ={})

    assert result["status"] == "auth_missing"
    assert result["credential_source"] == "missing"


@pytest.mark.parametrize(
    "content",
    [
        b'{"schema_version":"wrong","ownership_id":"owner","token":"secret"}',
        b"\xff\xfe\x00",
    ],
)
def test_doctor_rejects_invalid_persisted_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    home = tmp_path / "hermes"
    runner = HermesRunner()
    installer.install(
        home=home,
        runner=runner,
        environ={installer.DEFAULT_TOKEN_ENV: "token"},
    )
    (home / "mno" / "adapter-token").write_bytes(content)

    result = installer.doctor(home=home, runner=runner, environ={})

    assert result["status"] == "auth_missing"
    assert result["credential_source"] == "missing"


def test_uninstall_failure_restores_owned_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    home = tmp_path / "hermes"
    runner = HermesRunner()
    installer.install(
        home=home,
        runner=runner,
        environ={installer.DEFAULT_TOKEN_ENV: "rollback-token"},
    )
    token_path = home / "mno" / "adapter-token"
    token_before = token_path.read_bytes()
    state_path = home / "mno" / "install-state.json"
    original_unlink = Path.unlink
    failed = False

    def fail_state_unlink(path: Path, *args, **kwargs):
        nonlocal failed
        if path == state_path and not failed:
            failed = True
            raise OSError("injected state deletion failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_state_unlink)

    with pytest.raises(OSError, match="injected"):
        installer.uninstall(home=home, runner=runner)

    assert token_path.read_bytes() == token_before
    assert runner.state == "enabled"


def test_token_value_is_never_an_installer_argument_and_doctor_is_health_capabilities_only(tmp_path: Path) -> None:
    parser = installer._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["install", "--token", "secret"])
    runner = HermesRunner()
    with pytest.raises(installer.HermesInstallError, match="required token environment variable"):
        installer.install(home=tmp_path / "hermes", runner=runner, environ={})


@pytest.mark.parametrize("probe_status", ["auth_denied", "runtime_unavailable", "contract_incompatible"])
def test_doctor_preserves_typed_live_probe_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe_status: str,
) -> None:
    runner = HermesRunner()
    home = tmp_path / "hermes"
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "token"})

    def fail_probe(*_args, **_kwargs):
        raise installer.HermesProbeError(probe_status, "injected")

    monkeypatch.setattr(installer, "_live_probe", fail_probe)
    result = installer.doctor(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "token"})
    assert result["status"] == probe_status


def test_install_reports_incomplete_state_rollback_without_hiding_original_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FailingStateRunner(fail_action="disable")
    runner.state = "disabled"

    def fail_probe(*_args, **_kwargs):
        runner.fail_enabled = True
        raise installer.HermesProbeError("runtime_unavailable", "install doctor failure")

    monkeypatch.setattr(installer, "_live_probe", fail_probe)
    with pytest.raises(installer.HermesInstallError, match="rollback incomplete"):
        installer.install(
            home=tmp_path / "hermes",
            runner=runner,
            environ={installer.DEFAULT_TOKEN_ENV: "token"},
        )


def test_uninstall_validates_backup_before_mutating_plugin_or_hermes_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    runner = HermesRunner()
    home = tmp_path / "hermes"
    installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "token"})
    state_path = home / "mno" / "install-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    backup = home / "mno" / "backups" / "mno-memory"
    backup.mkdir(parents=True, exist_ok=True)
    changed = backup / "changed.txt"
    changed.write_text("changed", encoding="utf-8")
    state["backup"] = {
        "path": backup.relative_to(home).as_posix(),
        "hashes": {changed.relative_to(home).as_posix(): "0" * 64},
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    calls_before = list(runner.calls)
    with pytest.raises(installer.HermesInstallError, match="backup changed"):
        installer.uninstall(home=home, runner=runner)
    assert runner.calls == calls_before
    assert runner.state == "enabled"
    assert (home / "plugins" / installer.PLUGIN_NAME / "adapter.py").is_file()


def test_uninstall_state_failure_leaves_files_and_state_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "_live_probe", _healthy_probe)
    runner = FailingStateRunner(fail_action="disable")
    runner.state = "disabled"
    home = tmp_path / "hermes"
    installer.install(home=home, runner=runner, environ={installer.DEFAULT_TOKEN_ENV: "token"})
    state_path = home / "mno" / "install-state.json"
    plugin_path = home / "plugins" / installer.PLUGIN_NAME / "adapter.py"
    state_before = state_path.read_bytes()
    plugin_before = plugin_path.read_bytes()

    runner.fail_enabled = True
    with pytest.raises(installer.HermesInstallError):
        installer.uninstall(home=home, runner=runner)

    assert state_path.read_bytes() == state_before
    assert plugin_path.read_bytes() == plugin_before
    assert runner.state == "enabled"
