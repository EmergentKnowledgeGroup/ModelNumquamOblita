from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from engine.continuity import ContinuityStore
from engine.memory import SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


@pytest.fixture(autouse=True)
def _integration_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", raising=False)


def _http(method: str, url: str, payload: dict, headers: dict[str, str]) -> tuple[int, dict]:
    request = Request(url, data=json.dumps(payload).encode("utf-8"), method=method, headers={"Content-Type": "application/json", **headers})
    try:
        with urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _envelope(data: dict, *, request_id: str, session_id: str = "temporal_session", run_id: str = "temporal_run") -> dict:
    return {
        "schema_version": "integration.v1",
        "request_id": request_id,
        "session_id": session_id,
        "run_id": run_id,
        "data": data,
    }


def test_v022_temporal_http_schedule_read_resolve_scope_and_heartbeat(tmp_path) -> None:
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    operator = {"Authorization": "Bearer local-integration-operator-token"}
    viewer = {"Authorization": "Bearer local-integration-viewer-token"}
    try:
        source_status, source = _http(
            "POST", f"{base}/api/integration/v1/memory/source/register",
            _envelope({"content": "Pay electricity bill next week.", "source_role": "user"}, request_id="req_TEMPORALSOURCE0001"), operator,
        )
        assert source_status == 200, source
        registration = source["data"]["source_registration"]

        schedule_data = {
            "temporal_request": {"relative_duration": {"amount": 1, "unit": "weeks"}, "timezone": "UTC"},
            "original_expression": "next week",
            "source_content": "Pay electricity bill next week.",
            "source_role": "user",
            "source_registration": registration,
            "temporal_kind": "reminder",
        }
        schedule_status, scheduled = _http(
            "POST", f"{base}/api/integration/v1/memory/temporal/schedule",
            _envelope(schedule_data, request_id="req_TEMPORALSCHEDULE01"), {**operator, "Idempotency-Key": "idem_temporal_schedule_1"},
        )
        assert schedule_status == 200, scheduled
        record_id = scheduled["data"]["record_id"]
        assert scheduled["data"]["revision"] == 1

        denied_status, denied = _http(
            "POST", f"{base}/api/integration/v1/memory/temporal/schedule",
            _envelope(schedule_data, request_id="req_TEMPORALSCHEDULE02"), {**viewer, "Idempotency-Key": "idem_temporal_schedule_2"},
        )
        assert denied_status == 403
        assert denied["error"]["code"] == "PERMISSION_DENIED"

        list_status, listed = _http(
            "POST", f"{base}/api/integration/v1/memory/temporal/list",
            _envelope({"due_only": True, "include_upcoming": False, "limit": 3}, request_id="req_TEMPORALLIST00001"), operator,
        )
        assert list_status == 200, listed
        assert listed["data"]["heartbeat"] is True
        assert listed["data"]["records"] == []

        get_status, fetched = _http(
            "POST", f"{base}/api/integration/v1/memory/temporal/get",
            _envelope({"record_id": record_id}, request_id="req_TEMPORALGET00001"), operator,
        )
        assert get_status == 200, fetched
        assert fetched["data"]["record"]["record_id"] == record_id
        assert fetched["data"]["record"]["temporal_revision"] == 1

        own_why_status, own_why = _http(
            "POST", f"{base}/api/integration/v1/context/why",
            _envelope({"evidence_ids": [record_id]}, request_id="req_TEMPORALWHY00000"), operator,
        )
        assert own_why_status == 200
        assert own_why["data"]["evidence"][0]["temporal"]["record"]["record_id"] == record_id

        cross_status, cross = _http(
            "POST", f"{base}/api/integration/v1/memory/temporal/get",
            _envelope({"record_id": record_id}, request_id="req_TEMPORALGET00002"), viewer,
        )
        assert cross_status == 404
        assert cross["error"]["message"] == "temporal record not found"

        why_status, why = _http(
            "POST", f"{base}/api/integration/v1/context/why",
            _envelope({"evidence_ids": [record_id]}, request_id="req_TEMPORALWHY00001"), viewer,
        )
        assert why_status == 200
        assert why["data"]["evidence"] == []
        assert "electricity" not in json.dumps(why)

        resolve_status, resolved = _http(
            "POST", f"{base}/api/integration/v1/memory/temporal/resolve",
            _envelope({"record_id": record_id, "action": "cancel", "expected_revision": 1}, request_id="req_TEMPORALRESOLVE1"),
            {**operator, "Idempotency-Key": "idem_temporal_resolve_1"},
        )
        assert resolve_status == 200, resolved
        assert resolved["data"]["disposition"] == "cancelled"
        assert resolved["data"]["revision"] == 2
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        store.close()


def test_v022_temporal_http_fails_closed_without_sqlite() -> None:
    from engine.memory import AtomStore

    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        status, payload = _http(
            "POST", f"{base}/api/integration/v1/memory/temporal/list",
            _envelope({"due_only": True, "include_upcoming": False, "limit": 3}, request_id="req_TEMPORALDURABLE1"),
            {"Authorization": "Bearer local-integration-viewer-token"},
        )
        assert status == 503
        assert payload["error"]["code"] == "TEMPORAL_DURABLE_STORE_REQUIRED"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
