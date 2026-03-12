from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from engine.continuity import Constellation, ContinuityBuilder, ContinuitySnapshot, ContinuityStore, NarrativeArc, SharedLanguageKey
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStatus, AtomStore, MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server
from engine.runtime import server as runtime_server_module


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


def test_memory_atoms_cards_detail_and_graph_endpoints() -> None:
    store = AtomStore()
    first = store.add_candidate(_candidate("a1", "We anchored continuity to evidence.", "conv_1", "continuity"))
    second = store.add_candidate(_candidate("a2", "You prefer tea in late sessions.", "conv_2", "preference"))
    third = store.add_candidate(_candidate("a3", "We tracked migration rollback safeguards.", "conv_3", "operations"))
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
        assert cards["total"] >= 2
        card_ids = {item["card_id"] for item in cards["cards"]}
        assert f"card_{first.atom_id}" in card_ids

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
                {"title": "Edited tea preference title"},
            )
            assert edited["ok"] is True
            assert edited["episode"]["title"] == "Edited tea preference title"

            enabled = _json_post(f"{base}/api/memory/episodes/{quote(episode_id)}/enable", {})
            assert enabled["ok"] is True
            filtered_enabled = _json_get(f"{base}/api/memory/episodes?status=approved")
            assert any(str(item["episode_id"]) == episode_id for item in filtered_enabled["episodes"])

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
        state["review_decisions"] = {
            "ep_001": {"decision": "approved", "title": "", "summary": "", "actors": [], "topic_tags": [], "cue_terms": []},
            "ep_002": {"decision": "edited", "title": "Edited title", "summary": "Edited summary", "actors": ["user"], "topic_tags": ["testing"], "cue_terms": []},
            "ep_003": {"decision": "rejected", "title": "", "summary": "", "actors": [], "topic_tags": [], "cue_terms": []},
        }
        runtime_server_module._wizard_sync_review_state(state, source_payload=draft_payload, source_cards_path=draft_path)
        runtime_server_module._save_wizard_state(state)

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

        searched = _json_get(f"{base}/api/wizard/review/cards?run_id={quote(run_id)}&q={quote('Episode 020')}&page=1&page_size=12")
        assert searched["ok"] is True
        assert searched["filtered_total"] == 1
        assert len(searched["cards"]) == 1
        assert str(searched["cards"][0]["episode_id"]) == "ep_020"
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

        verify = _json_post(f"{base}/api/wizard/verify/run", {"run_id": run_id})
        assert verify["ok"] is True
        assert verify["status"] == "Safe"

        activated = _json_post(f"{base}/api/wizard/go-live", {"run_id": run_id})
        assert activated["ok"] is True
        assert str((((activated.get("activation") or {}).get("direct") or {}).get("status") or "")) == "running"
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


def test_wizard_developer_mode_allows_local_draft_activation_only(tmp_path: Path) -> None:
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

        mcp_code, mcp_payload = _json_post_error(
            f"{base}/api/wizard/activate/mcp/export",
            {"run_id": run_id},
        )
        assert mcp_code == 400
        assert "verification must be safe" in str(mcp_payload.get("error") or "").lower()
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        runtime_server_module.LIVE_RUNTIME_LOCK_PATH = original_lock_path


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
