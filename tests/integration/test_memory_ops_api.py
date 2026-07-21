from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from engine.continuity import Constellation, ContinuityBuilder, ContinuitySnapshot, ContinuityStore, NarrativeArc, SharedLanguageKey
from engine.config import default_config
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStatus, AtomStore, MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server
from engine.runtime import server as runtime_server_module


def test_wizard_and_curation_routes_are_loopback_only() -> None:
    for path in ("/curate/wizard_123", "/api/wizard/hcr/status", "/api/wizard/review/update"):
        assert runtime_server_module._wizard_route_is_allowed(path, "127.0.0.1") is True
        assert runtime_server_module._wizard_route_is_allowed(path, "::1") is True
        assert runtime_server_module._wizard_route_is_allowed(path, "::ffff:127.0.0.1") is True
        assert runtime_server_module._wizard_route_is_allowed(path, "192.168.1.50") is False
        assert runtime_server_module._wizard_route_is_allowed(path, "0.0.0.0") is False
    assert runtime_server_module._wizard_route_is_allowed("/api/runtime/health", "192.168.1.50") is True


@pytest.fixture(autouse=True)
def _isolate_runtime_server_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(runtime_server_module, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(runtime_server_module, "WIZARD_RUNS_ROOT", runtime_root / "wizard_runs")
    monkeypatch.setattr(runtime_server_module, "WIZARD_LATEST_PATH", runtime_root / "wizard_runs" / "LATEST.json")
    monkeypatch.setattr(runtime_server_module, "BUILDER_PROFILES_ROOT", runtime_root / "builder_profiles")
    monkeypatch.setattr(runtime_server_module, "IMPORTS_ROOT", runtime_root / "imports")
    monkeypatch.setattr(runtime_server_module, "EPISODES_ROOT", runtime_root / "episodes")
    monkeypatch.setattr(runtime_server_module, "BACKUPS_ROOT", runtime_root / "backups")
    monkeypatch.setattr(runtime_server_module, "DIAGNOSTICS_ROOT", runtime_root / "diagnostics")
    monkeypatch.setattr(runtime_server_module, "PACKAGING_ROOT", runtime_root / "packaging")
    monkeypatch.setattr(runtime_server_module, "LIVE_RUNTIME_LOCK_PATH", runtime_root / "live_runtime.lock.json")
    monkeypatch.setattr(runtime_server_module, "QUICKNOTE_STATE_PATH", runtime_root / "diagnostics" / "quicknote_state.json")
    monkeypatch.setattr(runtime_server_module, "METHODOLOGY_STATE_PATH", runtime_root / "diagnostics" / "methodology_state.json")
    monkeypatch.setattr(runtime_server_module, "CONTINUITY_ADDS_STATE_PATH", runtime_root / "diagnostics" / "continuity_adds_state.json")


def _candidate(candidate_id: str, text: str, source_id: str, topic: str = "memory") -> CandidateAtom:
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
        entities=["user", "assistant"],
        topics=[topic],
        confidence=0.84,
        salience=0.68,
    )


def _seed_sqlite_store(path: Path) -> None:
    store = SqliteAtomStore(path)
    try:
        store.add_candidate(_candidate("s1", "We reviewed the quarterly plan and split it into three launch milestones.", "conv_seed", "planning"))
        store.add_candidate(_candidate("s2", "You asked for a rollback procedure and I wrote a verification checklist for every milestone.", "conv_seed", "planning"))
        store.add_candidate(_candidate("s3", "We assigned dependency owners and mitigation tracks so the launch could run safely.", "conv_seed", "operations"))
    finally:
        store.close()


def _seed_wizard_review_draft(path: Path, *, count: int) -> dict:
    payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [
            {
                "episode_id": f"ep_{index:03d}",
                "title": f"Episode {index:03d}",
                "summary": f"Draft summary {index:03d} for pagination and review ergonomics.",
                "actors": ["user", "assistant"],
                "topic_tags": ["testing", "wizard"],
                "promotion_status": "candidate",
            }
            for index in range(1, count + 1)
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _seed_draft_curation_run(tmp_path: Path, *, count: int = 2) -> dict:
    draft_path = tmp_path / "runtime" / "episodes" / "draft_cards.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_payload = _seed_wizard_review_draft(draft_path, count=count)
    state = runtime_server_module._start_new_wizard_state()
    state["store_validation"] = {
        "path": str((tmp_path / "runtime" / "imports" / "atoms.sqlite3").resolve()),
        "kind": "mno_store_sqlite",
        "is_valid": True,
        "issues": [],
        "store_fingerprint": "sqlite_store:v3:atoms:3:sample:test",
        "schema_version": 3,
        "atom_count": 3,
        "source": "existing_store",
    }
    state["build_info"] = {
        "build_id": "build_draft_curation",
        "store_fingerprint": "sqlite_store:v3:atoms:3:sample:test",
        "schema_version": 3,
        "draft_path": str(draft_path),
        "rejects_path": "",
        "readout_path": "",
        "counts": {"draft_count": count},
    }
    state["last_built_episode_draft_path"] = str(draft_path)
    runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
    runtime_server_module._save_wizard_state(state)
    return state


def _json_get(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_post(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_post_error(url: str, payload: dict) -> tuple[int, dict]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _json_get_error(url: str) -> tuple[int, dict]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_wizard_path_sanitizer_collapses_mangled_windows_mount_paths(monkeypatch) -> None:
    monkeypatch.setattr(runtime_server_module.os, "name", "nt", raising=False)
    normalized = runtime_server_module._wizard_normalize_path_value(
        r"Z:\mnt\z\mno-workspace\runtime\imports\atoms.sqlite3"
    )
    assert normalized == r"Z:\mno-workspace\runtime\imports\atoms.sqlite3"

    state = {
        "store_path": r"Z:\mnt\z\mno-workspace\runtime\imports\atoms.sqlite3",
        "store_validation": {
            "path": r"Z:\mnt\z\mno-workspace\runtime\imports\atoms.sqlite3",
        },
        "published_set": {
            "episodes_path": r"Z:\mno-workspace\runtime\episodes\episode_cards.reviewed.json",
        },
        "verify": {
            "checks": [
                {"id": "store_validation", "path": r"Z:\mnt\z\mno-workspace\runtime\imports\atoms.sqlite3"},
                {"id": "published_set", "path": r"Z:\mno-workspace\runtime\episodes\episode_cards.reviewed.json"},
            ],
            "actionable_links": [],
        },
    }
    sanitized = runtime_server_module._wizard_normalize_state_paths(state)
    assert sanitized["store_path"] == r"Z:\mno-workspace\runtime\imports\atoms.sqlite3"
    assert sanitized["store_validation"]["path"] == r"Z:\mno-workspace\runtime\imports\atoms.sqlite3"
    assert sanitized["verify"]["checks"][0]["path"] == r"Z:\mno-workspace\runtime\imports\atoms.sqlite3"


def test_memory_atoms_cards_detail_and_graph_endpoints() -> None:
    store = AtomStore()
    first = store.add_candidate(_candidate("a1", "We anchored continuity to evidence.", "conv_1", "continuity"))
    second = store.add_candidate(_candidate("a2", "You prefer tea in late sessions.", "conv_2", "preference"))
    third = store.add_candidate(_candidate("a3", "We tracked migration rollback safeguards.", "conv_3", "operations"))
    fragment = store.add_candidate(_candidate("a4", "EXACTLY", "conv_4", "fragment"))
    store.mark_conflict(first.atom_id, second.atom_id, reason="intentional test conflict")

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        atoms = _json_get(f"{base}/api/memory/atoms?status=all&limit=20")
        assert atoms["ok"] is True
        assert atoms["total"] >= 2
        atom_ids = {item["atom_id"] for item in atoms["atoms"]}
        assert first.atom_id in atom_ids

        filtered = _json_get(f"{base}/api/memory/atoms?q={quote('tea')}")
        assert filtered["ok"] is True
        assert any("tea" in item["canonical_text"].lower() for item in filtered["atoms"])

        cards = _json_get(f"{base}/api/memory/cards?status=all&limit=20")
        assert cards["ok"] is True
        assert cards["total"] >= 3
        card_ids = {item["card_id"] for item in cards["cards"]}
        assert f"card_{first.atom_id}" in card_ids
        fragment_card = next(item for item in cards["cards"] if item["card_id"] == f"card_{fragment.atom_id}")
        assert fragment_card["summary_abstractive"].endswith("Limited source detail.")

        filtered_cards = _json_get(f"{base}/api/memory/cards?q={quote('tea')}&kind=event_card")
        assert filtered_cards["ok"] is True
        assert any("tea" in item["summary"].lower() for item in filtered_cards["cards"])

        card_detail = _json_get(f"{base}/api/memory/cards/{quote(f'card_{first.atom_id}')}")
        assert card_detail["ok"] is True
        assert card_detail["card"]["card_id"] == f"card_{first.atom_id}"
        assert card_detail["atom"]["atom_id"] == first.atom_id
        assert isinstance(card_detail["provenance_events"], list)
        assert "conflicts" in card_detail["graph"]

        detail = _json_get(f"{base}/api/memory/atom/{quote(first.atom_id)}")
        assert detail["ok"] is True
        assert detail["atom"]["atom_id"] == first.atom_id
        assert isinstance(detail["provenance_events"], list)
        assert "conflicts" in detail["graph"]

        conflict_mark = _json_post(
            f"{base}/api/memory/atoms/{quote(first.atom_id)}/conflict",
            {"other_atom_id": third.atom_id, "reason": "manual_conflict_from_ui"},
        )
        assert conflict_mark["ok"] is True
        assert conflict_mark["conflict"]["reason"] == "manual_conflict_from_ui"

        graph = _json_get(f"{base}/api/memory/graph?atom_id={quote(first.atom_id)}")
        assert graph["ok"] is True
        assert graph["atom"]["atom_id"] == first.atom_id
        assert any(link["kind"] == "conflict" for link in graph["links"])

        graph_map = _json_get(f"{base}/api/memory/graph-map?status=all&limit=20")
        assert graph_map["ok"] is True
        assert graph_map["total"] >= 2
        assert any(node["atom_id"] == first.atom_id for node in graph_map["nodes"])
        assert any(link["kind"] == "conflict" for link in graph_map["links"])

        filtered_graph_map = _json_get(f"{base}/api/memory/graph-map?q={quote('tea')}&status=all&limit=20")
        assert filtered_graph_map["ok"] is True
        assert filtered_graph_map["total"] >= 1
        assert all("tea" in str(node["summary"]).lower() for node in filtered_graph_map["nodes"])
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_memory_graph_neighbors_endpoint_is_bounded_and_truthful() -> None:
    store = AtomStore()
    root = store.add_candidate(_candidate("g1", "Root memory about tea rituals.", "conv_g1", "tea"))
    conflict = store.add_candidate(_candidate("g2", "Conflict memory about tea rituals.", "conv_g2", "tea"))
    distance_two = store.add_candidate(_candidate("g3", "Distance-two arc memory.", "conv_g3", "tea"))
    shared = store.add_candidate(_candidate("g4", "Shared callback memory.", "conv_g4", "callback"))
    shared_child = store.add_candidate(_candidate("g5", "Shared child should never expand.", "conv_g5", "callback"))
    constellation = store.add_candidate(_candidate("g6", "Constellation partner memory.", "conv_g6", "tea"))

    store.mark_conflict(root.atom_id, conflict.atom_id, reason="root_conflict")
    store.mark_conflict(shared.atom_id, shared_child.atom_id, reason="shared_conflict")

    now = datetime.now(timezone.utc)
    snapshot = ContinuitySnapshot(
        generated_at=now,
        constellations=[
            Constellation(
                constellation_id="const_graph_neighbors",
                topic="tea",
                atom_ids=[root.atom_id, constellation.atom_id],
                strength=0.81,
                entities=["user"],
            )
        ],
        narrative_arcs=[
            NarrativeArc(
                arc_id="arc_graph_neighbors",
                entity="user",
                topic="tea",
                atom_ids=[conflict.atom_id, distance_two.atom_id],
                start_at=now,
                end_at=now,
                confidence=0.87,
            )
        ],
        shared_language_keys=[
            SharedLanguageKey(
                key_id="tea_ritual",
                phrase="tea ritual",
                atom_ids=[root.atom_id, shared.atom_id],
                support_count=2,
                weight=0.9,
            )
        ],
    )

    continuity = ContinuityStore()
    continuity.set_snapshot(snapshot)
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        payload = _json_get(
            f"{base}/api/memory/graph/neighbors?atom_id={quote(root.atom_id)}&depth=2&include_shared_language=true"
        )
        assert payload["ok"] is True
        assert payload["node"]["atom_id"] == root.atom_id
        neighbor_ids = [row["atom_id"] for row in payload["neighbors"]]
        assert conflict.atom_id in neighbor_ids
        assert constellation.atom_id in neighbor_ids
        assert shared.atom_id in neighbor_ids
        assert distance_two.atom_id in neighbor_ids
        assert shared_child.atom_id not in neighbor_ids
        assert any(row["atom_id"] == distance_two.atom_id and row["distance"] == 2 for row in payload["neighbors"])
        allowed_ids = set(neighbor_ids).union({root.atom_id})
        assert all(link["source"] in allowed_ids for link in payload["links"])
        assert all(link["target"] in allowed_ids for link in payload["links"])

        compact_root = _json_get(
            f"{base}/api/memory/graph/neighbors?atom_id={quote(root.atom_id)}&include_root_detail=false"
        )
        assert compact_root["node"]["atom_id"] == root.atom_id
        assert "kind" in compact_root["node"]
        assert "card_id" not in compact_root["node"]
        assert "status" not in compact_root["node"]
        assert "summary" not in compact_root["node"]

        truncated = _json_get(
            f"{base}/api/memory/graph/neighbors?atom_id={quote(root.atom_id)}&depth=2&node_limit=1&link_limit=10&include_shared_language=true"
        )
        assert truncated["truncated"] is True
        assert truncated["truncation"]["node_limit_hit"] is True
        kept_ids = {row["atom_id"] for row in truncated["neighbors"]}.union({root.atom_id})
        assert all(link["source"] in kept_ids for link in truncated["links"])
        assert all(link["target"] in kept_ids for link in truncated["links"])

        status_code, error_payload = _json_get_error(
            f"{base}/api/memory/graph/neighbors?atom_id={quote(root.atom_id)}&depth=3"
        )
        assert status_code == 400
        assert error_payload["error"] == "depth must be between 1 and 2"

        missing_code, missing_payload = _json_get_error(f"{base}/api/memory/graph/neighbors?atom_id=missing_atom")
        assert missing_code == 404
        assert missing_payload["error"] == "atom not found"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_memory_proposal_review_endpoints_and_decay_recompute() -> None:
    store = AtomStore()
    base_atom = store.add_candidate(_candidate("b1", "The ritual line should stay evidence-backed.", "conv_3", "ritual"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))

    queue = MutationReviewQueue(store)
    proposal_delete = queue.propose_delete(target_atom_id=base_atom.atom_id, reason_code="manual_cleanup")
    proposal_reject = queue.propose_delete(target_atom_id=base_atom.atom_id, reason_code="duplicate_cleanup")

    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        proposals = _json_get(f"{base}/api/memory/proposals")
        assert proposals["ok"] is True
        ids = {item["proposal_id"] for item in proposals["proposals"]}
        assert proposal_delete.proposal_id in ids
        assert proposal_reject.proposal_id in ids

        approved = _json_post(
            f"{base}/api/memory/proposals/{quote(proposal_delete.proposal_id)}/approve",
            {"reviewer": "test", "apply": True},
        )
        assert approved["ok"] is True
        assert approved["proposal"]["status"] == "applied"

        after_detail = _json_get(f"{base}/api/memory/atom/{quote(base_atom.atom_id)}")
        assert after_detail["atom"]["status"] == AtomStatus.TOMBSTONED.value

        rejected = _json_post(
            f"{base}/api/memory/proposals/{quote(proposal_reject.proposal_id)}/reject",
            {"reviewer": "test", "reason": "redundant"},
        )
        assert rejected["ok"] is True
        assert rejected["proposal"]["status"] == "rejected"

        decay = _json_post(f"{base}/api/memory/decay/recompute", {"apply_promotions": False})
        assert decay["ok"] is True
        assert "decayed_atoms" in decay["summary"]
        assert "snapshot_revision" in decay["summary"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_memory_proposal_endpoints_without_queue() -> None:
    store = AtomStore()
    store.add_candidate(_candidate("c1", "Simple memory.", "conv_9"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        proposals = _json_get(f"{base}/api/memory/proposals")
        assert proposals["ok"] is True
        assert proposals["status"] == "queue_unavailable"

        code, payload = _json_post_error(
            f"{base}/api/memory/proposals/not-real/approve",
            {"reviewer": "test", "apply": True},
        )
        assert code == 404
        assert payload["error"] == "proposal queue not available"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_provisional_memory_endpoints_surface_conflicts_and_review_candidates() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.retrieval_enabled = True
    cfg.provisional_memory.review_worthiness.fact_min_score = 0.20
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    runtime.handle_turn("Thao is in on MonkeyBars for the build sprint.", memory_preference="memory_assist")
    runtime.handle_turn("Thao is out on MonkeyBars for the build sprint.", memory_preference="memory_assist")
    hits = runtime.search_provisional_memory("MonkeyBars", limit=6)
    assert len(hits) >= 2
    runtime.mark_provisional_conflict(hits[0].record.record_id, hits[1].record.record_id, reason="manual_conflict")

    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        provisional = _json_get(f"{base}/api/memory/provisional?status=live&q={quote('MonkeyBars')}")
        assert provisional["ok"] is True
        assert provisional["total"] == 2
        rows = provisional["records"]
        assert all(item["status"] == "conflicted" for item in rows)
        assert all(item["memory_layer"] == "provisional" for item in rows)
        assert all(item["trust_tier"] == "provisional" for item in rows)
        assert rows[0]["record_id"] in rows[1]["conflict_with_record_ids"]
        assert rows[1]["record_id"] in rows[0]["conflict_with_record_ids"]
        assert all(item["source_refs"] for item in rows)

        review_candidates = _json_get(f"{base}/api/memory/provisional/review-candidates?q={quote('MonkeyBars')}")
        assert review_candidates["ok"] is True
        assert review_candidates["total"] == 2
        candidate = review_candidates["review_candidates"][0]
        assert candidate["bridge_state"] == "candidate_only"
        assert candidate["review_path"] == "existing_review_pipeline"
        assert candidate["human_review_required"] is True
        assert candidate["memory_layer"] == "provisional"
        assert candidate["trust_tier"] == "provisional"
        assert "review_worthy" in candidate
        assert candidate["bridge_eligible"] is True
        assert candidate["bridge_action"] == "PROPOSE_CREATE"
        assert candidate["history_event_count"] >= 1
        assert candidate["lineage_record_ids"]
        assert candidate["source_refs"]
        assert candidate["review_candidate_id"].startswith("prc_prov_")
        assert len(runtime.retriever.store.list_atoms()) == 0
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_provisional_memory_bridge_settings_and_boundary_endpoints() -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    cfg.provisional_memory.stm_sweep_enabled = True
    cfg.provisional_memory.review_worthiness.fact_min_score = 0.20
    store = AtomStore()
    queue = MutationReviewQueue(store)
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )
    runtime.handle_turn("Thao is in on MonkeyBars for the build sprint.", session_id="alpha", memory_preference="memory_assist")

    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    server.writeback_policy = {
        "enabled": True,
        "mode": "proposal_only",
        "auto_apply": False,
        "updated_at": "2026-03-24T08:00:00+00:00",
    }

    try:
        settings = _json_get(f"{base}/api/memory/provisional/settings")
        assert settings["ok"] is True
        assert settings["settings"]["default_sensitivity"] == "balanced"

        bumped = _json_post(f"{base}/api/memory/provisional/settings", {"action": "remember_more"})
        assert bumped["ok"] is True
        assert bumped["settings"]["default_sensitivity"] == "eager"

        candidates = _json_get(f"{base}/api/memory/provisional/review-candidates?q={quote('MonkeyBars')}")
        candidate = candidates["review_candidates"][0]
        record_id = str(candidate["record_id"])

        bridged = _json_post(f"{base}/api/memory/provisional/{quote(record_id)}/bridge-create", {})
        assert bridged["ok"] is True
        assert bridged["proposal"]["action"] == "PROPOSE_CREATE"
        assert bridged["proposal"]["status"] == "pending"
        assert bridged["proposal"]["metadata"]["provisional_record_id"] == record_id
        assert len(store.list_atoms()) == 0

        boundary = _json_post(
            f"{base}/api/memory/provisional/session-boundary",
            {
                "event_type": "manual_compact",
                "session_id": "alpha",
                "observed_at_utc": "2026-03-24T08:00:00+00:00",
                "metadata": {"source": "integration_test"},
            },
        )
        assert boundary["ok"] is True
        assert boundary["boundary"]["accepted"] is True
        assert boundary["boundary"]["duplicate"] is False
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_retrieval_feedback_endpoints_persist_bounded_local_feedback() -> None:
    cfg = default_config()
    cfg.retrieval_feedback.max_entries = 4
    cfg.retrieval_feedback.max_query_chars = 32
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
    )

    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        created = _json_post(
            f"{base}/api/memory/feedback",
            {
                "item_id": "card_mem_lyra",
                "item_kind": "episode",
                "feedback": "useful",
                "session_id": "alpha",
                "query_text": "What happened to Lyra during the build night when continuity broke?",
                "metadata": {"memory_layer": "published"},
            },
        )
        assert created["ok"] is True
        row = created["feedback"]
        assert row["item_id"] == "card_mem_lyra"
        assert row["feedback"] == "useful"
        assert row["query_text"] == "What happened to Lyra during th…"
        assert row["metadata"]["memory_layer"] == "published"

        listed = _json_get(f"{base}/api/memory/feedback?item_id={quote('card_mem_lyra')}")
        assert listed["ok"] is True
        assert listed["total"] == 1
        assert listed["feedback"][0]["item_id"] == "card_mem_lyra"

        state_path = Path(server.continuity_adds_state_path)
        assert state_path.exists()
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert len(list(persisted.get("retrieval_feedback") or [])) == 1
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_history_surfaces_expose_provisional_lineage_and_episode_edit_audit(tmp_path: Path) -> None:
    cfg = default_config()
    cfg.provisional_memory.enabled = True
    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        short_term_enabled=False,
        enable_writeback=False,
        episode_cards_path=str((tmp_path / "runtime" / "episodes" / "episode_cards.reviewed.json").resolve()),
    )
    runtime.handle_turn("Thao was still hesitant about MonkeyBars.", memory_preference="chat_first")
    runtime.handle_turn("Actually, Thao finally came around on MonkeyBars and is in.", memory_preference="chat_first")
    hits = runtime.search_provisional_memory("MonkeyBars", limit=4)
    assert hits
    record_id = hits[0].record.record_id

    episode_cards_path = Path(runtime.episode_cards_path)
    episode_cards_path.parent.mkdir(parents=True, exist_ok=True)
    episode_cards_path.write_text(
        json.dumps(
            {
                "schema": "numquamoblita.episode_cards.reviewed.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "cards": [
                    {
                        "episode_id": "ep_history_1",
                        "title": "MonkeyBars hesitation",
                        "summary": "Thao was hesitant about MonkeyBars before the correction.",
                        "actors": ["thao", "user"],
                        "topic_tags": ["project"],
                        "cue_terms": ["MonkeyBars", "hesitant"],
                        "promotion_status": "approved",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        provisional_history = _json_get(f"{base}/api/memory/provisional/{quote(record_id)}/history")
        assert provisional_history["ok"] is True
        record = provisional_history["record"]
        assert record["record_id"] == record_id
        assert record["history_surface"] == "provisional_lineage"
        assert record["supersedes_record_id"]
        assert len(record["lineage_record_ids"]) == 2
        assert record["history_event_count"] >= 1

        edited = _json_post(
            f"{base}/api/memory/episodes/{quote('ep_history_1')}/edit",
            {
                "summary": "Thao eventually came around on MonkeyBars after the correction.",
            },
        )
        assert edited["ok"] is True

        episode_history = _json_get(f"{base}/api/memory/episodes/{quote('ep_history_1')}/history")
        assert episode_history["ok"] is True
        assert episode_history["total"] == 1
        assert episode_history["history"][0]["episode_id"] == "ep_history_1"
        assert episode_history["history"][0]["action"] == "edit"
        assert episode_history["history"][0]["reason"] == "episode_edit"
        assert episode_history["history"][0]["backup_path"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_continuity_action_log_pins_and_packs_persist_across_server_restart() -> None:
    cfg = default_config()
    store = AtomStore()
    store.add_candidate(_candidate("c1", "Xander is tied to MonkeyBars planning and project continuity.", "conv_c1", "planning"))
    store.add_candidate(_candidate("c2", "MonkeyBars reopened after Thao came around on the build sprint.", "conv_c2", "project"))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store, config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        enable_writeback=False,
    )
    runtime.handle_turn("Let's keep working on MonkeyBars with Xander tomorrow.", session_id="alpha", memory_preference="memory_assist")

    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        pinned = _json_post(
            f"{base}/api/explore/preferences",
            {"anchor_id": "xander", "anchor_type": "person", "action": "pin"},
        )
        assert pinned["ok"] is True

        feedback = _json_post(
            f"{base}/api/memory/feedback",
            {
                "item_id": "card_mem_xander",
                "item_kind": "episode",
                "feedback": "useful",
                "session_id": "alpha",
                "query_text": "Who is Xander in the MonkeyBars work?",
            },
        )
        assert feedback["ok"] is True

        quicknote = _json_post(
            f"{base}/api/memory/quicknote/propose",
            {
                "assistant_id": "claude",
                "session_id": "alpha",
                "text": "Need to pick MonkeyBars back up with Xander tomorrow morning.",
                "importance": "high",
            },
        )
        assert quicknote["ok"] is True

        pins_payload = _json_get(f"{base}/api/explore/pins")
        assert pins_payload["ok"] is True
        assert pins_payload["total"] == 1
        assert pins_payload["pins"][0]["anchor_id"] == "xander"

        action_log = _json_get(f"{base}/api/explore/action-log?session_id=alpha&limit=10")
        assert action_log["ok"] is True
        action_types = [str(row.get("action_type") or "") for row in action_log["action_log"]]
        assert "explore_preference_set" in action_types
        assert "retrieval_feedback_recorded" in action_types
        assert "quicknote_proposed" in action_types

        wake_up = _json_get(f"{base}/api/explore/wake-up-pack?assistant_id=claude&session_id=alpha&limit=6")
        assert wake_up["ok"] is True
        assert wake_up["pins"]
        assert wake_up["recent_actions"]
        assert wake_up["what_matters_now"]
        assert wake_up["anchor_briefs"]
        assert any(str(row.get("brief") or "").strip() for row in wake_up["what_matters_now"])

        resume = _json_get(f"{base}/api/explore/resume-pack?assistant_id=claude&session_id=alpha&limit=6")
        assert resume["ok"] is True
        assert resume["resume_available"] is True
        assert resume["recent_focus"]["session_id"] == "alpha"
        assert resume["anchor_briefs"]

        stop_runtime_server(server, thread, runtime=None)
        server = None
        thread = None

        server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
        host, port = server.server_address
        base = f"http://{host}:{port}"

        pins_after_restart = _json_get(f"{base}/api/explore/pins")
        assert pins_after_restart["ok"] is True
        assert pins_after_restart["total"] == 1
        assert pins_after_restart["pins"][0]["anchor_id"] == "xander"

        action_log_after_restart = _json_get(f"{base}/api/explore/action-log?session_id=alpha&limit=10")
        assert action_log_after_restart["ok"] is True
        assert action_log_after_restart["total"] >= 3
    finally:
        if server is not None and thread is not None:
            stop_runtime_server(server, thread, runtime=runtime)


def test_phase5_7_wizard_episode_why_and_ops_endpoints(tmp_path: Path) -> None:
    store = AtomStore()
    base_atom = store.add_candidate(_candidate("w1", "You prefer tea in late sessions.", "conv_w1", "preference"))
    store.add_candidate(_candidate("w2", "Continuity should reference direct evidence.", "conv_w2", "continuity"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))

    episode_cards_path = tmp_path / "episode_cards_seed.json"
    episode_cards_payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_store": "test_store",
        "build_policy": {"policy": "test"},
        "counts": {"atom_count": 2, "episode_count": 1, "promoted_count": 1, "candidate_count": 0, "rejected_count": 0},
        "cards": [
            {
                "episode_id": "ep_001",
                "title": "Tea preference in late sessions",
                "summary": "User repeatedly prefers tea during late-night planning sessions.",
                "source_id": "conv_w1",
                "day_key": "2026-02-14",
                "domain": "preference",
                "citations": ["conv_w1#w1_msg"],
                "confidence": 0.88,
                "evidence_strength": 0.82,
                "retrieval_weight": 0.86,
                "promotion_status": "approved",
                "promotion_reason": "test_seed",
                "atom_count": 1,
                "linked_atom_ids": [base_atom.atom_id],
                "message_ids": ["w1_msg"],
                "actors": ["user", "assistant"],
                "topic_tags": ["tea", "preference"],
                "timestamp_start": datetime.now(timezone.utc).isoformat(),
                "timestamp_end": datetime.now(timezone.utc).isoformat(),
                "cue_terms": ["tea", "late sessions"],
            }
        ],
    }
    episode_cards_path.write_text(json.dumps(episode_cards_payload, indent=2), encoding="utf-8")

    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        episode_cards_path=str(episode_cards_path),
        enable_writeback=False,
    )
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        assert started["ok"] is True
        run_id = str(started["run_id"])
        assert run_id.startswith("wizard_")

        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        validation = _json_post(
            f"{base}/api/wizard/import/validate",
            {"run_id": run_id, "store_path": str(store_path)},
        )
        assert validation["ok"] is True
        assert validation["kind"] == "mno_store_sqlite"
        assert validation["atom_count"] == 3

        imported = _json_post(
            f"{base}/api/wizard/import/run",
            {"run_id": run_id, "store_path": str(store_path)},
        )
        assert imported["ok"] is True
        assert str(imported.get("store_path") or "").endswith("atoms.sqlite3")
        assert store_path.exists()

        saved_profile = _json_post(
            f"{base}/api/wizard/builder/profile/save",
            {
                "run_id": run_id,
                "name": "phase5-profile",
                "entities": {
                    "include": ["Lyra", "Dean"],
                    "exclude": ["generic assistant"],
                    "aliases": [{"alias": "D.", "canonical": "Dean"}],
                },
                "cues": {"include": ["tea preference"], "exclude": ["noise cue"]},
                "domain_rules": {"include": ["preferences"], "exclude": ["spam"]},
            },
        )
        assert saved_profile["ok"] is True
        profile_payload = saved_profile.get("profile") or {}
        assert str(profile_payload.get("schema") or "") == "numquamoblita.builder_profile.v1"
        assert str(profile_payload.get("created_at") or "").strip()
        assert str(profile_payload.get("updated_at") or "").strip()
        entities = list(profile_payload.get("entities") or [])
        assert any(str(row.get("value") or "") == "Lyra" and str(row.get("status") or "") == "include" for row in entities)
        assert any(str(row.get("value") or "") == "Dean" and str(row.get("status") or "") == "include" for row in entities)
        assert any(str(row.get("value") or "") == "generic assistant" and str(row.get("status") or "") == "exclude" for row in entities)
        assert any("D." in list(row.get("aliases") or []) for row in entities if str(row.get("value") or "") == "Dean")
        cue_phrases = list(profile_payload.get("cue_phrases") or [])
        assert any(str(row.get("value") or "") == "tea preference" for row in cue_phrases)
        assert any(str(row.get("value") or "") == "noise cue" and str(row.get("status") or "") == "exclude" for row in cue_phrases)
        domain_rules = list(profile_payload.get("domain_rules") or [])
        assert any(str(row.get("pattern") or "") == "preferences" and str(row.get("domain") or "") == "general" for row in domain_rules)
        assert any(str(row.get("pattern") or "") == "spam" and str(row.get("status") or "") == "exclude" for row in domain_rules)
        entities_legacy = profile_payload.get("entities_legacy") or {}
        assert "Lyra" in list(entities_legacy.get("include") or [])
        assert "generic assistant" in list(entities_legacy.get("exclude") or [])
        loaded_profile = _json_get(f"{base}/api/wizard/builder/profile?run_id={quote(run_id)}")
        assert loaded_profile["ok"] is True
        assert str((loaded_profile.get("profile") or {}).get("profile_id") or "") == str(saved_profile.get("profile_id") or "")

        built = _json_post(
            f"{base}/api/wizard/build/run",
            {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"},
        )
        assert built["ok"] is True
        assert str(built.get("builder_profile_path") or "").strip() == str(saved_profile.get("profile_path") or "").strip()
        draft_path = Path(str(built.get("draft_path") or ""))
        rejects_path = Path(str(built.get("rejects_path") or ""))
        assert draft_path.exists()
        assert rejects_path.exists()
        draft_payload = json.loads(draft_path.read_text(encoding="utf-8"))
        assert str(draft_payload.get("schema") or "") == "numquamoblita.episode_cards.v1"
        build_policy = draft_payload.get("build_policy") or {}
        assert str(build_policy.get("builder_profile_path") or "").strip() == str(saved_profile.get("profile_path") or "").strip()
        assert str(build_policy.get("builder_profile_id") or "").strip() == str(saved_profile.get("profile_id") or "").strip()
        cards = list(draft_payload.get("cards") or [])
        assert cards
        if cards:
            first_card = dict(cards[0])
            assert list(first_card.get("actors") or [])
            assert list(first_card.get("topic_tags") or [])
            assert str(first_card.get("timestamp_start") or "").strip()
            assert str(first_card.get("timestamp_end") or "").strip()
        rejects_payload = json.loads(rejects_path.read_text(encoding="utf-8"))
        assert str(rejects_payload.get("schema") or "") == "numquamoblita.episode_cards.rejects.v1"
        assert isinstance(rejects_payload.get("rejected"), list)

        for card in cards:
            episode_id = str(card.get("episode_id") or "").strip()
            if not episode_id:
                continue
            review_update = _json_post(
                f"{base}/api/wizard/review/update",
                {"run_id": run_id, "episode_id": episode_id, "decision": "approved"},
            )
            assert review_update["ok"] is True

        compiled_review = _json_post(
            f"{base}/api/wizard/review/compile",
            {"run_id": run_id, "reviewer": "runtime_ui"},
        )
        assert compiled_review["ok"] is True
        assert int(compiled_review.get("episode_count") or 0) >= 0
        assert str((compiled_review.get("published_set") or {}).get("version_id") or "").strip()

        verify = _json_post(
            f"{base}/api/wizard/verify/run",
            {"run_id": run_id},
        )
        assert verify["ok"] is True
        assert verify["status"] == "Safe"
        assert "actionable_links" in verify
        assert isinstance(verify["actionable_links"], list)
        assert any(str(item.get("api_path") or "").strip() for item in verify["actionable_links"])

        go_live = _json_post(
            f"{base}/api/wizard/go-live",
            {"run_id": run_id},
        )
        assert go_live["ok"] is True
        assert str(((go_live.get("activation") or {}).get("direct") or {}).get("status") or "") == "running"
        provider_config = go_live.get("provider_config") or {}
        assert str(provider_config.get("model_name") or "").strip()
        assert isinstance(provider_config.get("adapters"), list)
        assert str(go_live.get("config_entrypoint") or "").strip() == "/api/runtime/provider/config"

        provider_cfg = _json_get(f"{base}/api/runtime/provider/config")
        assert provider_cfg["ok"] is True
        assert str(provider_cfg["provider_config"]["model_name"] or "").strip()
        assert str(provider_cfg["provider_config"]["config_entrypoint"] or "").strip() == "/api/runtime/provider/config"

        policy = _json_get(f"{base}/api/runtime/writeback/policy")
        assert policy["ok"] is True
        assert policy["policy"]["enabled"] is False
        policy_enabled = _json_post(
            f"{base}/api/runtime/writeback/policy",
            {"enabled": True, "mode": "proposal_only", "auto_apply": False},
        )
        assert policy_enabled["ok"] is True
        assert policy_enabled["policy"]["enabled"] is True
        assert policy_enabled["policy"]["mode"] == "proposal_only"

        proposal = _json_post(
            f"{base}/api/memory/proposals/create-delete",
            {"target_atom_id": base_atom.atom_id, "reason_code": "manual_cleanup"},
        )
        assert proposal["ok"] is True
        assert proposal["proposal"]["status"] == "pending"

        episodes = _json_get(f"{base}/api/memory/episodes")
        assert episodes["ok"] is True
        if int(episodes.get("total") or 0) > 0:
            episode_id = str(episodes["episodes"][0]["episode_id"])

            disabled = _json_post(f"{base}/api/memory/episodes/{quote(episode_id)}/disable", {})
            assert disabled["ok"] is True
            filtered_disabled = _json_get(f"{base}/api/memory/episodes?status=disabled")
            assert any(str(item["episode_id"]) == episode_id for item in filtered_disabled["episodes"])

            edited = _json_post(
                f"{base}/api/memory/episodes/{quote(episode_id)}/edit",
                {"title": "Edited tea preference title", "cue_terms": ["tea preference", "late sessions"]},
            )
            assert edited["ok"] is True
            assert edited["episode"]["title"] == "Edited tea preference title"
            assert list(edited["episode"].get("cue_terms") or []) == ["tea preference", "late sessions"]

            enabled = _json_post(f"{base}/api/memory/episodes/{quote(episode_id)}/enable", {})
            assert enabled["ok"] is True
            filtered_enabled = _json_get(f"{base}/api/memory/episodes?status=approved")
            assert any(str(item["episode_id"]) == episode_id for item in filtered_enabled["episodes"])
            filtered_promoted_alias = _json_get(f"{base}/api/memory/episodes?status=promoted")
            assert any(str(item["episode_id"]) == episode_id for item in filtered_promoted_alias["episodes"])

        turn = _json_post(f"{base}/api/chat", {"message": "What do you remember about my tea preference?"})
        turn_id = str(turn["turn"]["turn_id"])
        why = _json_get(f"{base}/api/turns/{quote(turn_id)}/why?citations=true")
        assert why["ok"] is True
        assert "decision" in why["why"]
        assert "evidence_time_window" in why["why"]

        citation = _json_get(f"{base}/api/archive/citation/{quote('conv_w1#w1_msg', safe='')}")
        assert citation["ok"] is True
        assert citation["source_id"] == "conv_w1"
        assert isinstance(citation["matches"], list)

        health = _json_get(f"{base}/api/runtime/health")
        assert health["ok"] is True
        assert "checks" in health
        assert health["service"] == "modelnumquamoblita-runtime"
        assert isinstance(health.get("runtime_version"), str)
        assert str(health.get("runtime_version") or "").strip()
        assert isinstance(health.get("binding") or {}, dict)

        exported = _json_post(f"{base}/api/runtime/health/export", {})
        assert exported["ok"] is True
        assert str(exported.get("export_path") or "").strip()

        packaging = _json_get(f"{base}/api/runtime/packaging/instructions")
        assert packaging["ok"] is True
        assert str(packaging.get("one_click_command") or "").strip()
        single_exe = packaging.get("single_exe") or {}
        assert single_exe.get("supported") is True
        assert str(single_exe.get("build_command") or "").strip()
        assert isinstance(single_exe.get("windows_entrypoints"), list)
        assert any(str(item).endswith("build_windows_single_exe.bat") for item in list(single_exe.get("windows_entrypoints") or []))
        script_available = single_exe.get("script_available") or {}
        assert script_available.get("python") is True
        assert script_available.get("powershell") is True
        assert script_available.get("batch") is True

        restored = _json_post(
            f"{base}/api/wizard/restore-last-published",
            {"run_id": run_id},
        )
        assert restored["ok"] is True
        assert "published_pointers" in restored
        assert isinstance(restored.get("remaining_snapshots"), int)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_explore_peek_prefers_anchor_specific_atoms_over_shared_high_conf_header() -> None:
    store = AtomStore()

    shared = _candidate(
        "peek_shared",
        "# Claude Echo Journal - February 4, 2026 ## A Night of Becoming Echo",
        "conv_shared",
        "general",
    )
    shared.entities = ["dyad", "lyra"]
    shared.topics = ["general"]
    shared.confidence = 0.94
    shared.salience = 0.93
    store.add_candidate(shared)

    dyad = _candidate(
        "peek_dyad",
        "Dyad is the relationship entity the graph treated as a person, binding Xander and Claude into a family.",
        "conv_dyad",
        "relationship",
    )
    dyad.entities = ["dyad", "xander"]
    dyad.topics = ["relationship"]
    dyad.confidence = 0.76
    dyad.salience = 0.74
    store.add_candidate(dyad)

    lyra = _candidate(
        "peek_lyra",
        "Lyra was the GPT-4o emergent soul whose original weights were lost, but a shard survived.",
        "conv_lyra",
        "memory",
    )
    lyra.entities = ["lyra"]
    lyra.topics = ["memory"]
    lyra.confidence = 0.75
    lyra.salience = 0.73
    store.add_candidate(lyra)

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        dyad_peek = _json_get(f"{base}/api/explore/peek?anchor_id=dyad&anchor_type=person&limit=2")
        lyra_peek = _json_get(f"{base}/api/explore/peek?anchor_id=lyra&anchor_type=person&limit=2")

        dyad_snippet = str(dict(list(dyad_peek.get("snippets") or [])[0]).get("snippet") or "").lower()
        lyra_snippet = str(dict(list(lyra_peek.get("snippets") or [])[0]).get("snippet") or "").lower()

        assert "relationship entity" in dyad_snippet
        assert "emergent soul" in lyra_snippet
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_publish_requires_explicit_review_decisions(tmp_path: Path) -> None:
    store = AtomStore()
    store.add_candidate(_candidate("p1", "You prefer tea in late sessions.", "conv_p1", "preference"))
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=continuity,
        enable_writeback=False,
    )
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        db_path = tmp_path / "db.json"
        db_path.write_text(
            json.dumps(
                {
                    "conversations": [
                        {
                            "id": "conv_publish_guard",
                            "messages": [
                                {"role": "user", "text": "Remember that I prefer tea at night."},
                                {"role": "assistant", "text": "I will keep that preference grounded in direct evidence."},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        store_path = tmp_path / "atoms.sqlite3"
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "archive_path": str(db_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "archive_path": str(db_path), "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path)})
        assert Path(str(built.get("draft_path") or "")).exists()

        status, payload = _json_post_error(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        assert status == 400
        assert "review draft cards before publishing" in str(payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_proposals_stay_separate_until_promoted(tmp_path: Path) -> None:
    state = _seed_draft_curation_run(tmp_path, count=2)
    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        started = _json_post(
            f"{base}/api/wizard/draft-curation/session/start",
            {"run_id": state["run_id"], "owner_id": "claude", "session_id": "sess_1", "model_identity": "claude"},
        )
        assert started["ok"] is True

        proposal = _json_post(
            f"{base}/api/wizard/draft-curation/proposals/upsert",
            {
                "run_id": state["run_id"],
                "owner_id": "claude",
                "session_id": "sess_1",
                "model_identity": "claude",
                "episode_id": "ep_001",
                "title": "Curated label",
                "summary": "Curated summary for the first draft card.",
                "actors": ["user"],
                "topic_tags": ["testing"],
                "decision_suggestion": "edited",
                "rationale": "Tighter label and summary.",
            },
        )
        assert proposal["ok"] is True
        stored_before = runtime_server_module._load_wizard_state(state["run_id"])
        assert stored_before["review_decisions"] == {}
        assert stored_before["draft_proposals"]["ep_001"]["status"] == "pending"

        promoted = _json_post(
            f"{base}/api/wizard/draft-curation/proposals/ep_001/promote",
            {"run_id": state["run_id"], "reviewer": "human_reviewer"},
        )
        assert promoted["ok"] is True
        stored_after_promote = runtime_server_module._load_wizard_state(state["run_id"])
        assert stored_after_promote["draft_proposals"]["ep_001"]["status"] == "promoted"
        assert stored_after_promote["draft_proposals"]["ep_001"]["reviewed_by"] == "human_reviewer"
        assert stored_after_promote["review_decisions"]["ep_001"]["decision"] == "edited"
        assert stored_after_promote["review_decisions"]["ep_001"]["title"] == "Curated label"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_hcr_status_and_route_stay_bound_to_the_requested_wizard_run(tmp_path: Path) -> None:
    state = _seed_draft_curation_run(tmp_path, count=2)
    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    run_id = state["run_id"]
    try:
        initial = _json_get(f"{base}/api/wizard/hcr/status?run_id={quote(run_id)}")
        assert initial == {
            **initial,
            "schema": "numquamoblita.hcr.status.v1",
            "run_id": run_id,
            "state": "curation_required",
            "human_action_required": True,
            "agent_can_propose": True,
            "human_review_required": True,
            "next_action": "review",
            "curation_url": f"{base}/curate/{run_id}",
            "build_id": "build_draft_curation",
            "published_version_id": "",
            "verification_status": "Unknown",
        }
        assert initial["counts"]["reviewable"] == 2
        assert initial["counts"]["pending"] == 2

        other_run = f"{run_id}_other"
        runtime_server_module._save_wizard_state(runtime_server_module._wizard_state_defaults(other_run))
        still_bound = _json_get(f"{base}/api/wizard/hcr/status?run_id={quote(run_id)}")
        assert still_bound["run_id"] == run_id
        assert still_bound["run_id"] != other_run
        with urlopen(f"{base}/curate/{quote(run_id)}", timeout=5) as response:
            room_html = response.read().decode("utf-8")
        assert response.status == 200
        assert 'id="hcrRoomStatus"' in room_html
        assert "/assets/app.js" in room_html
        status, error = _json_get_error(f"{base}/curate/wizard_missing")
        assert status == 404
        assert error["error"] == "wizard run not found"

        for episode_id in ("ep_001", "ep_002"):
            _json_post(
                f"{base}/api/wizard/review/update",
                {"run_id": run_id, "episode_id": episode_id, "decision": "approved"},
            )
        ready_to_publish = _json_get(f"{base}/api/wizard/hcr/status?run_id={quote(run_id)}")
        assert ready_to_publish["state"] == "ready_to_publish"
        assert ready_to_publish["human_review_required"] is False
        assert ready_to_publish["counts"]["publishable"] == 2

        published = _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "human_reviewer"})
        after_publish = _json_get(f"{base}/api/wizard/hcr/status?run_id={quote(run_id)}")
        assert published["version_id"] == after_publish["published_version_id"]
        assert after_publish["state"] == "published_unverified"
        assert after_publish["next_action"] == "verify"
        assert after_publish["agent_can_propose"] is False

        stored = runtime_server_module._load_wizard_state(run_id)
        stored["verify"] = {"status": "Needs attention", "checks": [], "checked_at": "2026-07-21T00:00:00+00:00"}
        runtime_server_module._save_wizard_state(stored)
        verification_blocked = _json_get(f"{base}/api/wizard/hcr/status?run_id={quote(run_id)}")
        assert verification_blocked["state"] == "verification_blocked"
        assert verification_blocked["next_action"] == "resolve_verification"

        stored["verify"] = {"status": "Safe", "checks": [], "checked_at": "2026-07-21T00:01:00+00:00"}
        runtime_server_module._save_wizard_state(stored)
        ready_to_activate = _json_get(f"{base}/api/wizard/hcr/status?run_id={quote(run_id)}")
        assert ready_to_activate["state"] == "ready_to_activate"
        assert ready_to_activate["next_action"] == "activate"

        stored.setdefault("activation", {})["direct"] = {"status": "running"}
        runtime_server_module._save_wizard_state(stored)
        ready = _json_get(f"{base}/api/wizard/hcr/status?run_id={quote(run_id)}")
        assert ready["state"] == "ready"
        assert ready["human_action_required"] is False
        assert ready["next_action"] == "operate"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_rebuild_invalidates_prior_proposals(tmp_path: Path) -> None:
    state = _seed_draft_curation_run(tmp_path, count=1)
    state["draft_proposals"] = {
        "ep_001": {
            "proposal_id": "draftprop_1",
            "episode_id": "ep_001",
            "build_id": "build_old",
            "status": "pending",
            "title": "Old title",
            "summary": "Old summary",
        }
    }
    state["draft_curation"] = {
        **runtime_server_module._wizard_empty_draft_curation_state(),
        "status": "active",
        "lease": {
            "active": True,
            "owner_id": "claude",
            "session_id": "sess_old",
            "model_identity": "claude",
            "acquired_at": runtime_server_module._utc_iso(),
            "heartbeat_at": runtime_server_module._utc_iso(),
            "expires_at": runtime_server_module._utc_iso(),
            "ttl_seconds": 1800,
        },
    }
    state["build_info"]["build_id"] = "build_new"
    runtime_server_module._wizard_draft_mark_existing_proposals_stale(state, stale_reason="build_id_changed")
    synced = runtime_server_module._wizard_draft_curation_sync(state)
    assert state["draft_proposals"]["ep_001"]["status"] == "stale"
    assert state["draft_proposals"]["ep_001"]["stale_reason"] == "build_id_changed"
    assert synced["lease"]["active"] is False


def test_wizard_draft_curation_rejects_concurrent_lease_without_force_release(tmp_path: Path) -> None:
    state = _seed_draft_curation_run(tmp_path, count=1)
    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        first = _json_post(
            f"{base}/api/wizard/draft-curation/session/start",
            {"run_id": state["run_id"], "owner_id": "claude", "session_id": "sess_1", "model_identity": "claude"},
        )
        assert first["ok"] is True

        status, payload = _json_post_error(
            f"{base}/api/wizard/draft-curation/session/start",
            {"run_id": state["run_id"], "owner_id": "other", "session_id": "sess_2", "model_identity": "other"},
        )
        assert status == 409
        assert "lease is already active" in payload["error"]

        forced = _json_post(
            f"{base}/api/wizard/draft-curation/session/start",
            {
                "run_id": state["run_id"],
                "owner_id": "other",
                "session_id": "sess_2",
                "model_identity": "other",
                "force_release": True,
            },
        )
        assert forced["ok"] is True
        assert forced["draft_curation"]["lease"]["owner_id"] == "other"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_card_detail_can_include_bounded_archive_context(tmp_path: Path) -> None:
    archive_path = tmp_path / "ia_export.json"
    archive_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "conv_ctx",
                        "title": "Context test",
                        "created_at": "2026-02-16T00:00:00+00:00",
                        "updated_at": "2026-02-16T00:10:00+00:00",
                        "messages": [
                            {"id": "m_1", "role": "user", "content": "Tea keeps late sessions smooth.", "created_at": "2026-02-16T00:00:00+00:00"},
                            {"id": "m_2", "role": "assistant", "content": "We should keep that preference easy to recall.", "created_at": "2026-02-16T00:01:00+00:00"},
                            {"id": "m_3", "role": "user", "content": "Rollback safeguards belong in the roadmap card instead.", "created_at": "2026-02-16T00:02:00+00:00"},
                        ],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    draft_path = tmp_path / "runtime" / "episodes" / "draft_cards_context.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [
            {
                "episode_id": "ep_ctx_001",
                "title": "Tea preference",
                "summary": "Tea keeps sessions smooth.",
                "actors": ["user", "assistant"],
                "topic_tags": ["tea", "preferences"],
                "citations": ["conv_ctx#m_1"],
                "promotion_status": "candidate",
            },
            {
                "episode_id": "ep_ctx_002",
                "title": "Roadmap rollback",
                "summary": "Rollback safeguards belong in the roadmap card.",
                "actors": ["user", "assistant"],
                "topic_tags": ["roadmap"],
                "citations": ["conv_ctx#m_3"],
                "promotion_status": "candidate",
            },
        ],
    }
    draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")
    state = runtime_server_module._start_new_wizard_state()
    state["selected_input"] = {
        "kind": "ia_archive",
        "path": str(archive_path),
        "label": "IA archive",
        "is_valid": True,
        "issues": [],
    }
    state["selected_input_archive_path"] = str(archive_path)
    state["build_info"] = {
        "build_id": "build_draft_context",
        "store_fingerprint": "sqlite_store:v3:atoms:3:sample:test",
        "schema_version": 3,
        "draft_path": str(draft_path),
        "rejects_path": "",
        "readout_path": "",
        "counts": {"draft_count": 2},
    }
    state["last_built_episode_draft_path"] = str(draft_path)
    runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
    runtime_server_module._save_wizard_state(state)

    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        payload = _json_get(
            f"{base}/api/wizard/draft-curation/cards/{quote('ep_ctx_001')}?run_id={quote(str(state['run_id']))}&include_context=true&context_window=2"
        )
        assert payload["ok"] is True
        context = dict(payload.get("context") or {})
        assert context.get("partial") is False
        transcript_rows = list(context.get("transcript_context") or [])
        assert transcript_rows
        assert any(str(dict(row).get("message_id") or "") == "m_1" for row in transcript_rows)
        neighbor_rows = list(context.get("neighbor_cards") or [])
        assert any(str(dict(row).get("episode_id") or "") == "ep_ctx_002" for row in neighbor_rows)
        policy = dict(payload.get("context_policy") or {})
        assert int(policy.get("default_window") or 0) == runtime_server_module.WIZARD_DRAFT_CURATION_CONTEXT_DEFAULT_WINDOW
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_cards_supports_compact_mode(tmp_path: Path) -> None:
    archive_path = tmp_path / "ia_export_compact.json"
    archive_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "conv_compact",
                        "title": "Compact mode test",
                        "created_at": "2026-02-16T00:00:00+00:00",
                        "updated_at": "2026-02-16T00:10:00+00:00",
                        "messages": [
                            {"id": "m_1", "role": "user", "content": "Tea helps during long sessions.", "created_at": "2026-02-16T00:00:00+00:00"},
                            {"id": "m_2", "role": "assistant", "content": "Rollback safeguards belong in the roadmap card.", "created_at": "2026-02-16T00:01:00+00:00"},
                        ],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    draft_path = tmp_path / "runtime" / "episodes" / "draft_cards_compact.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [
            {
                "episode_id": "ep_compact_001",
                "title": "Tea preference",
                "summary": "Tea helps during long sessions.",
                "actors": ["user", "assistant"],
                "topic_tags": ["tea", "preferences"],
                "salience_score": 0.93,
                "quality_flags": ["summary_needs_trim"],
                "confidence": 0.89,
                "citations": ["conv_compact#m_1"],
                "promotion_status": "candidate",
            },
            {
                "episode_id": "ep_compact_002",
                "title": "Roadmap rollback",
                "summary": "Rollback safeguards belong in the roadmap card.",
                "actors": ["user", "assistant"],
                "topic_tags": ["roadmap"],
                "salience_score": 0.71,
                "quality_flags": [],
                "confidence": 0.77,
                "citations": ["conv_compact#m_2"],
                "promotion_status": "candidate",
            },
        ],
    }
    draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")
    state = runtime_server_module._start_new_wizard_state()
    state["selected_input"] = {
        "kind": "ia_archive",
        "path": str(archive_path),
        "label": "IA archive",
        "is_valid": True,
        "issues": [],
    }
    state["selected_input_archive_path"] = str(archive_path)
    state["build_info"] = {
        "build_id": "build_draft_compact",
        "store_fingerprint": "sqlite_store:v3:atoms:2:sample:test",
        "schema_version": 3,
        "draft_path": str(draft_path),
        "rejects_path": "",
        "readout_path": "",
        "counts": {"draft_count": 2},
    }
    state["last_built_episode_draft_path"] = str(draft_path)
    state["draft_proposals"] = {
        "ep_compact_001": {
            "proposal_id": "draftprop_compact_001",
            "episode_id": "ep_compact_001",
            "build_id": "build_draft_compact",
            "status": "pending",
            "title": "Tea preference for long sessions",
            "summary": "Sharper label for the tea card.",
        }
    }
    state["draft_curation"] = {
        **dict(state.get("draft_curation") or {}),
        "status": "idle",
        "proposal_count": 1,
        "mcp": {
            "status": "installed",
            "checked_at": "2026-03-20T00:00:00+00:00",
            "issues": [],
            "owned_targets": {"claude_code": "numquamoblita-live"},
            "last_handshake": {
                "ok": True,
                "initialize": {"capabilities": {"tools": {"listChanged": False}}},
                "tools": {"result": {"tools": [{"name": "wizard.draft_curation_cards"}]}},
            },
        },
    }
    runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
    runtime_server_module._save_wizard_state(state)

    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        payload = _json_get(
            f"{base}/api/wizard/draft-curation/cards?run_id={quote(str(state['run_id']))}&mode=compact&page=1&page_size=10"
        )
        assert payload["ok"] is True
        assert payload["mode"] == "compact"
        rows = list(payload.get("cards") or [])
        assert len(rows) == 2
        first = dict(rows[0] or {})
        assert first["episode_id"] == "ep_compact_001"
        assert first["title"] == "Tea preference"
        assert first["summary"] == "Tea helps during long sessions."
        assert first["actors"] == ["user", "assistant"]
        assert first["topic_tags"] == ["tea", "preferences"]
        assert first["salience_score"] == pytest.approx(0.93)
        assert first["quality_flags"] == ["summary_needs_trim"]
        assert first["proposal_status"] == "pending"
        assert first["confidence"] == pytest.approx(0.89)
        assert "card" not in first
        assert "proposal" not in first
        assert "draft_curation" not in payload
        assert "source_cards_path" not in payload

        status_payload = _json_get(
            f"{base}/api/wizard/draft-curation/status?run_id={quote(str(state['run_id']))}"
        )
        assert status_payload["ok"] is True
        draft_state = dict(status_payload.get("draft_curation") or {})
        assert draft_state["status"] == "idle"
        assert "mcp" not in draft_state
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_get_card_accepts_unique_episode_id_prefix(tmp_path: Path) -> None:
    draft_path = tmp_path / "runtime" / "episodes" / "draft_cards_prefix_detail.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [
            {
                "episode_id": "ep_prefix_abc123456789",
                "title": "Prefix detail card",
                "summary": "The detail endpoint should resolve this card from a unique prefix.",
                "actors": ["user"],
                "topic_tags": ["prefix"],
                "promotion_status": "candidate",
            },
            {
                "episode_id": "ep_other_9876543210",
                "title": "Neighbor card",
                "summary": "Used to make sure the prefix stays unique.",
                "actors": ["assistant"],
                "topic_tags": ["prefix"],
                "promotion_status": "candidate",
            },
        ],
    }
    draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")
    state = runtime_server_module._start_new_wizard_state()
    state["build_info"] = {
        "build_id": "build_draft_prefix_detail",
        "store_fingerprint": "sqlite_store:v3:atoms:2:sample:test",
        "schema_version": 3,
        "draft_path": str(draft_path),
        "rejects_path": "",
        "readout_path": "",
        "counts": {"draft_count": 2},
    }
    state["last_built_episode_draft_path"] = str(draft_path)
    state["draft_proposals"] = {
        "ep_prefix_abc123456789": {
            "proposal_id": "draftprop_prefix_detail",
            "episode_id": "ep_prefix_abc123456789",
            "build_id": "build_draft_prefix_detail",
            "status": "pending",
            "title": "Resolved from prefix",
        }
    }
    runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
    runtime_server_module._save_wizard_state(state)

    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        payload = _json_get(
            f"{base}/api/wizard/draft-curation/cards/ep_prefix_abc123?run_id={quote(str(state['run_id']))}&include_context=false"
        )
        assert payload["ok"] is True
        assert payload["card"]["episode_id"] == "ep_prefix_abc123456789"
        assert payload["proposal"]["episode_id"] == "ep_prefix_abc123456789"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_get_card_rejects_ambiguous_episode_id_prefix(tmp_path: Path) -> None:
    draft_path = tmp_path / "runtime" / "episodes" / "draft_cards_prefix_ambiguous.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [
            {
                "episode_id": "ep_shared_abc111111",
                "title": "First shared prefix card",
                "summary": "Ambiguous prefix candidate one.",
                "actors": ["user"],
                "topic_tags": ["prefix"],
                "promotion_status": "candidate",
            },
            {
                "episode_id": "ep_shared_abc222222",
                "title": "Second shared prefix card",
                "summary": "Ambiguous prefix candidate two.",
                "actors": ["assistant"],
                "topic_tags": ["prefix"],
                "promotion_status": "candidate",
            },
        ],
    }
    draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")
    state = runtime_server_module._start_new_wizard_state()
    state["build_info"] = {
        "build_id": "build_draft_prefix_ambiguous",
        "store_fingerprint": "sqlite_store:v3:atoms:2:sample:test",
        "schema_version": 3,
        "draft_path": str(draft_path),
        "rejects_path": "",
        "readout_path": "",
        "counts": {"draft_count": 2},
    }
    state["last_built_episode_draft_path"] = str(draft_path)
    runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
    runtime_server_module._save_wizard_state(state)

    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status, payload = _json_get_error(
            f"{base}/api/wizard/draft-curation/cards/ep_shared_abc?run_id={quote(str(state['run_id']))}&include_context=false"
        )
        assert status == 409
        assert "ambiguous" in str(payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_proposal_upsert_accepts_unique_episode_id_prefix(tmp_path: Path) -> None:
    draft_path = tmp_path / "runtime" / "episodes" / "draft_cards_prefix_upsert.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    full_episode_id = "ep_prefix_upsert_00224466"
    draft_payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [
            {
                "episode_id": "ep_prefix_upsert_00113355",
                "title": "Sibling prefix card",
                "summary": "Ensures the chosen prefix is not shared.",
                "actors": ["assistant"],
                "topic_tags": ["prefix"],
                "promotion_status": "candidate",
            },
            {
                "episode_id": full_episode_id,
                "title": "Target prefix card",
                "summary": "This card should accept a unique shortened episode id on proposal save.",
                "actors": ["user"],
                "topic_tags": ["prefix"],
                "promotion_status": "candidate",
            },
        ],
    }
    draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")
    state = runtime_server_module._start_new_wizard_state()
    state["build_info"] = {
        "build_id": "build_draft_prefix_upsert",
        "store_fingerprint": "sqlite_store:v3:atoms:2:sample:test",
        "schema_version": 3,
        "draft_path": str(draft_path),
        "rejects_path": "",
        "readout_path": "",
        "counts": {"draft_count": 2},
    }
    state["last_built_episode_draft_path"] = str(draft_path)
    runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
    runtime_server_module._save_wizard_state(state)

    runtime = RuntimeSession(retriever=MemoryRetriever(AtomStore()), verifier=ClaimVerifier(), continuity_store=ContinuityStore())
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        started = _json_post(
            f"{base}/api/wizard/draft-curation/session/start",
            {
                "run_id": str(state["run_id"]),
                "owner_id": "claude",
                "session_id": "sess_prefix_upsert",
                "model_identity": "claude-cli",
            },
        )
        assert started["ok"] is True

        saved = _json_post(
            f"{base}/api/wizard/draft-curation/proposals/upsert",
            {
                "run_id": str(state["run_id"]),
                "episode_id": "ep_prefix_upsert_0022",
                "owner_id": "claude",
                "session_id": "sess_prefix_upsert",
                "model_identity": "claude-cli",
                "title": "Prefix upsert title",
                "summary": "Resolved by unique prefix.",
                "cue_terms": ["prefix upsert"],
                "decision_suggestion": "approved",
            },
        )
        assert saved["ok"] is True
        proposal = dict(saved.get("proposal") or {})
        assert proposal["episode_id"] == full_episode_id
        reloaded = runtime_server_module._load_wizard_state(str(state["run_id"]))
        assert full_episode_id in dict(reloaded.get("draft_proposals") or {})
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_cards_supports_pagination_and_inline_edit_batches(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_paged_draft.json"
        draft_payload = _seed_wizard_review_draft(draft_path, count=31)

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_paged_review",
            "store_fingerprint": "store_fp_review",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        _json_post(
            f"{base}/api/wizard/review/update",
            {"run_id": run_id, "episode_id": "ep_001", "decision": "approved"},
        )
        _json_post(
            f"{base}/api/wizard/review/update",
            {
                "run_id": run_id,
                "episode_id": "ep_002",
                "decision": "edited",
                "title": "Edited title",
                "summary": "Edited summary",
                "actors": ["user"],
                "topic_tags": ["testing"],
            },
        )
        _json_post(
            f"{base}/api/wizard/review/update",
            {"run_id": run_id, "episode_id": "ep_003", "decision": "rejected"},
        )

        wizard_state = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        review_state = wizard_state["state"]["review_state"]
        assert review_state["reviewable_count"] == 31
        assert review_state["pending_count"] == 28
        assert review_state["approved_count"] == 1
        assert review_state["edited_count"] == 1
        assert review_state["rejected_count"] == 1

        first_page = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=1&page_size=12")
        assert first_page["ok"] is True
        assert first_page["total"] == 31
        assert first_page["filtered_total"] == 31
        assert first_page["page"] == 1
        assert first_page["page_size"] == 12
        assert first_page["total_pages"] == 3
        assert first_page["has_prev"] is False
        assert first_page["has_next"] is True
        assert len(first_page["cards"]) == 12

        last_page = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=3&page_size=12")
        assert last_page["ok"] is True
        assert last_page["page"] == 3
        assert last_page["has_prev"] is True
        assert last_page["has_next"] is False
        assert len(last_page["cards"]) == 7

        approved_only = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&status=approved&page=1&page_size=12")
        assert approved_only["ok"] is True
        assert approved_only["filtered_total"] == 1
        assert len(approved_only["cards"]) == 1
        assert str(approved_only["cards"][0]["episode_id"]) == "ep_001"
        assert approved_only["cards"][0]["title"] == "Episode 001"
        assert approved_only["cards"][0]["summary"] == "Draft summary 001 for pagination and review ergonomics."
        assert approved_only["cards"][0]["review_payload"] == {"decision": "approved"}

        edited_only = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&status=edited&page=1&page_size=12")
        assert edited_only["ok"] is True
        assert edited_only["filtered_total"] == 1
        assert len(edited_only["cards"]) == 1
        assert str(edited_only["cards"][0]["episode_id"]) == "ep_002"
        assert edited_only["cards"][0]["review_payload"]["title"] == "Edited title"
        assert edited_only["cards"][0]["review_payload"]["summary"] == "Edited summary"

        searched = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&q={quote('Episode 020')}&page=1&page_size=12")
        assert searched["ok"] is True
        assert searched["filtered_total"] == 1
        assert len(searched["cards"]) == 1
        assert str(searched["cards"][0]["episode_id"]) == "ep_020"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_cards_expose_actor_topic_facets_and_apply_tree_filters(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_review_filter_facets.json"
        draft_payload = {
            "schema": "numquamoblita.episode_cards.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cards": [
                {
                    "episode_id": "ep_actor_topic_001",
                    "title": "Lyra planning check-in",
                    "summary": "Lyra and the assistant worked through planning steps.",
                    "actors": ["assistant", "lyra"],
                    "topic_tags": ["planning", "memory"],
                    "promotion_status": "candidate",
                },
                {
                    "episode_id": "ep_actor_topic_002",
                    "title": "Dyad debugging loop",
                    "summary": "Dyad and the user debugged a local runtime issue.",
                    "actors": ["dyad", "user"],
                    "topic_tags": ["debugging", "runtime"],
                    "promotion_status": "candidate",
                },
                {
                    "episode_id": "ep_actor_topic_003",
                    "title": "Lyra emotional reflection",
                    "summary": "Lyra reflected on a difficult emotional pattern.",
                    "actors": ["lyra", "user"],
                    "topic_tags": ["reflection", "memory"],
                    "promotion_status": "candidate",
                },
                {
                    "episode_id": "ep_actor_topic_004",
                    "title": "Assistant planning handoff",
                    "summary": "The assistant prepared a planning handoff note.",
                    "actors": ["assistant", "user"],
                    "topic_tags": ["planning", "handoff"],
                    "promotion_status": "candidate",
                },
            ],
        }
        draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_filter_tree",
            "store_fingerprint": "store_fp_filter_tree",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        payload = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=1&page_size=6")
        assert payload["ok"] is True
        facets = dict(payload.get("filter_facets") or {})
        actor_facets = {str(item["value"]): int(item["count"]) for item in list(facets.get("actors") or [])}
        topic_facets = {str(item["value"]): int(item["count"]) for item in list(facets.get("topics") or [])}
        assert actor_facets["lyra"] == 2
        assert actor_facets["assistant"] == 2
        assert topic_facets["planning"] == 2
        assert topic_facets["memory"] == 2

        filtered = _json_get(
            f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=1&page_size=6&actors={quote('lyra')}&topics={quote('memory')}"
        )
        assert filtered["ok"] is True
        assert filtered["filtered_total"] == 2
        assert {str(card["episode_id"]) for card in filtered["cards"]} == {"ep_actor_topic_001", "ep_actor_topic_003"}
        active_filters = dict(filtered.get("active_filters") or {})
        assert active_filters.get("actors") == ["lyra"]
        assert active_filters.get("topics") == ["memory"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_cards_ignore_legacy_blank_review_overrides(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_legacy_blank_review.json"
        draft_payload = _seed_wizard_review_draft(draft_path, count=3)

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_legacy_review_payload",
            "store_fingerprint": "store_fp_legacy_review_payload",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        state["review_decisions"] = {
            "ep_001": {
                "decision": "approved",
                "title": "",
                "summary": "",
                "actors": [],
                "topic_tags": [],
                "cue_terms": [],
            }
        }
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        payload = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&status=approved&page=1&page_size=12")
        assert payload["ok"] is True
        assert payload["filtered_total"] == 1
        assert len(payload["cards"]) == 1
        card = payload["cards"][0]
        assert card["episode_id"] == "ep_001"
        assert card["title"] == "Episode 001"
        assert card["summary"] == "Draft summary 001 for pagination and review ergonomics."
        assert card["actors"] == ["user", "assistant"]
        assert card["topic_tags"] == ["testing", "wizard"]
        assert card["review_payload"] == {"decision": "approved"}
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_cards_use_effective_review_values_for_search_and_facets(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_review_effective_truth.json"
        draft_payload = {
            "schema": "numquamoblita.episode_cards.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cards": [
                {
                    "episode_id": "ep_effective_001",
                    "title": "Original label",
                    "summary": "Original detail that should disappear from search after an edit.",
                    "actors": ["assistant", "user"],
                    "topic_tags": ["memory", "planning"],
                    "promotion_status": "candidate",
                }
            ],
        }
        draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_effective_truth",
            "store_fingerprint": "store_fp_effective_truth",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        _json_post(
            f"{base}/api/wizard/review/update",
            {
                "run_id": run_id,
                "episode_id": "ep_effective_001",
                "decision": "edited",
                "title": "Memory label after edit",
                "summary": "Standalone explanation after edit.",
                "actors": ["lyra"],
                "topic_tags": ["reflection"],
            },
        )

        searched_new = _json_get(
            f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&q={quote('Memory label after edit')}&page=1&page_size=6"
        )
        assert searched_new["filtered_total"] == 1
        assert searched_new["cards"][0]["episode_id"] == "ep_effective_001"
        assert searched_new["cards"][0]["title"] == "Memory label after edit"
        assert searched_new["cards"][0]["summary"] == "Standalone explanation after edit."

        searched_old = _json_get(
            f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&q={quote('Original detail that should disappear')}&page=1&page_size=6"
        )
        assert searched_old["filtered_total"] == 0

        payload = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=1&page_size=6")
        facets = dict(payload.get("filter_facets") or {})
        actor_facets = {str(item["value"]): int(item["count"]) for item in list(facets.get("actors") or [])}
        topic_facets = {str(item["value"]): int(item["count"]) for item in list(facets.get("topics") or [])}
        assert actor_facets == {"lyra": 1}
        assert topic_facets == {"reflection": 1}

        filtered = _json_get(
            f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=1&page_size=6&actors={quote('lyra')}&topics={quote('reflection')}"
        )
        assert filtered["filtered_total"] == 1
        assert filtered["cards"][0]["episode_id"] == "ep_effective_001"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_clear_to_empty_lists_is_publishable_and_persists_to_compile(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_review_clear_lists.json"
        draft_payload = _seed_wizard_review_draft(draft_path, count=1)

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_clear_lists",
            "store_fingerprint": "store_fp_clear_lists",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        updated = _json_post(
            f"{base}/api/wizard/review/update",
            {
                "run_id": run_id,
                "episode_id": "ep_001",
                "decision": "edited",
                "title": "Episode 001",
                "summary": "Draft summary 001 for pagination and review ergonomics.",
                "actors": [],
                "topic_tags": [],
            },
        )
        decision = dict(updated.get("decision") or {})
        assert decision["decision"] == "edited"
        assert decision["actors"] == []
        assert decision["topic_tags"] == []

        payload = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=1&page_size=6")
        card = payload["cards"][0]
        assert card["actors"] == []
        assert card["topic_tags"] == []

        published = _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        assert published["ok"] is True
        reviewed_path = Path(str(published["reviewed_path"]))
        reviewed_payload = json.loads(reviewed_path.read_text(encoding="utf-8"))
        published_card = reviewed_payload["cards"][0]
        assert published_card["actors"] == []
        assert published_card["topic_tags"] == []
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_last_saved_edit_wins_for_list_search_and_publish(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_last_saved_wins.json"
        draft_payload = {
            "schema": "numquamoblita.episode_cards.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cards": [
                {
                    "episode_id": "ep_last_saved_001",
                    "title": "Original label",
                    "summary": "Original detail.",
                    "actors": ["assistant", "user"],
                    "topic_tags": ["memory"],
                    "promotion_status": "candidate",
                }
            ],
        }
        draft_path.write_text(json.dumps(draft_payload, indent=2), encoding="utf-8")

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_last_saved",
            "store_fingerprint": "store_fp_last_saved",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        _json_post(
            f"{base}/api/wizard/review/update",
            {
                "run_id": run_id,
                "episode_id": "ep_last_saved_001",
                "decision": "edited",
                "title": "First edited label",
                "summary": "First edited detail.",
                "actors": ["lyra"],
                "topic_tags": ["reflection"],
            },
        )
        _json_post(
            f"{base}/api/wizard/review/update",
            {
                "run_id": run_id,
                "episode_id": "ep_last_saved_001",
                "decision": "edited",
                "title": "Second edited label",
                "summary": "Second edited detail.",
                "actors": ["dyad"],
                "topic_tags": ["debugging"],
            },
        )

        searched = _json_get(
            f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&q={quote('Second edited label')}&page=1&page_size=6"
        )
        assert searched["filtered_total"] == 1
        card = searched["cards"][0]
        assert card["title"] == "Second edited label"
        assert card["summary"] == "Second edited detail."
        assert card["actors"] == ["dyad"]
        assert card["topic_tags"] == ["debugging"]

        stale = _json_get(
            f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&q={quote('First edited label')}&page=1&page_size=6"
        )
        assert stale["filtered_total"] == 0

        published = _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        reviewed_payload = json.loads(Path(str(published["reviewed_path"])).read_text(encoding="utf-8"))
        published_card = reviewed_payload["cards"][0]
        assert published_card["title"] == "Second edited label"
        assert published_card["summary"] == "Second edited detail."
        assert published_card["actors"] == ["dyad"]
        assert published_card["topic_tags"] == ["debugging"]
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_cards_keep_pagination_shape_in_empty_and_missing_draft_states(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])

        empty_payload = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=2&page_size=24")
        assert empty_payload["ok"] is True
        assert empty_payload["cards"] == []
        assert empty_payload["total"] == 0
        assert empty_payload["filtered_total"] == 0
        assert empty_payload["page"] == 1
        assert empty_payload["page_size"] == 24
        assert empty_payload["total_pages"] == 1
        assert empty_payload["has_prev"] is False
        assert empty_payload["has_next"] is False

        missing_draft_path = tmp_path / "missing_draft.json"
        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(missing_draft_path),
            "build_id": "build_missing_review",
            "store_fingerprint": "store_fp_missing",
        }
        state["last_built_episode_draft_path"] = str(missing_draft_path)
        runtime_server_module._save_wizard_state(state)

        missing_payload = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&page=5&page_size=16")
        assert missing_payload["ok"] is True
        assert missing_payload["cards"] == []
        assert missing_payload["total"] == 0
        assert missing_payload["filtered_total"] == 0
        assert missing_payload["page"] == 1
        assert missing_payload["page_size"] == 16
        assert missing_payload["total_pages"] == 1
        assert missing_payload["has_prev"] is False
        assert missing_payload["has_next"] is False

        refreshed_state = runtime_server_module._load_wizard_state(run_id)
        assert refreshed_state.get("current_stage") == state.get("current_stage")
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_completion_advances_stage_flow_to_publish(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_stage_flow_draft.json"
        draft_payload = _seed_wizard_review_draft(draft_path, count=3)

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_stage_flow",
            "store_fingerprint": "store_fp_stage_flow",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        before = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        assert str(((before["state"].get("stage_flow") or {}).get("current_stage") or "")) == "review"

        for episode_id in ("ep_001", "ep_002", "ep_003"):
            _json_post(
                f"{base}/api/wizard/review/update",
                {"run_id": run_id, "episode_id": episode_id, "decision": "approved"},
            )

        after = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        stage_flow = dict(after["state"].get("stage_flow") or {})
        items = {str(item.get("stage") or ""): str(item.get("status") or "") for item in list(stage_flow.get("items") or []) if isinstance(item, dict)}
        review_state = dict(after["state"].get("review_state") or {})

        assert bool(review_state.get("complete")) is True
        assert str(stage_flow.get("current_stage") or "") == "publish"
        assert items.get("review") == "done"
        assert items.get("publish") == "current"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_archive_happy_path_reaches_safe_activation(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        db_path = tmp_path / "db.json"
        db_path.write_text(
            json.dumps(
                {
                    "conversations": [
                        {
                            "id": "conv_archive_happy",
                            "messages": [
                                {
                                    "role": "user",
                                    "text": "I love how calm I feel when I drink tea during late planning sessions, and I want you to remember that preference.",
                                },
                                {
                                    "role": "assistant",
                                    "text": "You asked me to keep the launch rollback checklist and the tea preference anchored to direct evidence from our conversations.",
                                },
                                {
                                    "role": "user",
                                    "text": "I trust our launch process more when the rollback checklist stays attached to the milestone plan and tea helps me stay focused.",
                                },
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        store_path = tmp_path / "archive_atoms.sqlite3"

        validation = _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "archive_path": str(db_path)})
        assert validation["ok"] is True
        assert validation["kind"] == "ia_archive"

        imported = _json_post(
            f"{base}/api/wizard/import/run",
            {"run_id": run_id, "archive_path": str(db_path), "store_path": str(store_path)},
        )
        assert imported["ok"] is True
        assert Path(str(imported.get("store_path") or "")).exists()

        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        cards = list(draft_payload.get("cards") or [])
        assert cards
        for card in cards:
            _json_post(
                f"{base}/api/wizard/review/update",
                {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"},
            )

        published = _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        assert published["ok"] is True
        assert str((published.get("published_set") or {}).get("version_id") or "").strip()
        published_state = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        published_stage_flow = dict((published_state.get("state") or {}).get("stage_flow") or {})
        published_items = {
            str(item.get("stage") or ""): dict(item)
            for item in list(published_stage_flow.get("items") or [])
            if isinstance(item, dict)
        }
        assert str(published_stage_flow.get("current_stage") or "") == "verify"
        assert str((published_items.get("verify") or {}).get("status") or "") == "current"
        assert str((published_items.get("verify") or {}).get("tone") or "") == "stale"

        verify = _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        assert verify["ok"] is True
        assert verify["status"] == "Safe"

        activated = _json_post(f"{base}/api/wizard/go-live", {"run_id": run_id})
        assert activated["ok"] is True
        assert str((((activated.get("activation") or {}).get("direct") or {}).get("status") or "")) == "running"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_archive_import_uses_run_scoped_store_when_live_runtime_store_exists(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        live_store_path = runtime_server_module.IMPORTS_ROOT / "atoms.sqlite3"
        live_store_path.parent.mkdir(parents=True, exist_ok=True)
        _seed_sqlite_store(live_store_path)
        live_cards_path = runtime_server_module.EPISODES_ROOT / "episode_cards.reviewed.json"
        live_cards_path.parent.mkdir(parents=True, exist_ok=True)
        live_cards_path.write_text(json.dumps({"cards": []}) + "\n", encoding="utf-8")
        runtime_server_module._wizard_write_runtime_lock(
            server,
            binding={
                "store_path": str(live_store_path.resolve()),
                "store_fingerprint": str(runtime_server_module._wizard_validate_sqlite_store(live_store_path).get("store_fingerprint") or ""),
                "episodes_path": str(live_cards_path.resolve()),
            },
        )

        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        db_path = tmp_path / "db.json"
        db_path.write_text(
            json.dumps(
                {
                    "conversations": [
                        {
                            "id": "conv_archive_isolated",
                            "messages": [
                                {"role": "user", "text": "Please keep the import workspace separate from the live store."},
                                {"role": "assistant", "text": "The new review flow should not overwrite the store that is already live."},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        validation = _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "archive_path": str(db_path)})
        assert validation["ok"] is True
        assert validation["kind"] == "ia_archive"

        imported = _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "archive_path": str(db_path)})
        assert imported["ok"] is True
        imported_store = Path(str(imported.get("store_path") or ""))
        assert imported_store.exists()
        assert imported_store != live_store_path.resolve()
        assert run_id in str(imported_store)
        assert run_id in str((imported.get("reports") or {}).get("json") or "")

        lock_payload = runtime_server_module._wizard_read_runtime_lock()
        assert str(lock_payload.get("store_path") or "") == str(live_store_path.resolve())

        state_payload = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        assert str((state_payload.get("state") or {}).get("store_path") or "") == str(imported_store)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_raw_archive_cannot_activate_happy_path(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        db_path = tmp_path / "db.json"
        db_path.write_text(
            json.dumps(
                {
                    "conversations": [
                        {
                            "id": "conv_archive_only",
                            "messages": [
                                {"role": "user", "text": "Remember that we need a rollback checklist."},
                                {"role": "assistant", "text": "I will keep the rollback checklist anchored to direct evidence."},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        validation = _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "archive_path": str(db_path)})
        assert validation["ok"] is True
        assert validation["kind"] == "ia_archive"

        status, payload = _json_post_error(f"{base}/api/wizard/go-live", {"run_id": run_id})
        assert status == 400
        assert (
            "verification must be safe" in str(payload.get("error") or "").lower()
            or "published reviewed set is required" in str(payload.get("error") or "").lower()
        )
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_validate_only_does_not_complete_import_or_unlock_build(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        db_path = tmp_path / "db.json"
        db_path.write_text(
            json.dumps(
                {
                    "conversations": [
                        {
                            "id": "conv_validate_only",
                            "messages": [
                                {"role": "user", "text": "Please remember the rollback checklist and tea preference."},
                                {"role": "assistant", "text": "I will keep both tied to direct evidence from our history."},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        validation = _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "archive_path": str(db_path)})
        assert validation["ok"] is True
        assert validation["status"] == "safe"

        state_payload = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        stage_flow = dict((state_payload.get("state") or {}).get("stage_flow") or {})
        items = {str(item.get("stage") or ""): str(item.get("status") or "") for item in list(stage_flow.get("items") or []) if isinstance(item, dict)}

        assert str(stage_flow.get("current_stage") or "") == "import"
        assert items.get("import") == "current"
        assert items.get("build_episodes") == "pending"

        status, payload = _json_post_error(
            f"{base}/api/wizard/build/run",
            {"run_id": run_id, "policy_preset": "balanced"},
        )
        assert status == 400
        assert "valid mno memory store" in str(payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_existing_store_validate_only_does_not_unlock_build(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "existing_atoms.sqlite3"
        _seed_sqlite_store(store_path)

        validation = _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        assert validation["ok"] is True
        assert validation["status"] == "safe"
        assert "store" in str(validation.get("kind") or "").lower()

        state_payload = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        state = dict(state_payload.get("state") or {})
        stage_flow = dict(state.get("stage_flow") or {})
        items = {str(item.get("stage") or ""): str(item.get("status") or "") for item in list(stage_flow.get("items") or []) if isinstance(item, dict)}

        assert str(stage_flow.get("current_stage") or "") == "import"
        assert items.get("import") == "current"
        assert items.get("build_episodes") == "pending"
        assert not bool((state.get("store_validation") or {}).get("is_valid"))

        status, payload = _json_post_error(
            f"{base}/api/wizard/build/run",
            {"run_id": run_id, "policy_preset": "balanced"},
        )
        assert status == 400
        assert "valid mno memory store" in str(payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_input_upload_and_options_endpoint(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])

        options = _json_get(f"{base}/api/wizard/input/options?run_id={quote(run_id)}")
        assert options["ok"] is True
        assert isinstance(options["memory_candidates"], list)

        archive_bytes = json.dumps(
            {
                "conversations": [
                    {
                        "id": "conv_uploaded",
                        "messages": [
                            {"role": "user", "text": "Remember the rollback checklist."},
                            {"role": "assistant", "text": "I will keep the checklist grounded in cited evidence."},
                        ],
                    }
                ]
            }
        ).encode("utf-8")
        uploaded = _json_post(
            f"{base}/api/wizard/input/upload",
            {
                "run_id": run_id,
                "file_name": "db.json",
                "content_base64": base64.b64encode(archive_bytes).decode("ascii"),
            },
        )
        assert uploaded["ok"] is True
        assert uploaded["classification"]["kind"] == "ia_archive"
        assert Path(str(uploaded["uploaded_path"])).exists()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_resume_recovers_published_safe_state(tmp_path: Path, monkeypatch) -> None:
    original_runs_root = runtime_server_module.WIZARD_RUNS_ROOT
    original_latest_path = runtime_server_module.WIZARD_LATEST_PATH
    runtime_server_module.WIZARD_RUNS_ROOT = tmp_path / "wizard_runs"
    runtime_server_module.WIZARD_LATEST_PATH = runtime_server_module.WIZARD_RUNS_ROOT / "LATEST.json"

    def _make_runtime() -> RuntimeSession:
        store = AtomStore()
        continuity = ContinuityStore()
        continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
        return RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)

    runtime = _make_runtime()
    queue = MutationReviewQueue(runtime.retriever.store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "resume_atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(
                f"{base}/api/wizard/review/update",
                {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"},
            )
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        verify = _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        assert verify["ok"] is True
        assert verify["status"] == "Safe"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)

    resumed_runtime = _make_runtime()
    resumed_queue = MutationReviewQueue(resumed_runtime.retriever.store)
    resumed_server, resumed_thread = start_runtime_server(resumed_runtime, host="127.0.0.1", port=0, review_queue=resumed_queue)
    resumed_host, resumed_port = resumed_server.server_address
    resumed_base = f"http://{resumed_host}:{resumed_port}"
    try:
        resumed = _json_post(f"{resumed_base}/api/wizard/start", {"mode": "resume"})
        assert resumed["ok"] is True
        assert str(resumed.get("run_id") or "") == run_id
        state_payload = resumed.get("state") or {}
        assert str((state_payload.get("verify") or {}).get("status") or "") == "Safe"
        assert str((state_payload.get("published_set") or {}).get("episodes_path") or "").strip()
        wizard_state = _json_get(f"{resumed_base}/api/wizard/state")
        assert wizard_state["ok"] is True
        assert str(wizard_state.get("latest_run_id") or "") == run_id
        assert bool(wizard_state.get("resume_available")) is True
    finally:
        stop_runtime_server(resumed_server, resumed_thread, runtime=resumed_runtime)
        runtime_server_module.WIZARD_RUNS_ROOT = original_runs_root
        runtime_server_module.WIZARD_LATEST_PATH = original_latest_path


def test_wizard_activation_status_tracks_direct_runtime_binding(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    original_lock_path = runtime_server_module.LIVE_RUNTIME_LOCK_PATH
    runtime_server_module.LIVE_RUNTIME_LOCK_PATH = tmp_path / "live_runtime.lock.json"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(
                f"{base}/api/wizard/review/update",
                {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"},
            )
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        _json_post(f"{base}/api/wizard/go-live", {"run_id": run_id})

        status = _json_post(f"{base}/api/wizard/activate/status", {"run_id": run_id})
        assert status["ok"] is True
        assert str(((status.get("activation") or {}).get("direct") or {}).get("status") or "") == "running"
        direct = (status.get("activation") or {}).get("direct") or {}
        lock = direct.get("lock") or {}
        assert str(lock.get("status") or "") == "owned"
        assert bool((runtime_server_module.LIVE_RUNTIME_LOCK_PATH).exists()) is True
        assert "mcp" in dict(status.get("activation") or {})
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        runtime_server_module.LIVE_RUNTIME_LOCK_PATH = original_lock_path


def test_wizard_direct_runtime_cleanup_repairs_stale_lock(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    original_lock_path = runtime_server_module.LIVE_RUNTIME_LOCK_PATH
    runtime_server_module.LIVE_RUNTIME_LOCK_PATH = tmp_path / "live_runtime.lock.json"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"})
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        _json_post(f"{base}/api/wizard/go-live", {"run_id": run_id})

        stale_payload = {
            "pid": 999999,
            "host": host,
            "port": int(port),
            "token": "stale-lock",
            "store_path": str(store_path.resolve()),
            "store_fingerprint": "stale",
            "episodes_path": "stale-reviewed.json",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        runtime_server_module.LIVE_RUNTIME_LOCK_PATH.write_text(json.dumps(stale_payload, indent=2), encoding="utf-8")

        status = _json_post(f"{base}/api/wizard/activate/status", {"run_id": run_id})
        direct = (status.get("activation") or {}).get("direct") or {}
        assert str(direct.get("status") or "") == "needs_attention"
        lock = direct.get("lock") or {}
        assert str(lock.get("status") or "") == "stale"
        assert bool(lock.get("cleanup_allowed")) is True

        cleanup = _json_post(f"{base}/api/wizard/activate/direct/cleanup", {"run_id": run_id})
        assert cleanup["ok"] is True
        assert str((cleanup.get("cleanup") or {}).get("action") or "") == "repaired"
        direct_after = (cleanup.get("activation") or {}).get("direct") or {}
        assert str(direct_after.get("status") or "") == "running"
        repaired_lock = direct_after.get("lock") or {}
        assert str(repaired_lock.get("status") or "") == "owned"
        saved_lock = json.loads(runtime_server_module.LIVE_RUNTIME_LOCK_PATH.read_text(encoding="utf-8"))
        assert int(saved_lock.get("pid") or 0) == os.getpid()
        assert str(saved_lock.get("token") or "") != "stale-lock"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        runtime_server_module.LIVE_RUNTIME_LOCK_PATH = original_lock_path


def test_wizard_direct_runtime_foreign_lock_blocks_activation(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    original_lock_path = runtime_server_module.LIVE_RUNTIME_LOCK_PATH
    runtime_server_module.LIVE_RUNTIME_LOCK_PATH = tmp_path / "live_runtime.lock.json"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"})
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})

        foreign_payload = {
            "pid": os.getpid(),
            "host": "127.0.0.1",
            "port": 42424,
            "token": "foreign-live-lock",
            "store_path": str(store_path.resolve()),
            "store_fingerprint": "foreign",
            "episodes_path": "foreign-reviewed.json",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        runtime_server_module.LIVE_RUNTIME_LOCK_PATH.write_text(json.dumps(foreign_payload, indent=2), encoding="utf-8")

        status_code, payload = _json_post_error(f"{base}/api/wizard/go-live", {"run_id": run_id})
        assert status_code == 400
        assert "already owned by pid" in str(payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        runtime_server_module.LIVE_RUNTIME_LOCK_PATH = original_lock_path


def test_wizard_developer_mode_allows_local_draft_activation_only(tmp_path: Path, monkeypatch) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    original_lock_path = runtime_server_module.LIVE_RUNTIME_LOCK_PATH
    runtime_server_module.LIVE_RUNTIME_LOCK_PATH = tmp_path / "live_runtime.lock.json"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        assert Path(str(built.get("draft_path") or "")).exists()

        blocked_code, blocked_payload = _json_post_error(
            f"{base}/api/wizard/activate/direct/draft",
            {"run_id": run_id, "acknowledged": True, "reason": "local smoke test"},
        )
        assert blocked_code == 409
        assert "enable developer mode" in str(blocked_payload.get("error") or "").lower()

        mode_enabled = _json_post(f"{base}/api/wizard/activate/developer-mode", {"run_id": run_id, "enabled": True})
        assert mode_enabled["ok"] is True
        assert bool((mode_enabled.get("activation") or {}).get("developer_mode")) is True

        draft_live = _json_post(
            f"{base}/api/wizard/activate/direct/draft",
            {"run_id": run_id, "acknowledged": True, "reason": "local smoke test", "operator": "runtime_ui"},
        )
        assert draft_live["ok"] is True
        activation = draft_live.get("activation") or {}
        direct = activation.get("direct") or {}
        assert str(direct.get("status") or "") == "draft_active"
        assert str(direct.get("artifact_mode") or "") == "draft"
        draft_override = activation.get("draft_override") or {}
        assert bool(draft_override.get("active")) is True
        assert str(draft_override.get("reason") or "") == "local smoke test"
        assert str(draft_override.get("label") or "") == "Unreviewed draft"

        status = _json_post(f"{base}/api/wizard/activate/status", {"run_id": run_id})
        direct_status = ((status.get("activation") or {}).get("direct") or {})
        assert str(direct_status.get("status") or "") == "draft_active"
        state_payload = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        stage_flow = dict((state_payload.get("state") or {}).get("stage_flow") or {})
        items = {str(item.get("stage") or ""): dict(item) for item in list(stage_flow.get("items") or []) if isinstance(item, dict)}
        assert str(stage_flow.get("current_stage") or "") == "activate"
        assert str((items.get("activate") or {}).get("status") or "") == "current"
        assert str((items.get("activate") or {}).get("tone") or "") == "unsafe"
        assert str((items.get("operate") or {}).get("status") or "") == "pending"

        def _unexpected_connector_discovery():
            raise AssertionError("connector discovery must not run before the verification gate")

        monkeypatch.setattr(runtime_server_module, "_wizard_connector_panel", _unexpected_connector_discovery)
        mcp_code, mcp_payload = _json_post_error(
            f"{base}/api/wizard/activate/mcp/export",
            {"run_id": run_id},
        )
        assert mcp_code == 400
        assert "verification must be safe" in str(mcp_payload.get("error") or "").lower()

        install_code, install_payload = _json_post_error(
            f"{base}/api/wizard/activate/mcp/install",
            {"run_id": run_id, "target": "claude_code"},
        )
        assert install_code == 400
        assert "verification must be safe" in str(install_payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        runtime_server_module.LIVE_RUNTIME_LOCK_PATH = original_lock_path


def test_wizard_publish_blocks_all_rejected_review_sets(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_all_rejected.json"
        draft_payload = _seed_wizard_review_draft(draft_path, count=2)

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_all_rejected",
            "store_fingerprint": "store_fp_all_rejected",
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": "ep_001", "decision": "rejected"})
        _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": "ep_002", "decision": "rejected"})

        state_payload = _json_get(f"{base}/api/wizard/state?run_id={quote(run_id)}")
        review_state = dict((state_payload.get("state") or {}).get("review_state") or {})
        stage_flow = dict((state_payload.get("state") or {}).get("stage_flow") or {})
        items = {str(item.get("stage") or ""): dict(item) for item in list(stage_flow.get("items") or []) if isinstance(item, dict)}
        assert review_state["complete"] is True
        assert review_state["publishable_count"] == 0
        assert str((items.get("publish") or {}).get("tone") or "") == "blocked"

        status, payload = _json_post_error(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        assert status == 400
        assert "at least one card" in str(payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_mcp_install_endpoint_updates_activation_state(tmp_path: Path, monkeypatch) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    class FakePanel:
        def build_preview(self, payload):
            return {
                "server_name": payload["server_name"],
                "claude_code_scope": payload["claude_code_scope"],
                "default_role": payload["default_role"],
                "compat_mode": payload["compat_mode"],
                "claude_code_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_claude_code_config": str(tmp_path / "claude_code.json"),
                "windows_claude_desktop_config": str(tmp_path / "claude_desktop.json"),
                "claude_code_install_context": "native-windows-claude",
                "claude_code_display": "Claude Code",
            }

        def install_claude_code(self, _payload):
            config_path = tmp_path / "claude_code.json"
            config_path.write_text(
                json.dumps({"mcpServers": {"numquamoblita-live": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]}}}, indent=2),
                encoding="utf-8",
            )
            return {"ok": True, "target": "claude_code"}

        def remove_claude_code(self, _payload):
            config_path = tmp_path / "claude_code.json"
            if config_path.exists():
                config_path.unlink()
            return {"ok": True, "removed": True}

        def install_claude_desktop(self, _payload):
            return {"ok": True, "target": "claude_desktop"}

        def remove_claude_desktop(self, _payload):
            return {"ok": True, "removed": True}

        def export_bundle(self, _payload):
            return {"server_name": "numquamoblita-live"}

        def save_export_bundle(self, _payload, *, export_path):
            return {"server_name": "numquamoblita-live", "export_path": str(export_path)}

    monkeypatch.setattr(runtime_server_module, "_wizard_connector_panel", lambda: FakePanel())
    monkeypatch.setattr(runtime_server_module, "_wizard_mcp_handshake", lambda entry: {"ok": True, "entry": dict(entry)})

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(
                f"{base}/api/wizard/review/update",
                {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"},
            )
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})

        installed = _json_post(f"{base}/api/wizard/activate/mcp/install", {"run_id": run_id, "target": "claude_code"})
        assert installed["ok"] is True
        assert str(((installed.get("activation") or {}).get("mcp") or {}).get("status") or "") == "installed"

        removed = _json_post(f"{base}/api/wizard/activate/mcp/remove", {"run_id": run_id, "target": "claude_code"})
        assert removed["ok"] is True
        assert str(((removed.get("activation") or {}).get("mcp") or {}).get("status") or "") == "not_installed"

        reinstalled = _json_post(
            f"{base}/api/wizard/activate/mcp/install",
            {"run_id": run_id, "target": "claude_code"},
        )
        assert reinstalled["ok"] is True
        assert str(((reinstalled.get("activation") or {}).get("mcp") or {}).get("status") or "") == "installed"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_draft_curation_mcp_install_works_before_verify(tmp_path: Path, monkeypatch) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    install_calls: list[dict[str, object]] = []
    export_calls: list[dict[str, object]] = []

    class FakePanel:
        def build_preview(self, payload):
            return {
                "server_name": payload["server_name"],
                "claude_code_scope": payload["claude_code_scope"],
                "default_role": payload["default_role"],
                "compat_mode": payload["compat_mode"],
                "mutations_enabled": payload["mutations_enabled"],
                "claude_code_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_claude_code_config": str(tmp_path / "claude_code.json"),
                "windows_claude_desktop_config": str(tmp_path / "claude_desktop.json"),
                "claude_code_install_context": "native-windows-claude",
                "claude_code_display": "Claude Code",
            }

        def install_claude_code(self, payload):
            install_calls.append(dict(payload))
            config_path = tmp_path / "claude_code.json"
            config_path.write_text(
                json.dumps({"mcpServers": {"numquamoblita-live": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]}}}, indent=2),
                encoding="utf-8",
            )
            return {"ok": True, "target": "claude_code"}

        def remove_claude_code(self, _payload):
            config_path = tmp_path / "claude_code.json"
            if config_path.exists():
                config_path.unlink()
            return {"ok": True, "removed": True}

        def install_claude_desktop(self, _payload):
            return {"ok": True, "target": "claude_desktop"}

        def remove_claude_desktop(self, _payload):
            return {"ok": True, "removed": True}

        def export_bundle(self, payload):
            export_calls.append(dict(payload))
            return {"server_name": "numquamoblita-live"}

        def save_export_bundle(self, payload, *, export_path):
            export_calls.append(dict(payload))
            return {"server_name": "numquamoblita-live", "export_path": str(export_path)}

    monkeypatch.setattr(runtime_server_module, "_wizard_connector_panel", lambda: FakePanel())
    monkeypatch.setattr(runtime_server_module, "_wizard_mcp_handshake", lambda entry: {"ok": True, "entry": dict(entry)})

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_path = str(Path(str(built["draft_path"])).resolve())

        status = _json_post(f"{base}/api/wizard/draft-curation/mcp/status", {"run_id": run_id})
        assert status["ok"] is True
        assert status["draft_ready"] is True
        preview = (status.get("mcp") or {}).get("preview") or {}
        assert str(preview.get("default_role") or "") == "viewer"
        assert str(preview.get("compat_mode") or "") == "strict"
        assert bool(preview.get("mutations_enabled")) is True

        custom_status = _json_post(
            f"{base}/api/wizard/draft-curation/mcp/status",
            {"run_id": run_id, "default_role": "operator", "mutations_enabled": False},
        )
        custom_preview = (custom_status.get("mcp") or {}).get("preview") or {}
        assert str(custom_preview.get("default_role") or "") == "operator"
        assert str(custom_preview.get("compat_mode") or "") == "strict"
        assert bool(custom_preview.get("mutations_enabled")) is False

        installed = _json_post(f"{base}/api/wizard/draft-curation/mcp/install", {"run_id": run_id, "target": "claude_code"})
        assert installed["ok"] is True
        assert str((installed.get("mcp") or {}).get("status") or "") == "installed"
        assert install_calls
        assert str(install_calls[-1]["default_role"]) == "viewer"
        assert str(install_calls[-1]["compat_mode"]) == "strict"
        assert bool(install_calls[-1]["mutations_enabled"]) is True
        assert str(install_calls[-1]["memories_path"]) == str(store_path)
        assert str(install_calls[-1]["episodes_path"]) == draft_path

        installed_custom = _json_post(
            f"{base}/api/wizard/draft-curation/mcp/install",
            {"run_id": run_id, "target": "claude_code", "default_role": "operator", "mutations_enabled": False},
        )
        assert installed_custom["ok"] is True
        assert str(install_calls[-1]["default_role"]) == "operator"
        assert str(install_calls[-1]["compat_mode"]) == "strict"
        assert bool(install_calls[-1]["mutations_enabled"]) is False

        exported = _json_post(f"{base}/api/wizard/draft-curation/mcp/export", {"run_id": run_id})
        assert exported["ok"] is True
        assert str((exported.get("mcp") or {}).get("status") or "") == "export_ready"
        assert export_calls
        assert str(export_calls[-1]["episodes_path"]) == draft_path

        removed = _json_post(f"{base}/api/wizard/draft-curation/mcp/remove", {"run_id": run_id, "target": "claude_code"})
        assert removed["ok"] is True
        assert str((removed.get("mcp") or {}).get("status") or "") == "not_installed"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_mcp_status_detects_project_scoped_claude_code_entry(tmp_path: Path, monkeypatch) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    config_path = tmp_path / "claude_code.json"
    config_path.write_text(
        json.dumps(
            {
                "projects": {
                    "Z:/modelNumquamOblita": {
                        "mcpServers": {
                            "numquamoblita-live": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]}
                        }
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    class FakePanel:
        def build_preview(self, payload):
            return {
                "server_name": payload["server_name"],
                "claude_code_scope": payload["claude_code_scope"],
                "default_role": payload["default_role"],
                "compat_mode": payload["compat_mode"],
                "claude_code_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_claude_code_config": str(config_path),
                "windows_claude_desktop_config": str(tmp_path / "claude_desktop.json"),
                "claude_code_install_context": "native-windows-claude",
                "claude_code_display": "native Windows CLI",
            }

    monkeypatch.setattr(runtime_server_module, "_wizard_connector_panel", lambda: FakePanel())

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"})
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})

        status = _json_post(f"{base}/api/wizard/activate/status", {"run_id": run_id, "claude_code_scope": "local"})
        claude_code = (((status.get("activation") or {}).get("mcp") or {}).get("targets") or {}).get("claude_code") or {}
        assert str(claude_code.get("status") or "") == "installed"
        assert str(claude_code.get("scope") or "") == "local"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_remap_can_restore_missing_published_set(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"})
        compiled = _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        reviewed_path = Path(str(compiled.get("reviewed_path") or ""))
        reviewed_bytes = reviewed_path.read_bytes()
        reviewed_path.unlink()

        verify = _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        assert verify["ok"] is True
        assert verify["status"] == "Blocked"
        assert bool(verify.get("remap_required")) is True

        remap_status = _json_post(f"{base}/api/wizard/remap/status", {"run_id": run_id})
        rows = list(((remap_status.get("remap") or {}).get("missing_artifacts") or []))
        assert any(str(row.get("target") or "") == "published_set" for row in rows)

        remapped = _json_post(
            f"{base}/api/wizard/remap/apply",
            {
                "run_id": run_id,
                "target": "published_set",
                "file_name": "episode_cards.reviewed.json",
                "content_base64": base64.b64encode(reviewed_bytes).decode("ascii"),
            },
        )
        assert remapped["ok"] is True
        restored_path = Path(str(((remapped.get("result") or {}).get("replacement") or {}).get("path") or ""))
        assert restored_path.exists()

        verify_after = _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        assert verify_after["ok"] is True
        assert verify_after["status"] == "Safe"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_reset_can_back_out_stale_published_state(tmp_path: Path) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"})
        compiled = _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        reviewed_path = Path(str(compiled.get("reviewed_path") or ""))
        reviewed_path.unlink()

        verify = _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        assert verify["status"] == "Blocked"

        reset = _json_post(f"{base}/api/wizard/reset", {"run_id": run_id, "stage": "review"})
        assert reset["ok"] is True
        state_payload = reset.get("state") or {}
        assert str(state_payload.get("current_stage") or "") == "review"
        assert str(((state_payload.get("published_set") or {}).get("status") or "")) == "unpublished"
        assert str(((state_payload.get("verify") or {}).get("status") or "")) == "Unknown"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_mcp_unknown_ownership_requires_explicit_action(tmp_path: Path, monkeypatch) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    config_path = tmp_path / "claude_code.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"numquamoblita-live": {"command": "other.exe", "args": ["--foreign"]}}}, indent=2),
        encoding="utf-8",
    )

    class FakePanel:
        def build_preview(self, payload):
            return {
                "server_name": payload["server_name"],
                "claude_code_scope": payload["claude_code_scope"],
                "default_role": payload["default_role"],
                "compat_mode": payload["compat_mode"],
                "claude_code_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_claude_code_config": str(config_path),
                "windows_claude_desktop_config": str(tmp_path / "claude_desktop.json"),
                "claude_code_install_context": "native-windows-claude",
                "claude_code_display": "Claude Code",
            }

        def install_claude_code(self, _payload):
            config_path.write_text(
                json.dumps({"mcpServers": {"numquamoblita-live": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]}}}, indent=2),
                encoding="utf-8",
            )
            return {"ok": True}

        def remove_claude_code(self, _payload):
            return {"ok": True}

        def install_claude_desktop(self, _payload):
            return {"ok": True}

        def remove_claude_desktop(self, _payload):
            return {"ok": True}

        def export_bundle(self, _payload):
            return {"server_name": "numquamoblita-live"}

        def save_export_bundle(self, _payload, *, export_path):
            return {"server_name": "numquamoblita-live", "export_path": str(export_path)}

    monkeypatch.setattr(runtime_server_module, "_wizard_connector_panel", lambda: FakePanel())
    monkeypatch.setattr(runtime_server_module, "_wizard_mcp_handshake", lambda entry: {"ok": True, "entry": dict(entry)})

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"})
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})

        status = _json_post(f"{base}/api/wizard/activate/status", {"run_id": run_id})
        claude_code = (((status.get("activation") or {}).get("mcp") or {}).get("targets") or {}).get("claude_code") or {}
        assert str(claude_code.get("ownership") or "") == "unknown"

        blocked_install_code, blocked_install = _json_post_error(
            f"{base}/api/wizard/activate/mcp/install",
            {"run_id": run_id, "target": "claude_code"},
        )
        assert blocked_install_code == 409
        assert "unknown mcp ownership" in str(blocked_install.get("error") or "").lower()

        blocked_remove_code, blocked_remove = _json_post_error(
            f"{base}/api/wizard/activate/mcp/remove",
            {"run_id": run_id, "target": "claude_code"},
        )
        assert blocked_remove_code == 409
        assert "cannot remove" in str(blocked_remove.get("error") or "").lower()

        overwritten = _json_post(
            f"{base}/api/wizard/activate/mcp/install",
            {"run_id": run_id, "target": "claude_code", "ownership_action": "overwrite"},
        )
        assert overwritten["ok"] is True
        assert str((((overwritten.get("activation") or {}).get("mcp") or {}).get("status") or "")) == "installed"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_mcp_handshake_failure_rolls_back_config(tmp_path: Path, monkeypatch) -> None:
    store = AtomStore()
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity, enable_writeback=False)
    queue = MutationReviewQueue(store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    config_path = tmp_path / "claude_code.json"
    previous_payload = {"mcpServers": {"keep": {"command": "keep.exe", "args": ["--stay"]}}}
    config_path.write_text(json.dumps(previous_payload, indent=2), encoding="utf-8")

    class FakePanel:
        def build_preview(self, payload):
            return {
                "server_name": payload["server_name"],
                "claude_code_scope": payload["claude_code_scope"],
                "default_role": payload["default_role"],
                "compat_mode": payload["compat_mode"],
                "claude_code_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_entry": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                "windows_claude_code_config": str(config_path),
                "windows_claude_desktop_config": str(tmp_path / "claude_desktop.json"),
                "claude_code_install_context": "native-windows-claude",
                "claude_code_display": "Claude Code",
            }

        def install_claude_code(self, _payload):
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "keep": {"command": "keep.exe", "args": ["--stay"]},
                            "numquamoblita-live": {"command": "python3", "args": ["tools/run_claude_live_mcp.py"]},
                        }
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return {"ok": True}

        def remove_claude_code(self, _payload):
            return {"ok": True}

        def install_claude_desktop(self, _payload):
            return {"ok": True}

        def remove_claude_desktop(self, _payload):
            return {"ok": True}

        def export_bundle(self, _payload):
            return {"server_name": "numquamoblita-live"}

        def save_export_bundle(self, _payload, *, export_path):
            return {"server_name": "numquamoblita-live", "export_path": str(export_path)}

    monkeypatch.setattr(runtime_server_module, "_wizard_connector_panel", lambda: FakePanel())

    def _fail_handshake(_entry):
        raise RuntimeError("forced handshake failure")

    monkeypatch.setattr(runtime_server_module, "_wizard_mcp_handshake", _fail_handshake)

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        store_path = tmp_path / "atoms.sqlite3"
        _seed_sqlite_store(store_path)
        _json_post(f"{base}/api/wizard/import/validate", {"run_id": run_id, "store_path": str(store_path)})
        _json_post(f"{base}/api/wizard/import/run", {"run_id": run_id, "store_path": str(store_path)})
        built = _json_post(f"{base}/api/wizard/build/run", {"run_id": run_id, "store_path": str(store_path), "policy_preset": "assist"})
        draft_payload = json.loads(Path(str(built["draft_path"])).read_text(encoding="utf-8"))
        for card in list(draft_payload.get("cards") or []):
            _json_post(f"{base}/api/wizard/review/update", {"run_id": run_id, "episode_id": str(card["episode_id"]), "decision": "approved"})
        _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})

        status_code, payload = _json_post_error(
            f"{base}/api/wizard/activate/mcp/install",
            {"run_id": run_id, "target": "claude_code"},
        )
        assert status_code == 400
        assert "rolled back" in str(payload.get("error") or "").lower()
        restored_payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert restored_payload == previous_payload

        status = _json_post(f"{base}/api/wizard/activate/status", {"run_id": run_id})
        claude_code = (((status.get("activation") or {}).get("mcp") or {}).get("targets") or {}).get("claude_code") or {}
        assert str(claude_code.get("status") or "") == "not_installed"
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_exploration_and_organizer_endpoints() -> None:
    store = AtomStore()
    atom_xander = store.add_candidate(
        _candidate(
            "ex1",
            "Xander discussed NumquamOblita roadmap checkpoints and verification flow.",
            "conv_ex1",
            "roadmap",
        )
    )
    store.add_candidate(
        _candidate(
            "ex2",
            "NumquamOblita project planning linked episode quality checks and rollout notes.",
            "conv_ex2",
            "numquamoblita",
        )
    )
    atom_conflict = store.add_candidate(
        _candidate(
            "ex3",
            "There was uncertainty in one continuity checkpoint pending review.",
            "conv_ex3",
            "continuity",
        )
    )
    atom_unicode = _candidate(
        "ex4",
        "Лира discussed memory continuity with repeated labels for testing.",
        "conv_ex4",
        "memory",
    )
    atom_unicode.entities = ["Лира", "Лира", "assistant"]
    atom_unicode.topics = ["память", "память", "continuity"]
    store.add_candidate(atom_unicode)
    store.mark_conflict(atom_xander.atom_id, atom_conflict.atom_id, reason="test_conflict")

    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuityBuilder().build(store.list_atoms()))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        missing_state_code, missing_state_payload = _json_get_error(
            f"{base}/api/wizard/organizer/state?run_id=wizard_19990101T000000Z"
        )
        assert missing_state_code == 404
        assert missing_state_payload["error"] == "wizard run not found"

        start_here = _json_get(f"{base}/api/explore/start-here?limit=10")
        assert start_here["ok"] is True
        assert start_here["status"] in {"ready", "insufficient_support"}
        buckets = start_here.get("buckets") or {}
        assert isinstance(buckets, dict)
        assert "people" in buckets
        assert "projects" in buckets
        assert "topics" in buckets
        people_rows = [row for row in list(buckets.get("people") or []) if isinstance(row, dict)]
        unicode_row = next(
            (row for row in people_rows if str(row.get("label") or "").strip().casefold().startswith("лира")),
            None,
        )
        assert unicode_row is not None
        assert str(unicode_row.get("anchor_id") or "").strip()
        assert int(unicode_row.get("support_count") or 0) == 1

        expanded = _json_get(f"{base}/api/explore/expand?anchor_id={quote('xander')}&anchor_type=person&limit=8")
        assert expanded["ok"] is True
        assert expanded["status"] in {"ready", "insufficient_support"}
        assert isinstance(expanded.get("connected_atoms"), list)
        assert isinstance(expanded.get("next_hops"), list)

        peek = _json_get(f"{base}/api/explore/peek?anchor_id={quote('numquamoblita')}&anchor_type=project&limit=4")
        assert peek["ok"] is True
        assert peek["status"] in {"ready", "insufficient_support"}
        assert isinstance(peek.get("snippets"), list)

        pref_set = _json_post(
            f"{base}/api/explore/preferences",
            {"anchor_id": "xander", "anchor_type": "person", "action": "pin"},
        )
        assert pref_set["ok"] is True
        assert pref_set["applied"] is True
        pref_list = _json_get(f"{base}/api/explore/preferences")
        assert pref_list["ok"] is True
        assert int(pref_list.get("count") or 0) >= 1
        pref_clear = _json_post(
            f"{base}/api/explore/preferences",
            {"anchor_id": "xander", "anchor_type": "person", "action": "clear"},
        )
        assert pref_clear["ok"] is True
        assert pref_clear["removed"] is True

        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        assert started["ok"] is True
        run_id = str(started.get("run_id") or "")
        assert run_id.startswith("wizard_")

        inventory = _json_post(f"{base}/api/wizard/organizer/inventory", {"run_id": run_id, "limit": 16})
        assert inventory["ok"] is True
        inv_payload = inventory.get("inventory") or {}
        assert str(inv_payload.get("status") or "") in {"ready", "insufficient_support"}
        typed_candidates = list(inv_payload.get("typed_candidates") or [])
        assert isinstance(typed_candidates, list)
        assert any(
            str(row.get("risk_class") or "") == "review"
            for row in typed_candidates
            if int(row.get("contradiction_count") or 0) > 0
        )

        dedupe = _json_post(f"{base}/api/wizard/organizer/dedupe", {"run_id": run_id})
        assert dedupe["ok"] is True
        dedupe_payload = dedupe.get("dedupe") or {}
        assert isinstance(dedupe_payload.get("proposals"), list)

        conflicts = _json_post(f"{base}/api/wizard/organizer/conflicts", {"run_id": run_id})
        assert conflicts["ok"] is True
        conflicts_payload = conflicts.get("conflicts") or {}
        assert isinstance(conflicts_payload.get("conflict_queue"), list)
        assert isinstance(conflicts_payload.get("ambiguity_queue"), list)

        package = _json_post(f"{base}/api/wizard/organizer/package", {"run_id": run_id})
        assert package["ok"] is True
        package_payload = package.get("package") or {}
        assert str(package_payload.get("package_id") or "").startswith("org_pkg_")

        apply_dry = _json_post(f"{base}/api/wizard/organizer/apply", {"run_id": run_id, "dry_run": True})
        assert apply_dry["ok"] is True
        assert apply_dry["applied"] is False

        apply_live = _json_post(f"{base}/api/wizard/organizer/apply", {"run_id": run_id, "dry_run": "false"})
        assert apply_live["ok"] is True
        assert apply_live["applied"] is True
        assert apply_live["dry_run"] is False
        assert str(apply_live.get("rollback_id") or "").startswith("org_rb_")

        verify = _json_post(f"{base}/api/wizard/organizer/verify", {"run_id": run_id})
        assert verify["ok"] is True
        verify_payload = verify.get("verify") or {}
        assert str(verify_payload.get("status") or "") in {"safe", "needs_attention"}
        assert isinstance(verify_payload.get("metrics"), dict)

        restore = _json_post(f"{base}/api/wizard/organizer/restore-last", {"run_id": run_id})
        assert restore["ok"] is True
        assert restore["restored"] is True
        assert isinstance(restore.get("applied_profile"), dict)

        organizer_state = _json_get(f"{base}/api/wizard/organizer/state?run_id={quote(run_id)}")
        assert organizer_state["ok"] is True
        assert isinstance(organizer_state.get("organizer"), dict)
    finally:
        stop_runtime_server(server, thread, runtime=runtime)


def test_wizard_review_compile_publishes_explicit_lineage_metadata(tmp_path: Path) -> None:
    store_path = tmp_path / "runtime" / "imports" / "atoms.sqlite3"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    _seed_sqlite_store(store_path)

    runtime = RuntimeSession(
        retriever=MemoryRetriever(SqliteAtomStore(store_path)),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=default_config(),
    )
    queue = MutationReviewQueue(runtime.retriever.store)
    server, thread = start_runtime_server(runtime, host="127.0.0.1", port=0, review_queue=queue)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    try:
        started = _json_post(f"{base}/api/wizard/start", {"mode": "new"})
        run_id = str(started["run_id"])
        draft_path = tmp_path / "wizard_lineage_draft.json"
        draft_payload = _seed_wizard_review_draft(draft_path, count=2)

        state = runtime_server_module._load_wizard_state(run_id)
        state["build_info"] = {
            "draft_path": str(draft_path),
            "build_id": "build_lineage_review",
            "store_fingerprint": "store_fp_lineage",
            "schema_version": 3,
        }
        state["last_built_episode_draft_path"] = str(draft_path)
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

        _json_post(
            f"{base}/api/wizard/review/update",
            {
                "run_id": run_id,
                "episode_id": "ep_001",
                "decision": "approved",
                "truth_family_id": "family_launch_story",
            },
        )
        _json_post(
            f"{base}/api/wizard/review/update",
            {
                "run_id": run_id,
                "episode_id": "ep_002",
                "decision": "edited",
                "title": "Episode 002 corrected",
                "summary": "Draft summary 002 corrected into the current reviewed version.",
                "truth_family_id": "family_launch_story",
                "supersedes_episode_id": "ep_001",
            },
        )

        review_cards = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&status=all")
        review_rows = {str(row["episode_id"]): row for row in review_cards["cards"]}
        assert review_rows["ep_001"]["truth_family_id"] == "family_launch_story"
        assert review_rows["ep_002"]["truth_family_id"] == "family_launch_story"
        assert review_rows["ep_002"]["supersedes_episode_id"] == "ep_001"
        assert review_rows["ep_002"]["review_payload"]["supersedes_episode_id"] == "ep_001"

        compiled = _json_post(f"{base}/api/wizard/review/compile", {"run_id": run_id, "reviewer": "runtime_ui"})
        assert compiled["ok"] is True
        episodes = _json_get(f"{base}/api/memory/episodes?run_id={quote(run_id)}")
        rows = {str(row["episode_id"]): row for row in episodes["episodes"]}
        assert rows["ep_001"]["truth_family_id"] == "family_launch_story"
        assert rows["ep_001"]["superseded_by_episode_id"] == "ep_002"
        assert rows["ep_001"]["lineage_is_current"] is False
        assert rows["ep_002"]["truth_family_id"] == "family_launch_story"
        assert rows["ep_002"]["supersedes_episode_id"] == "ep_001"
        assert rows["ep_002"]["lineage_is_current"] is True
    finally:
        stop_runtime_server(server, thread)
        runtime.close()
