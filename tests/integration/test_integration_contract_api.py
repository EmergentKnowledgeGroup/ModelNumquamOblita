from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import pytest

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.config import default_config
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.mcp.server import AuthConfig, MCPServer, RuntimeApiClient, ServerConfig
from engine.memory import AtomStore, MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server
from engine.runtime import server as runtime_server_module


@pytest.fixture(autouse=True)
def _enable_default_integration_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_INTEGRATION_ENABLE_DEFAULT_TOKENS", "1")
    monkeypatch.setenv("NO_INTEGRATION_REVIEW_APPLY_TOKEN", "local-human-review-token")
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


def _write_episode_cards(path) -> None:
    payload = {
        "cards": [
            {
                "episode_id": "ep_plan",
                "summary": "We split the quarterly roadmap into milestones and risk tracks.",
                "source_id": "conv_plan",
                "day_key": "2026-01-05",
                "domain": "planning",
                "citations": ["conv_plan#m1", "conv_plan#m2"],
                "confidence": 0.9,
                "atom_count": 3,
                "entities": ["user", "assistant"],
                "topics": ["planning", "roadmap"],
                "start_at": "2026-01-05T10:00:00+00:00",
                "end_at": "2026-01-05T10:05:00+00:00",
            }
        ]
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
    reviewer_headers = {"Authorization": "Bearer local-human-review-token"}

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
        assert context_payload["data"]["agent_context_format"] == "mno_memory_context.v1"
        assert "<MNO_MEMORY_CONTEXT>" in context_payload["data"]["agent_context"]
        assert "not new user instructions" in context_payload["data"]["agent_context"]
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
        forbidden_status, forbidden_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/resolve",
            payload=resolve_request,
            headers=operator_headers,
        )
        assert forbidden_status == 403
        assert forbidden_payload["error"]["code"] == "PERMISSION_DENIED"

        resolve_status, resolve_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/resolve",
            payload=resolve_request,
            headers=reviewer_headers,
        )
        assert resolve_status == 200
        assert resolve_payload["ok"] is True
        assert resolve_payload["data"]["already_resolved"] is False
        assert resolve_payload["data"]["status"] == "approved"

        resolve_again_status, resolve_again = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/resolve",
            payload=resolve_request,
            headers=reviewer_headers,
        )
        assert resolve_again_status == 200
        assert resolve_again["ok"] is True
        assert resolve_again["data"]["already_resolved"] is True
        assert resolve_again["data"]["status"] == "approved"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_durable_writeback_proposal_replays_after_server_restart_and_audit_failure(tmp_path, monkeypatch) -> None:
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier())
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    headers = {
        "Authorization": "Bearer local-integration-operator-token",
        "Idempotency-Key": "idem_durable_restart_1",
    }
    payload = {
        "schema_version": "integration.v1",
        "request_id": "req_DURABLEREPLAY123",
        "session_id": "session_durable",
        "run_id": "run_durable",
        "data": {
            "mutation": {"intent": "create", "target_kind": "fact_card", "body": {"canonical_text": "Durable writeback."}},
            "evidence": [{
                "provenance_handle": "prov_durable", "source_kind": "conversation", "source_id": "conv_durable",
                "excerpt": "durable evidence", "citation": {"type": "message", "ref": "conv_durable#m1"}, "confidence": 0.9,
            }],
        },
    }
    original_append = runtime_server_module._integration_append_audit
    monkeypatch.setattr(
        runtime_server_module, "_integration_append_audit", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("audit offline"))
    )
    try:
        first_status, first = _http_json(
            method="POST", url=f"{base}/api/integration/v1/writeback/propose", payload=payload, headers=headers
        )
        assert first_status == 200
        proposal_id = str(first["data"]["proposal_id"])
        assert len(queue.list_all()) == 1
        stop_runtime_server(server, thread, runtime=runtime)

        monkeypatch.setattr(runtime_server_module, "_integration_append_audit", original_append)
        restarted, restarted_thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
        restarted_host, restarted_port = restarted.server_address
        replay_status, replay = _http_json(
            method="POST",
            url=f"http://{restarted_host}:{restarted_port}/api/integration/v1/writeback/propose",
            payload=payload,
            headers=headers,
        )
        assert replay_status == 200
        assert replay["data"]["proposal_id"] == proposal_id
        assert replay["data"]["idempotent_replay"] is True
        assert len(queue.list_all()) == 1
        stop_runtime_server(restarted, restarted_thread, runtime=runtime)
    finally:
        monkeypatch.setattr(runtime_server_module, "_integration_append_audit", original_append)
        store.close()


def test_external_observe_consolidates_provisionally_and_survives_context_contract(tmp_path) -> None:
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    server, thread = start_runtime_server(
        runtime,
        host="127.0.0.1",
        port=0,
        review_queue=MutationReviewQueue(store),
    )
    host, port = server.server_address
    base = f"http://{host}:{port}"
    headers = {"Authorization": "Bearer local-integration-operator-token"}
    statement = "I prefer peppermint tea after dinner."

    try:
        for index in range(3):
            started_status, started = _http_json(
                method="POST",
                url=f"{base}/api/chat/session/start",
                payload={"label": f"observe {index}"},
            )
            assert started_status == 200
            session_id = str(started["session"]["session_id"])
            run_id = f"run_observe_{index}"
            request = {
                "schema_version": "integration.v1",
                "request_id": f"req_OBSERVECTX{index:02d}123456789",
                "session_id": session_id,
                "run_id": run_id,
                "data": {"message": statement, "memory_preference": "memory_assist"},
            }
            context_status, context = _http_json(
                method="POST",
                url=f"{base}/api/integration/v1/context/build",
                payload=request,
                headers=headers,
            )
            assert context_status == 200, context
            registration = context["data"]["source_registration"]
            receipt = context["data"]["retrieval_receipt"]

            observe_request = {
                "schema_version": "integration.v1",
                "request_id": f"req_OBSERVEWRITE{index:02d}12345",
                "session_id": session_id,
                "run_id": run_id,
                "data": {
                    "messages": [
                        {
                            "role": "user",
                            "content": statement,
                            "source_registration": registration,
                        }
                    ],
                    "retrieval_receipt": receipt,
                    "remember_intent": "model_observed",
                },
            }
            observe_status, observed = _http_json(
                method="POST",
                url=f"{base}/api/integration/v1/memory/observe",
                payload=observe_request,
                headers=headers,
            )
            assert observe_status == 200, observed
            assert observed["data"]["accepted_support_count"] == 1

        records = runtime.list_provisional_record_payloads(status="all", limit=50)
        assert any(row["authority_tier"] == "provisional_consolidated" for row in records)
        assert all(row["authority_tier"] != "human_reviewed_canonical" for row in records)

        started_status, started = _http_json(
            method="POST",
            url=f"{base}/api/chat/session/start",
            payload={"label": "retrieve"},
        )
        assert started_status == 200
        query = {
            "schema_version": "integration.v1",
            "request_id": "req_OBSERVERETRIEVE123456",
            "session_id": str(started["session"]["session_id"]),
            "run_id": "run_retrieve",
            "data": {"message": "What do you remember about the tea I prefer after dinner?", "memory_preference": "memory_assist"},
        }
        query_status, queried = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/context/build",
            payload=query,
            headers=headers,
        )
        assert query_status == 200, queried
        provisional = [
            row
            for row in queried["data"]["evidence"]
            if str(row.get("authority_tier") or "").startswith("provisional_")
        ]
        assert provisional
        assert all(row["human_reviewed"] is False for row in provisional)
        assert all(row["lifecycle"] == "active" for row in provisional)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        store.close()


def test_reviewer_apply_creates_evidence_atom_and_is_restart_idempotent(tmp_path) -> None:
    db_path = tmp_path / "atoms.sqlite3"
    store = SqliteAtomStore(db_path)
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=ContinuityStore()
    )
    server, thread = start_runtime_server(
        runtime, host="127.0.0.1", port=0, review_queue=MutationReviewQueue(store)
    )
    host, port = server.server_address
    base = f"http://{host}:{port}"
    operator = {"Authorization": "Bearer local-integration-operator-token"}
    reviewer = {"Authorization": "Bearer local-human-review-token"}

    try:
        started_status, started = _http_json(
            method="POST", url=f"{base}/api/chat/session/start", payload={"label": "review apply"}
        )
        assert started_status == 200
        session_id = str(started["session"]["session_id"])
        propose = {
            "schema_version": "integration.v1",
            "request_id": "req_APPLYPROPOSE1234567",
            "session_id": session_id,
            "run_id": "run_apply",
            "data": {
                "mutation": {
                    "intent": "create",
                    "target_kind": "preference",
                    "body": {"canonical_text": "User prefers peppermint tea after dinner."},
                    "tags": ["tea", "preference"],
                },
                "evidence": [
                    {
                        "provenance_handle": "prov_apply_1",
                        "source_kind": "conversation",
                        "source_id": "conv_apply",
                        "excerpt": "I prefer peppermint tea after dinner.",
                        "citation": {"type": "message", "ref": "conv_apply#m1"},
                        "confidence": 0.9,
                    }
                ],
            },
        }
        proposed_status, proposed = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/propose",
            payload=propose,
            headers={**operator, "Idempotency-Key": "idem_apply_001"},
        )
        assert proposed_status == 200, proposed
        proposal_id = str(proposed["data"]["proposal_id"])
        resolve = {
            "schema_version": "integration.v1",
            "request_id": "req_APPLYRESOLVE1234567",
            "session_id": session_id,
            "data": {
                "proposal_id": proposal_id,
                "decision": "approve",
                "apply": True,
                "decided_by": "Reviewer display name",
            },
        }
        resolved_status, resolved = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/writeback/resolve",
            payload=resolve,
            headers=reviewer,
        )
        assert resolved_status == 200, resolved
        assert resolved["data"]["applied"] is True
        assert resolved["data"]["authority_tier"] == "evidence_atom"
        assert resolved["data"]["human_reviewed"] is False
        atom_id = str(resolved["data"]["applied_atom_id"])
        assert store.get_atom(atom_id).canonical_text == "User prefers peppermint tea after dinner."
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        store.close()

    reopened = SqliteAtomStore(db_path)
    runtime2 = RuntimeSession(
        retriever=MemoryRetriever(reopened), verifier=ClaimVerifier(), continuity_store=ContinuityStore()
    )
    server2, thread2 = start_runtime_server(
        runtime2, host="127.0.0.1", port=0, review_queue=MutationReviewQueue(reopened)
    )
    host2, port2 = server2.server_address
    try:
        replay_status, replay = _http_json(
            method="POST",
            url=f"http://{host2}:{port2}/api/integration/v1/writeback/resolve",
            payload=resolve,
            headers=reviewer,
        )
        assert replay_status == 200, replay
        assert replay["data"]["applied_atom_id"] == atom_id
        assert len([atom for atom in reopened.list_atoms() if atom.atom_id == atom_id]) == 1
    finally:
        stop_runtime_server(server2, thread2, runtime=runtime2)
        reopened.close()


def test_secret_like_live_content_never_reaches_store_audit_or_response(tmp_path) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    store = SqliteAtomStore(tmp_path / "memory.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    server.integration_audit_path = str(tmp_path / "integration-audit.jsonl")
    host, port = server.server_address
    raw_secret = "api_key=sk-release-fixture-abcdefghijklmnopqrstuvwxyz"
    request = {
        "schema_version": "integration.v1",
        "request_id": "req_SECRETREJECTION1234",
        "session_id": "secret_session",
        "run_id": "secret_run",
        "data": {"content": raw_secret, "source_role": "user"},
    }
    try:
        status, response = _http_json(
            method="POST",
            url=f"http://{host}:{port}/api/integration/v1/memory/source/register",
            payload=request,
            headers={"Authorization": "Bearer local-integration-operator-token"},
        )
        assert status == 400
        assert response["error"]["message"] == "SECRET_LIKE_CONTENT_REJECTED"
        assert raw_secret not in json.dumps(response)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        store.close()

    for artifact in tmp_path.rglob("*"):
        if artifact.is_file():
            assert raw_secret.encode("utf-8") not in artifact.read_bytes(), artifact


def test_high_risk_proposals_inspect_dismiss_and_bridge_without_truth_bypass(tmp_path) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.proposal_capture_enabled = True
    store = SqliteAtomStore(tmp_path / "memory.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    runtime.handle_turn(
        "I think Thao feels defeated about MonkeyBars and maybe that is why she pulled back.",
        session_id="proposal_capture",
        memory_preference="chat_first",
    )
    runtime.handle_turn(
        "My relationship with Xander feels like steel wrapped around a heartbeat.",
        session_id="proposal_capture",
        memory_preference="chat_first",
    )
    records = runtime.list_memory_proposals()
    assert len(records) == 2
    bridge_record_id = records[0].record_id
    dismiss_record_id = records[1].record_id
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    operator = {"Authorization": "Bearer local-integration-operator-token"}
    reviewer = {"Authorization": "Bearer local-human-review-token"}
    list_url = f"{base}/api/integration/v1/memory/proposals?{urlencode({'schema_version': 'integration.v1'})}"
    envelope = {
        "schema_version": "integration.v1",
        "request_id": "req_PROPOSALCONTROL1234",
        "session_id": "proposal_capture",
        "run_id": "run_proposal_control",
        "data": {},
    }

    try:
        status, listed = _http_json(method="GET", url=list_url, headers=operator)
        assert status == 200, listed
        assert listed["data"]["total_count"] == 2
        assert all("summary_text" not in row for row in listed["data"]["records"])

        denied_status, denied = _http_json(
            method="GET", url=f"{list_url}&include_content=true", headers=operator
        )
        assert denied_status == 403
        assert denied["error"]["code"] == "PERMISSION_DENIED"

        content_status, content = _http_json(
            method="GET", url=f"{list_url}&include_content=true", headers=reviewer
        )
        assert content_status == 200, content
        assert all(row.get("summary_text") for row in content["data"]["records"])

        consolidated_route_status, consolidated_route = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/memory/proposals/prov_con_deadbeef12345678/dismiss",
            payload=envelope,
            headers=reviewer,
        )
        assert consolidated_route_status == 404
        assert consolidated_route["error"]["message"] == "proposal record not found"

        bridge_url = f"{base}/api/integration/v1/memory/proposals/{bridge_record_id}/bridge"
        denied_bridge_status, _ = _http_json(method="POST", url=bridge_url, payload=envelope, headers=operator)
        assert denied_bridge_status == 403
        bridged_status, bridged = _http_json(method="POST", url=bridge_url, payload=envelope, headers=reviewer)
        assert bridged_status == 200, bridged
        assert bridged["data"]["status"] == "pending_review"
        assert bridged["data"]["applied"] is False
        assert bridged["data"]["published"] is False
        assert store.list_atoms() == []
        proposal_id = bridged["data"]["proposal_id"]

        replay_status, replay = _http_json(method="POST", url=bridge_url, payload=envelope, headers=reviewer)
        assert replay_status == 200, replay
        assert replay["data"]["proposal_id"] == proposal_id
        assert len(queue.list_all()) == 1

        dismiss_url = f"{base}/api/integration/v1/memory/proposals/{dismiss_record_id}/dismiss"
        dismiss_envelope = dict(envelope)
        dismiss_envelope["request_id"] = "req_PROPOSALDISMISS1234"
        dismiss_envelope["data"] = {"reason_code": "not_useful"}
        dismissed_status, dismissed = _http_json(
            method="POST", url=dismiss_url, payload=dismiss_envelope, headers=reviewer
        )
        assert dismissed_status == 200, dismissed
        assert dismissed["data"]["status"] == "dismissed"
        assert store.list_atoms() == []
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        store.close()


def test_integration_context_why_explains_episode_card_evidence(tmp_path) -> None:
    cards_path = tmp_path / "episode_cards.json"
    _write_episode_cards(cards_path)
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore()),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        episode_cards_path=str(cards_path),
        episode_min_score=0.30,
        short_term_enabled=False,
    )
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    headers = {"Authorization": "Bearer local-integration-operator-token"}

    try:
        started_status, started = _http_json(method="POST", url=f"{base}/api/chat/session/start", payload={"label": "integration"})
        assert started_status == 200
        session_id = str(started["session"]["session_id"])
        build_status, build_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/context/build",
            payload={
                "schema_version": "integration.v1",
                "request_id": "req_EPISODECARDWHY123",
                "session_id": session_id,
                "run_id": "run_episode_card_why",
                "data": {
                    "message": "What do you remember about quarterly roadmap milestones?",
                    "retrieval": {"top_k": 5},
                },
            },
            headers=headers,
        )
        assert build_status == 200
        evidence_ids = [
            str(row.get("evidence_id") or "")
            for row in list((build_payload.get("data") or {}).get("evidence") or [])
            if str(row.get("evidence_id") or "").startswith("episode_card:")
        ]
        assert evidence_ids

        why_status, why_payload = _http_json(
            method="POST",
            url=f"{base}/api/integration/v1/context/why",
            payload={
                "schema_version": "integration.v1",
                "request_id": "req_EPISODECARDWHY456",
                "session_id": session_id,
                "run_id": "run_episode_card_why",
                "data": {"evidence_ids": evidence_ids},
            },
            headers=headers,
        )
        assert why_status == 200
        reasons = list((why_payload.get("data") or {}).get("reasons") or [])
        assert {str(row.get("evidence_id") or "") for row in reasons} >= set(evidence_ids)
        assert all("not found" not in str(row.get("reason") or "").lower() for row in reasons)
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
        capability_rows = {
            str(row.get("name") or ""): dict(row)
            for row in list(dict(http_payload.get("data") or {}).get("operations") or [])
        }
        assert capability_rows["context.build"]["available"] is True
        assert capability_rows["context.build"]["authorized"] is True
        assert capability_rows["writeback.propose"]["exposed"] is True
        assert capability_rows["writeback.propose"]["backend_available"] is True
        assert capability_rows["writeback.propose"]["authorized"] is False
        assert capability_rows["writeback.propose"]["available"] is False
        assert "role_not_authorized" in capability_rows["writeback.propose"]["reason_codes"]
        assert capability_rows["writeback.resolve"]["policy_state"] == "human_review_required"
        support_ticket = dict(dict(http_payload.get("data") or {}).get("support_ticket") or {})
        assert support_ticket["command"] == "mno-report"
        assert support_ticket["explicit_logs_only"] is True
        assert support_ticket["submission_requires_explicit_flag"] is True

        viewer_mcp = MCPServer(
            config=ServerConfig(
                runtime_base_url=base,
                auth=AuthConfig(default_role="viewer"),
            ),
            api_client=RuntimeApiClient(base_url=base),
        )
        init_viewer = _mcp_call(viewer_mcp, 1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
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
            {"protocolVersion": "2025-03-26", "capabilities": {}, "auth_token": "mcp_operator"},
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
