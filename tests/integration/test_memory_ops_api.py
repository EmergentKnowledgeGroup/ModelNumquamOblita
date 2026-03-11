from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from engine.continuity import Constellation, ContinuityBuilder, ContinuitySnapshot, ContinuityStore, NarrativeArc, SharedLanguageKey
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStatus, AtomStore, MutationReviewQueue
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


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

        db_path = tmp_path / "db.json"
        db_path.write_text(
            json.dumps(
                {
                    "conversations": [
                        {
                            "id": "conv_seed",
                            "messages": [
                                {
                                    "role": "user",
                                    "text": "We should review the quarterly roadmap and lock three milestones for the launch window.",
                                },
                                {
                                    "role": "assistant",
                                    "text": "Agreed. I mapped the risks, mitigation tracks, and owners so we can sequence the work clearly.",
                                },
                                {
                                    "role": "user",
                                    "text": "Please add the rollback procedure and the verification checklist so we can run the deployment safely.",
                                },
                                {
                                    "role": "assistant",
                                    "text": "Done. I updated the plan with rollback notes and verification gates for each milestone.",
                                },
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        validation = _json_post(
            f"{base}/api/wizard/import/validate",
            {"run_id": run_id, "archive_path": str(db_path)},
        )
        assert validation["ok"] is True
        assert validation["conversation_count"] == 1
        assert validation["message_count"] == 4

        store_path = tmp_path / "atoms.sqlite3"
        import_out_dir = tmp_path / "import_reports"
        imported = _json_post(
            f"{base}/api/wizard/import/run",
            {"run_id": run_id, "archive_path": str(db_path), "store_path": str(store_path), "out_dir": str(import_out_dir)},
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
            {"run_id": run_id, "store_path": str(store_path), "policy_preset": "balanced"},
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
        if cards:
            first_card = dict(cards[0])
            assert list(first_card.get("actors") or [])
            assert list(first_card.get("topic_tags") or [])
            assert str(first_card.get("timestamp_start") or "").strip()
            assert str(first_card.get("timestamp_end") or "").strip()
        rejects_payload = json.loads(rejects_path.read_text(encoding="utf-8"))
        assert str(rejects_payload.get("schema") or "") == "numquamoblita.episode_cards.rejects.v1"
        assert isinstance(rejects_payload.get("rejected"), list)

        compiled_review = _json_post(
            f"{base}/api/wizard/review/compile",
            {"run_id": run_id, "reviewer": "runtime_ui"},
        )
        assert compiled_review["ok"] is True
        assert int(compiled_review.get("episode_count") or 0) >= 0

        verify = _json_post(
            f"{base}/api/wizard/verify/run",
            {"run_id": run_id},
        )
        assert verify["ok"] is True
        assert "actionable_links" in verify
        assert isinstance(verify["actionable_links"], list)
        assert any(str(item.get("api_path") or "").strip() for item in verify["actionable_links"])

        go_live = _json_post(
            f"{base}/api/wizard/go-live",
            {"run_id": run_id},
        )
        assert go_live["ok"] is True
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
