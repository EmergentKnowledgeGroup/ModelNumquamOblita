from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import pytest

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.mcp.server import AuthConfig, MCPServer, RuntimeApiClient, ServerConfig
from engine.memory import AtomStore, MutationReviewQueue
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


@pytest.fixture(autouse=True)
def _enable_default_integration_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", "1")
    monkeypatch.delenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", raising=False)


def _candidate(candidate_id: str, text: str, source_id: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_msg",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user"],
        topics=["integration"],
        confidence=0.88,
        salience=0.7,
    )


def _http_json(
    *,
    method: str,
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme}")
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=body, method=method.upper(), headers=request_headers)
    try:
        with urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _mcp_call(server: MCPServer, request_id: int, method: str, params: dict | None = None) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }
    return server.handle_request(payload)


def _normalize_parity_payload(payload: dict) -> dict:
    normalized = json.loads(json.dumps(payload))
    data = normalized.get("data")
    if isinstance(data, dict):
        data.pop("uptime_ms", None)
    if isinstance(normalized.get("warnings"), list):
        normalized["warnings"] = list(normalized["warnings"])
    return normalized


def test_integration_http_contract_idempotency_and_resolve_noop() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("cand_1", "User prefers tea before bed.", "conv_tea"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    review_queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=review_queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    operator_headers = {"Authorization": "Bearer local-integration-operator-token"}

    try:
        started_status, started = _http_json(method="POST", url=f"{base}/api/chat/session/start", payload={"label": "integration"})
        assert started_status == 200
        session_id = str(started["session"]["session_id"])
        run_id = "run_integration_001"

        context_request = {
            "schema_version": "integration.v1",
            "request_id": "req_CONTEXTBUILD123456",
            "session_id": session_id,
            "run_id": run_id,
            "data": {
                "message": "What do you remember about tea preference?",
                "retrieval": {"top_k": 5},
                "risk_signal": "medium",
            },
        }
        context_status, context_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/context/build",
            payload=context_request,
            headers=operator_headers,
        )
        assert context_status == 200
        assert context_payload["ok"] is True
        assert context_payload["operation"] == "context.build"
        assert context_payload["request_id_source"] == "client"
        assert isinstance(context_payload["data"]["context_text"], str)
        assert isinstance(context_payload["data"]["evidence"], list)

        missing_auth_status, missing_auth = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/context/build",
            payload=context_request,
            headers={},
        )
        assert missing_auth_status == 401
        assert missing_auth["ok"] is False
        assert missing_auth["error"]["code"] == "AUTH_REQUIRED"

        propose_request = {
            "schema_version": "integration.v1",
            "request_id": "req_PROPOSE1234567890",
            "session_id": session_id,
            "run_id": run_id,
            "data": {
                "mutation": {
                    "intent": "create",
                    "target_kind": "fact_card",
                    "body": {"canonical_text": "User prefers tea before bedtime."},
                    "tags": ["tea", "preference"],
                },
                "evidence": [
                    {
                        "provenance_handle": "prov_1",
                        "source_kind": "conversation",
                        "source_id": "conv_tea",
                        "excerpt": "I usually prefer tea before bed.",
                        "citation": {"type": "message", "ref": "conv_tea#m1"},
                        "confidence": 0.81,
                    }
                ],
            },
        }
        propose_headers = {
            **operator_headers,
            "Idempotency-Key": "idem_integration_001",
        }
        first_status, first_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/propose",
            payload=propose_request,
            headers=propose_headers,
        )
        assert first_status == 200
        assert first_payload["ok"] is True
        assert first_payload["data"]["idempotent_replay"] is False
        proposal_id = str(first_payload["data"]["proposal_id"])

        replay_status, replay_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/propose",
            payload=propose_request,
            headers=propose_headers,
        )
        assert replay_status == 200
        assert replay_payload["ok"] is True
        assert replay_payload["data"]["idempotent_replay"] is True
        assert replay_payload["data"]["proposal_id"] == proposal_id

        mismatch_request = json.loads(json.dumps(propose_request))
        mismatch_request["data"]["mutation"]["body"]["canonical_text"] = "Conflicting writeback body"
        mismatch_status, mismatch_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/propose",
            payload=mismatch_request,
            headers=propose_headers,
        )
        assert mismatch_status == 409
        assert mismatch_payload["ok"] is False
        assert mismatch_payload["error"]["code"] == "INVALID_INPUT"

        resolve_request = {
            "schema_version": "integration.v1",
            "request_id": "req_RESOLVE1234567890",
            "session_id": session_id,
            "data": {
                "proposal_id": proposal_id,
                "decision": "approve",
                "decided_by": "operator_1",
                "reason": "approved",
            },
        }
        resolve_status, resolve_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/resolve",
            payload=resolve_request,
            headers=operator_headers,
        )
        assert resolve_status == 200
        assert resolve_payload["ok"] is True
        assert resolve_payload["data"]["already_resolved"] is False
        assert resolve_payload["data"]["status"] == "approved"

        resolve_again_status, resolve_again = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/resolve",
            payload=resolve_request,
            headers=operator_headers,
        )
        assert resolve_again_status == 200
        assert resolve_again["ok"] is True
        assert resolve_again["data"]["already_resolved"] is True
        assert resolve_again["data"]["status"] == "approved"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_integration_mcp_parity_and_domain_error_passthrough() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("cand_1", "Tea preference captured.", "conv_tea"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    review_queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=review_queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    viewer_headers = {"Authorization": "Bearer local-integration-viewer-token"}

    try:
        request_id = "req_PARITY1234567890"
        query = urlencode({"schema_version": "integration.v1", "request_id": request_id})
        http_status, http_payload = _http_json(
            method="GET",
            url=f"{base}/api/integration/v1/capabilities?{query}",
            headers=viewer_headers,
        )
        assert http_status == 200

        viewer_mcp = MCPServer(
            config=ServerConfig(
                runtime_base_url=base,
                auth=AuthConfig(default_role="viewer"),
            ),
            api_client=RuntimeApiClient(base_url=base),
        )
        init_viewer = _mcp_call(viewer_mcp, 1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        assert "error" not in init_viewer
        mcp_caps = _mcp_call(
            viewer_mcp,
            2,
            "tools/call",
            {"name": "integration.capabilities.get", "arguments": {"request_id": request_id}},
        )
        assert "error" not in mcp_caps
        mcp_payload = dict(mcp_caps["result"]["structuredContent"])
        assert _normalize_parity_payload(mcp_payload) == _normalize_parity_payload(http_payload)

        operator_mcp = MCPServer(
            config=ServerConfig(
                runtime_base_url=base,
                auth=AuthConfig(default_role="viewer", operator_token="mcp_operator"),
            ),
            api_client=RuntimeApiClient(base_url=base),
        )
        init_operator = _mcp_call(
            operator_mcp,
            10,
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {}, "auth_token": "mcp_operator"},
        )
        assert "error" not in init_operator

        started_status, started = _http_json(method="POST", url=f"{base}/api/chat/session/start", payload={"label": "parity"})
        assert started_status == 200
        session_id = str(started["session"]["session_id"])
        bad_domain = _mcp_call(
            operator_mcp,
            11,
            "tools/call",
            {
                "name": "integration.writeback.propose",
                "arguments": {
                    "request_id": "req_DOMAINERR1234567",
                    "session_id": session_id,
                    "run_id": "run_mcp_domain_1",
                    "idempotency_key": "idem_mcp_domain_1",
                    "mutation": {"intent": "create", "body": {"canonical_text": "missing target kind"}},
                    "evidence": [
                        {
                            "provenance_handle": "prov_1",
                            "source_kind": "conversation",
                            "source_id": "conv_tea",
                            "excerpt": "tea mention",
                            "citation": {"type": "message", "ref": "conv_tea#m1"},
                            "confidence": 0.66,
                        }
                    ],
                },
            },
        )
        assert "error" not in bad_domain
        assert bad_domain["result"]["isError"] is False
        domain_payload = dict(bad_domain["result"]["structuredContent"])
        assert domain_payload["ok"] is False
        assert domain_payload["error"]["code"] == "INVALID_INPUT"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
