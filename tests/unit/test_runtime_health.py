from types import SimpleNamespace

from engine.runtime import server as runtime_server


class _FakeStore:
    def list_atoms(self):
        return []


class _FakeAdapters:
    def names(self):
        return []


class _FakeRuntime:
    def __init__(self):
        self.retriever = SimpleNamespace(store=_FakeStore())
        self._episode_index = SimpleNamespace(cards=[])


def test_runtime_health_uses_runtime_state_root_for_disk_usage(monkeypatch, tmp_path):
    calls: list[str] = []
    runtime_root = (tmp_path / 'runtime_state').resolve()
    diagnostics_root = (tmp_path / 'diagnostics').resolve()

    def fake_disk_usage(target: str):
        calls.append(target)
        return SimpleNamespace(total=10 * 1024**3, used=1 * 1024**3, free=9 * 1024**3)

    monkeypatch.setattr(runtime_server.shutil, 'disk_usage', fake_disk_usage)
    monkeypatch.setattr(runtime_server, 'DIAGNOSTICS_ROOT', diagnostics_root)

    server = SimpleNamespace(
        runtime=_FakeRuntime(),
        adapter_registry=_FakeAdapters(),
        server_address=('127.0.0.1', 7340),
        runtime_version='0.1.0',
        runtime_launch_mode='normal',
        active_runtime_binding={},
        writeback_policy={},
        runtime_root=str(runtime_root),
    )

    payload = runtime_server._runtime_health(server)

    assert payload['service'] == 'modelnumquamoblita-runtime'
    assert calls == [str(runtime_root)]
