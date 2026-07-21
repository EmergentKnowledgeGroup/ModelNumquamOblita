from __future__ import annotations

from pathlib import Path

import pytest

from tools import run_headless_curation as hcr


def test_hcr_host_is_loopback_only() -> None:
    assert hcr._is_loopback_host("127.0.0.1") is True
    assert hcr._is_loopback_host("127.12.34.56") is True
    assert hcr._is_loopback_host("::1") is True
    assert hcr._is_loopback_host("localhost") is True
    assert hcr._is_loopback_host("0.0.0.0") is False
    assert hcr._is_loopback_host("192.168.1.5") is False


def test_prepare_existing_store_creates_build_and_reads_hcr_status(tmp_path: Path) -> None:
    store = tmp_path / "atoms.sqlite3"
    store.write_bytes(b"sqlite")
    calls: list[tuple[str, str, dict | None]] = []

    def request(_base: str, path: str, *, method: str = "GET", payload: dict | None = None, **_kwargs):
        calls.append((method, path, payload))
        if path == "/api/wizard/start":
            return {"ok": True, "run_id": "wizard_hcr_1"}
        if path == "/api/wizard/import/validate":
            return {"ok": True, "is_valid": True, "status": "safe"}
        if path == "/api/wizard/import/run":
            return {"ok": True, "store_path": str(store)}
        if path == "/api/wizard/build/run":
            return {"ok": True, "build_info": {"build_id": "build_1"}}
        if path.startswith("/api/wizard/hcr/status?"):
            return {"schema": hcr.HCR_STATUS_SCHEMA, "run_id": "wizard_hcr_1", "state": "curation_required"}
        raise AssertionError(path)

    status = hcr._prepare_run(
        "http://127.0.0.1:7340",
        input_path=None,
        store_path=store,
        output_store=None,
        run_id="",
        policy_preset="strict",
        request_fn=request,
    )

    assert status["state"] == "curation_required"
    assert [path for _method, path, _payload in calls] == [
        "/api/wizard/start",
        "/api/wizard/import/validate",
        "/api/wizard/import/run",
        "/api/wizard/build/run",
        "/api/wizard/hcr/status?run_id=wizard_hcr_1",
    ]


def test_prepare_resume_fails_if_runtime_substitutes_a_different_run() -> None:
    def request(_base: str, _path: str, **_kwargs):
        return {"ok": True, "run_id": "wizard_wrong"}

    with pytest.raises(hcr.HeadlessCurationError, match="requested run"):
        hcr._prepare_run(
            "http://127.0.0.1:7340",
            input_path=None,
            store_path=None,
            output_store=None,
            run_id="wizard_expected",
            policy_preset="strict",
            request_fn=request,
        )

