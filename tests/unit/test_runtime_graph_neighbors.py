from __future__ import annotations

from datetime import datetime, timezone

from engine.continuity import Constellation, ContinuitySnapshot, ContinuityStore, NarrativeArc, SharedLanguageKey
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession
from engine.runtime.server import GRAPH_NEIGHBOR_REQUEST_BUDGET, _build_graph_neighbors_payload


def _candidate(
    candidate_id: str,
    text: str,
    source_id: str,
    *,
    entities: list[str] | None = None,
    topics: list[str] | None = None,
) -> CandidateAtom:
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
                span_end=max(1, len(text)),
            )
        ],
        entities=list(entities or ["user", "assistant"]),
        topics=list(topics or ["memory"]),
        confidence=0.84,
        salience=0.66,
    )


def _graph_runtime() -> tuple[RuntimeSession, dict[str, str]]:
    store = AtomStore()
    root = store.add_candidate(_candidate("root", "Root memory about tea rituals.", "conv_root", topics=["tea"]))
    conflict = store.add_candidate(_candidate("conflict", "Conflict memory about tea rituals.", "conv_conflict", topics=["tea"]))
    distance_two = store.add_candidate(
        _candidate("distance2", "Distance-two arc memory about tea rituals.", "conv_distance2", topics=["tea"])
    )
    constellation = store.add_candidate(
        _candidate("constellation", "Constellation partner memory.", "conv_constellation", topics=["tea"])
    )
    shared = store.add_candidate(_candidate("shared", "Shared phrase memory.", "conv_shared", topics=["callback"]))
    shared_child = store.add_candidate(
        _candidate("shared_child", "Shared child should never expand.", "conv_shared_child", topics=["callback"])
    )

    store.mark_conflict(root.atom_id, conflict.atom_id, reason="root_conflict")
    store.mark_conflict(shared.atom_id, shared_child.atom_id, reason="shared_branch_conflict")

    now = datetime.now(timezone.utc)
    snapshot = ContinuitySnapshot(
        generated_at=now,
        constellations=[
            Constellation(
                constellation_id="const_1",
                topic="tea",
                atom_ids=[root.atom_id, constellation.atom_id],
                strength=0.82,
                entities=["user"],
            )
        ],
        narrative_arcs=[
            NarrativeArc(
                arc_id="arc_1",
                entity="user",
                topic="tea",
                atom_ids=[conflict.atom_id, distance_two.atom_id],
                start_at=now,
                end_at=now,
                confidence=0.88,
            )
        ],
        shared_language_keys=[
            SharedLanguageKey(
                key_id="ritual_callback",
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
    return runtime, {
        "root": root.atom_id,
        "conflict": conflict.atom_id,
        "distance_two": distance_two.atom_id,
        "constellation": constellation.atom_id,
        "shared": shared.atom_id,
        "shared_child": shared_child.atom_id,
    }


def _request_budget_runtime() -> tuple[RuntimeSession, str]:
    store = AtomStore()
    root = store.add_candidate(_candidate("budget_root", "Budget root memory.", "conv_budget_root", topics=["ops"]))
    neighbors: list[str] = []
    for index in range(GRAPH_NEIGHBOR_REQUEST_BUDGET + 3):
        atom = store.add_candidate(
            _candidate(f"budget_{index}", f"Budget neighbor {index}.", f"conv_budget_{index}", topics=["ops"])
        )
        store.mark_conflict(root.atom_id, atom.atom_id, reason="budget_conflict")
        neighbors.append(atom.atom_id)
    continuity = ContinuityStore()
    continuity.set_snapshot(ContinuitySnapshot(generated_at=datetime.now(timezone.utc)))
    runtime = RuntimeSession(retriever=MemoryRetriever(store), verifier=ClaimVerifier(), continuity_store=continuity)
    return runtime, root.atom_id


def test_graph_neighbors_payload_proves_true_distance_two_and_record_only_shared_language() -> None:
    runtime, atom_ids = _graph_runtime()

    payload = _build_graph_neighbors_payload(
        runtime,
        atom_id=atom_ids["root"],
        depth=2,
        node_limit=10,
        link_limit=10,
        include_shared_language=True,
    )

    neighbors = list(payload.get("neighbors") or [])
    neighbor_ids = [str(row.get("atom_id") or "") for row in neighbors]
    assert neighbor_ids[:3] == [atom_ids["conflict"], atom_ids["constellation"], atom_ids["shared"]]
    assert atom_ids["distance_two"] in neighbor_ids
    assert atom_ids["shared_child"] not in neighbor_ids

    distance_two = next(row for row in neighbors if str(row.get("atom_id") or "") == atom_ids["distance_two"])
    assert int(distance_two.get("distance") or 0) == 2
    assert distance_two.get("via_edge_kind") == "narrative_arc"

    shared = next(row for row in neighbors if str(row.get("atom_id") or "") == atom_ids["shared"])
    assert int(shared.get("distance") or 0) == 1
    assert shared.get("via_edge_kind") == "shared_language"

    links = list(payload.get("links") or [])
    assert {"source": atom_ids["root"], "target": atom_ids["conflict"], "kind": "conflict"} in links
    assert {"source": atom_ids["conflict"], "target": atom_ids["distance_two"], "kind": "narrative_arc"} in links
    assert {"source": atom_ids["root"], "target": atom_ids["shared"], "kind": "shared_language"} in links
    assert payload.get("truncated") is False


def test_graph_neighbors_payload_truncation_is_truthful_and_links_reference_kept_nodes() -> None:
    runtime, atom_ids = _graph_runtime()

    payload = _build_graph_neighbors_payload(
        runtime,
        atom_id=atom_ids["root"],
        depth=2,
        node_limit=1,
        link_limit=10,
        include_shared_language=True,
    )

    neighbors = list(payload.get("neighbors") or [])
    neighbor_ids = {str(row.get("atom_id") or "") for row in neighbors}
    assert neighbor_ids == {atom_ids["conflict"]}
    assert payload.get("truncated") is True
    truncation = dict(payload.get("truncation") or {})
    assert truncation.get("node_limit_hit") is True
    assert truncation.get("link_limit_hit") is False
    assert truncation.get("request_budget_hit") is False
    assert truncation.get("dropped_shared_language") is True

    links = list(payload.get("links") or [])
    assert links == [{"source": atom_ids["root"], "target": atom_ids["conflict"], "kind": "conflict"}]
    allowed_ids = neighbor_ids.union({atom_ids["root"]})
    assert all(str(row.get("source") or "") in allowed_ids for row in links)
    assert all(str(row.get("target") or "") in allowed_ids for row in links)


def test_graph_neighbors_payload_does_not_admit_unlinked_neighbors_when_link_limit_hits() -> None:
    runtime, atom_ids = _graph_runtime()

    payload = _build_graph_neighbors_payload(
        runtime,
        atom_id=atom_ids["root"],
        depth=2,
        node_limit=10,
        link_limit=1,
        include_shared_language=True,
    )

    neighbors = list(payload.get("neighbors") or [])
    neighbor_ids = {str(row.get("atom_id") or "") for row in neighbors}
    assert neighbor_ids == {atom_ids["conflict"]}

    links = list(payload.get("links") or [])
    assert links == [{"source": atom_ids["root"], "target": atom_ids["conflict"], "kind": "conflict"}]

    truncation = dict(payload.get("truncation") or {})
    assert truncation.get("link_limit_hit") is True
    assert truncation.get("node_limit_hit") is False
    assert truncation.get("request_budget_hit") is False
    assert truncation.get("dropped_shared_language") is True


def test_graph_neighbors_payload_dedupes_symmetric_edges_by_canonical_pair() -> None:
    runtime, atom_ids = _graph_runtime()
    runtime.retriever.store.mark_conflict(atom_ids["conflict"], atom_ids["constellation"], reason="symmetric_pair")

    payload = _build_graph_neighbors_payload(
        runtime,
        atom_id=atom_ids["root"],
        depth=2,
        node_limit=10,
        link_limit=10,
        include_shared_language=True,
    )

    conflict_pair_links = [
        row
        for row in list(payload.get("links") or [])
        if {str(row.get("source") or ""), str(row.get("target") or "")}
        == {atom_ids["conflict"], atom_ids["constellation"]}
        and str(row.get("kind") or "") == "conflict"
    ]
    assert len(conflict_pair_links) == 1


def test_graph_neighbors_payload_honors_root_detail_omission() -> None:
    runtime, atom_ids = _graph_runtime()

    payload = _build_graph_neighbors_payload(
        runtime,
        atom_id=atom_ids["root"],
        include_root_detail=False,
    )

    node = dict(payload.get("node") or {})
    assert node["atom_id"] == atom_ids["root"]
    assert "kind" in node
    assert "card_id" not in node
    assert "status" not in node
    assert "summary" not in node


def test_graph_neighbors_payload_enforces_request_budget() -> None:
    runtime, root_atom_id = _request_budget_runtime()

    payload = _build_graph_neighbors_payload(
        runtime,
        atom_id=root_atom_id,
        depth=2,
        node_limit=60,
        link_limit=60,
    )

    assert int(payload.get("requests_used") or 0) == GRAPH_NEIGHBOR_REQUEST_BUDGET
    assert payload.get("truncated") is True
    truncation = dict(payload.get("truncation") or {})
    assert truncation.get("request_budget_hit") is True
