from __future__ import annotations

from collections import deque
from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest

from engine.mcp.server import (
    AuthConfig,
    MCPServer,
    RuntimeApiClient,
    RuntimeApiError,
    ServerConfig,
    run_stdio_server,
    start_http_server,
    stop_http_server,
)


class _FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []
        self.native_graph_neighbors_available = True
        self._episode_rows = [
            {
                "episode_id": "ep_1",
                "title": "Late-session tea preference",
                "summary": "Tea keeps sessions smooth." * 40,
                "promotion_status": "approved",
                "topic_tags": ["tea", "preferences"],
                "actors": ["user", "assistant"],
                "cue_terms": ["tea", "late sessions"],
                "citations": ["conv_1#m_1"],
                "linked_atom_ids": ["atom_1"],
                "domain": "preference",
                "confidence": 0.88,
                "evidence_strength": 0.82,
                "retrieval_weight": 0.86,
                "updated_at": "2026-02-16T00:00:00+00:00",
            },
            {
                "episode_id": "ep_2",
                "title": "Roadmap checkpoint",
                "summary": "We locked three milestones and rollback safeguards.",
                "promotion_status": "disabled",
                "topic_tags": ["roadmap"],
                "actors": ["user"],
                "updated_at": "2026-02-16T00:00:00+00:00",
            },
            {
                "episode_id": "ep_3",
                "title": "Continuity guardrails",
                "summary": "Evidence-first response policy review.",
                "promotion_status": "approved",
                "topic_tags": ["continuity"],
                "actors": ["assistant"],
                "updated_at": "2026-02-16T00:00:00+00:00",
            },
        ]
        self._cards = [
            {
                "card_id": "card_atom_1",
                "atom_id": "atom_1",
                "kind": "event_card",
                "atom_status": "active",
                "summary": "Tea preference is frequently recalled.",
                "citations": ["conv_1#m_1"],
                "citation_count": 1,
                "contradiction": False,
                "confidence": 0.84,
                "evidence_strength": 0.79,
                "retrieval_weight": 0.83,
                "updated_at": "2026-02-16T00:00:00+00:00",
            },
            {
                "card_id": "card_atom_2",
                "atom_id": "atom_2",
                "kind": "event_card",
                "atom_status": "active",
                "summary": "Roadmap checkpoint includes rollback.",
                "citations": ["conv_2#m_2"],
                "citation_count": 1,
                "contradiction": False,
                "confidence": 0.76,
                "evidence_strength": 0.7,
                "retrieval_weight": 0.72,
                "updated_at": "2026-02-16T00:00:00+00:00",
            },
            {
                "card_id": "card_atom_3",
                "atom_id": "atom_3",
                "kind": "relationship_card",
                "atom_status": "active",
                "summary": "Continuity rules reference evidence.",
                "citations": ["conv_3#m_3"],
                "citation_count": 1,
                "contradiction": False,
                "confidence": 0.8,
                "evidence_strength": 0.78,
                "retrieval_weight": 0.75,
                "updated_at": "2026-02-16T00:00:00+00:00",
            },
        ]
        self._sessions = [
            {
                "session_id": "sess_1",
                "label": "default",
                "created_at": "2026-02-16T00:00:00+00:00",
                "updated_at": "2026-02-16T00:00:00+00:00",
                "turn_count": 1,
            },
            {
                "session_id": "sess_2",
                "label": "second",
                "created_at": "2026-02-16T00:00:00+00:00",
                "updated_at": "2026-02-16T00:00:00+00:00",
                "turn_count": 0,
            },
        ]
        self._proposals = [
            {
                "proposal_id": "prop_1",
                "kind": "delete",
                "status": "pending",
                "created_at": "2026-02-16T00:00:00+00:00",
                "reason_code": "manual_cleanup",
            }
        ]
        self._wizard_run_id = "wizard_test_1"
        self._explore_preferences: dict[str, dict[str, object]] = {}
        self._organizer_applied_profile: dict[str, object] = {}
        self._organizer_rollback: list[dict[str, object]] = []
        self._quicknote_notes: list[dict[str, object]] = []
        self._quicknote_buffers: dict[str, dict[str, object]] = {}
        self._quicknote_cursors: dict[str, int] = {}
        self._methodology_records: list[dict[str, object]] = []
        self._methodology_active_id: str = ""
        self._methodology_events: list[dict[str, object]] = []
        self._methodology_clusters: dict[str, dict[str, object]] = {}

    def get_json(self, path: str, *, query: dict[str, object] | None = None) -> dict[str, object]:
        query_obj = dict(query or {})
        self.calls.append((path, query_obj))
        if path == "/api/runtime/health":
            return {"ok": True, "status": "safe", "checks": []}
        if path == "/api/runtime/provider/config":
            return {"ok": True, "provider_config": {"model_name": "test-model", "adapters": ["openai"]}}
        if path == "/api/turns":
            return {
                "ok": True,
                "turns": [
                    {
                        "turn_id": "turn_1",
                        "session_id": "sess_1",
                        "response_text": "Hello",
                        "decision": "NO_MEMORY",
                        "citations": [],
                    }
                ],
            }
        if path == "/api/memory/episodes":
            return {"ok": True, "episodes": list(self._episode_rows)}
        if path == "/api/memory/cards":
            offset = int(query_obj.get("offset") or 0)
            limit = int(query_obj.get("limit") or len(self._cards))
            page = list(self._cards)[offset : offset + limit]
            return {
                "ok": True,
                "cards": page,
                "offset": offset,
                "limit": limit,
                "total": len(self._cards),
                "has_more": offset + len(page) < len(self._cards),
            }
        if path.startswith("/api/memory/atom/"):
            atom_id = path.rsplit("/", 1)[-1]
            return {
                "ok": True,
                "atom": {
                    "atom_id": atom_id,
                    "canonical_text": "Canonical memory text." * 40,
                    "status": "active",
                    "entities": ["user"],
                    "topics": ["memory"],
                    "confidence": 0.9,
                    "salience": 0.7,
                    "updated_at": "2026-02-16T00:00:00+00:00",
                    "source_refs": [
                        {
                            "source_id": "conv_1",
                            "message_id": "m_1",
                            "timestamp": "2026-02-16T00:00:00+00:00",
                        }
                    ],
                },
                "provenance_events": [
                    {
                        "event_id": "evt_1",
                        "event_kind": "import",
                        "created_at": "2026-02-16T00:00:00+00:00",
                    }
                ],
                "graph": {
                    "conflicts": ["atom_9"],
                    "constellation_neighbors": ["atom_2"],
                    "arc_neighbors": ["atom_3"],
                    "shared_language_keys": [{"key_id": "plan"}],
                },
            }
        if path == "/api/memory/graph-map":
            return {
                "ok": True,
                "nodes": [
                    {
                        "atom_id": "atom_1",
                        "card_id": "card_atom_1",
                        "kind": "event_card",
                        "atom_status": "active",
                        "summary": "Tea memory node",
                        "citation_count": 1,
                        "contradiction": False,
                    },
                    {
                        "atom_id": "atom_2",
                        "card_id": "card_atom_2",
                        "kind": "event_card",
                        "atom_status": "active",
                        "summary": "Roadmap memory node",
                        "citation_count": 1,
                        "contradiction": False,
                    },
                    {
                        "atom_id": "atom_3",
                        "card_id": "card_atom_3",
                        "kind": "relationship_card",
                        "atom_status": "active",
                        "summary": "Continuity memory node",
                        "citation_count": 1,
                        "contradiction": False,
                    },
                ],
                "links": [
                    {"source": "atom_1", "target": "atom_2", "kind": "conflict"},
                    {"source": "atom_2", "target": "atom_3", "kind": "narrative_arc"},
                    {"source": "atom_1", "target": "slk:plan", "kind": "shared_language"},
                ],
                "total": 3,
                "truncated": False,
            }
        if path == "/api/memory/graph":
            atom_id = str(query_obj.get("atom_id") or "")
            mapping = {
                "atom_1": [
                    {"source": "atom_1", "target": "atom_2", "kind": "conflict"},
                    {"source": "atom_1", "target": "slk:plan", "kind": "shared_language"},
                ],
                "atom_2": [{"source": "atom_2", "target": "atom_3", "kind": "narrative_arc"}],
                "atom_3": [],
            }
            return {
                "ok": True,
                "atom": {
                    "atom_id": atom_id,
                    "canonical_text": f"{atom_id} canonical",
                    "status": "active",
                    "entities": [],
                    "topics": [],
                    "source_refs": [],
                },
                "links": list(mapping.get(atom_id, [])),
            }
        if path == "/api/explore/start-here":
            return {
                "ok": True,
                "status": "ready",
                "buckets": {
                    "people": [
                        {
                            "anchor_id": "xander",
                            "label": "Xander",
                            "anchor_type": "person",
                            "score": 2.2,
                            "confidence": 0.88,
                            "support_count": 4,
                            "preferred_action": "",
                        }
                    ],
                    "projects": [
                        {
                            "anchor_id": "numquamoblita",
                            "label": "NumquamOblita",
                            "anchor_type": "project",
                            "score": 1.9,
                            "confidence": 0.84,
                            "support_count": 3,
                            "preferred_action": "",
                        }
                    ],
                    "topics": [],
                    "arcs": [],
                    "unresolved": [],
                },
                "stats": {"atom_count": 3, "total_anchors": 2, "truncated": False},
                "guardrails": {"bounded": True, "fail_closed": True},
            }
        if path == "/api/explore/expand":
            anchor_id = str(query_obj.get("anchor_id") or "anchor")
            anchor_type = str(query_obj.get("anchor_type") or "topic")
            return {
                "ok": True,
                "status": "ready",
                "anchor": {"anchor_id": anchor_id, "label": anchor_id.title(), "anchor_type": anchor_type, "matched_atom_count": 2},
                "connected_atoms": [
                    {
                        "atom_id": "atom_1",
                        "card_id": "card_atom_1",
                        "summary": "Xander discussion memory",
                        "confidence": 0.81,
                        "contradiction": False,
                        "source_ref": "conv_1#m_1",
                    }
                ],
                "next_hops": [
                    {
                        "anchor_id": "assistant",
                        "label": "Assistant",
                        "anchor_type": "person",
                        "score": 1.82,
                        "confidence": 0.82,
                        "preferred_action": "",
                    },
                    {
                        "anchor_id": "assistant",
                        "label": "assistant",
                        "anchor_type": "person",
                        "score": 1.7,
                        "confidence": 0.7,
                        "preferred_action": "",
                    },
                    {
                        "anchor_id": "numquamoblita",
                        "label": "NumquamOblita",
                        "anchor_type": "project",
                        "score": 1.72,
                        "confidence": 0.8,
                        "preferred_action": "",
                    }
                ],
                "truncated": False,
                "guardrails": {"bounded": True, "max_hop_depth": 3},
            }
        if path == "/api/explore/peek":
            anchor_id = str(query_obj.get("anchor_id") or "anchor")
            anchor_type = str(query_obj.get("anchor_type") or "topic")
            return {
                "ok": True,
                "status": "ready",
                "anchor": {"anchor_id": anchor_id, "label": anchor_id.title(), "anchor_type": anchor_type},
                "mode": "lightweight",
                "snippets": [
                    {
                        "atom_id": "atom_1",
                        "card_id": "card_atom_1",
                        "snippet": "Xander memory snippet",
                        "raw_excerpt": "Fuller excerpt for Xander memory snippet.",
                        "confidence": 0.82,
                        "source_id": "conv_1",
                        "source_ref": "conv_1#m_1",
                    }
                ],
                "count": 1,
                "truncated": False,
                "guardrails": {"bounded": True},
            }
        if path == "/api/explore/preferences":
            rows = list(self._explore_preferences.values())
            rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
            return {
                "ok": True,
                "preferences": rows,
                "count": len(rows),
            }
        if path == "/api/memory/quicknote/status":
            assistant_id = str(query_obj.get("assistant_id") or "assistant_default")
            session_id = str(query_obj.get("session_id") or "session_default")
            key = f"{assistant_id}::{session_id}"
            row = dict(self._quicknote_buffers.get(key) or {})
            note_ids = [str(item).strip() for item in list(row.get("note_ids") or []) if str(item).strip()]
            cap = int(row.get("cap") or 24)
            used = int(row.get("notes_proposed") or 0)
            return {
                "ok": True,
                "status": {
                    "assistant_id": assistant_id,
                    "session_id": session_id,
                    "pending_count": len(note_ids),
                    "cap": cap,
                    "cap_used": used,
                    "cap_remaining": max(0, cap - used),
                    "last_activity_at": str(row.get("last_activity_at") or ""),
                    "last_flush_at": str(row.get("last_flush_at") or ""),
                    "last_flush_reason": str(row.get("last_flush_reason") or ""),
                    "flush_count": int(row.get("flush_count") or 0),
                    "recommended_action": "flush_pending_notes" if note_ids else "continue",
                },
                "policy": {"mode": "proposal_only", "auto_apply": False},
                "config": {"session_cap": cap, "inactivity_timeout_seconds": 3600},
            }
        if path == "/api/explore/whats-new":
            assistant_id = str(query_obj.get("assistant_id") or "assistant_default")
            peek_only = str(query_obj.get("peek_only") or "").strip().lower() in {"1", "true", "yes"}
            last_seen = int(self._quicknote_cursors.get(assistant_id) or 0)
            items = [
                {
                    "note_id": str(row.get("note_id") or ""),
                    "session_id": str(row.get("session_id") or ""),
                    "summary": str(row.get("summary") or ""),
                    "importance": str(row.get("importance") or "normal"),
                    "status": str(row.get("status") or "proposed"),
                    "updated_at": str(row.get("updated_at") or ""),
                    "tags": list(row.get("tags") or []),
                }
                for row in self._quicknote_notes
                if str(row.get("assistant_id") or "") == assistant_id and int(row.get("revision") or 0) > last_seen
            ]
            items.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
            current_revision = max([int(row.get("revision") or 0) for row in self._quicknote_notes] + [0])
            if not peek_only:
                self._quicknote_cursors[assistant_id] = current_revision
            return {
                "ok": True,
                "assistant_id": assistant_id,
                "peek_only": peek_only,
                "cursor": {
                    "last_seen_revision": last_seen,
                    "current_revision": current_revision,
                    "last_seen_at": "2026-02-16T00:00:00+00:00",
                    "advanced": not peek_only,
                    "baseline_reset": False,
                    "store_signature": "atoms:3:sample:test",
                },
                "changes": {
                    "added_count": len(items),
                    "updated_count": 0,
                    "resolved_count": 0,
                    "items": items[:8],
                    "top_changed_anchors": [{"anchor_id": "memory", "label": "memory", "anchor_type": "topic", "change_count": len(items)}]
                    if items
                    else [],
                    "unresolved_highlights": items[:4],
                },
            }
        if path == "/api/system/usage-guide":
            return {
                "ok": True,
                "guide": {
                    "version": "quicknote.v1",
                    "quick_start": ["orient", "quicknote.propose", "quicknote.flush", "whats_new"],
                },
            }
        if path == "/api/methodology/records":
            status_filter = str(query_obj.get("status") or "all").strip().lower() or "all"
            offset = int(query_obj.get("offset") or 0)
            limit = int(query_obj.get("limit") or 40)
            rows = list(self._methodology_records)
            rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
            if status_filter != "all":
                rows = [row for row in rows if str(row.get("status") or "").strip().lower() == status_filter]
            page = rows[offset : offset + limit]
            return {
                "ok": True,
                "records": page,
                "offset": offset,
                "limit": limit,
                "total": len(rows),
                "has_more": offset + len(page) < len(rows),
                "status_filter": status_filter,
                "active_methodology_id": self._methodology_active_id,
            }
        if path.startswith("/api/methodology/records/"):
            methodology_id = path.rsplit("/", 1)[-1]
            for row in self._methodology_records:
                if str(row.get("methodology_id") or "") == methodology_id:
                    return {
                        "ok": True,
                        "record": dict(row),
                        "active_methodology_id": self._methodology_active_id,
                    }
            return {"ok": False}
        if path == "/api/methodology/corrections/clusters":
            limit = int(query_obj.get("limit") or 20)
            rows = list(self._methodology_clusters.values())
            rows.sort(key=lambda row: (int(row.get("count") or 0), str(row.get("last_seen_at") or "")), reverse=True)
            page = rows[:limit]
            return {
                "ok": True,
                "clusters": page,
                "count": len(page),
            }
        if path == "/api/methodology/readout":
            pending = 0
            for row in self._methodology_records:
                if str(row.get("approval_state") or "") == "pending":
                    pending += 1
            active = {}
            for row in self._methodology_records:
                if str(row.get("methodology_id") or "") == self._methodology_active_id:
                    active = dict(row)
                    break
            latest_events = list(self._methodology_events)[-10:]
            latest_events.reverse()
            return {
                "ok": True,
                "readout": {
                    "active_methodology_id": self._methodology_active_id,
                    "active_methodology": active,
                    "counts": {
                        "records_total": len(self._methodology_records),
                        "pending_review": pending,
                    },
                    "recent_events": latest_events,
                    "latest_maintenance": [],
                    "live_quality_snapshot": {"turns_considered": 3, "clarify_rate": 0.0},
                },
            }
        if path == "/api/wizard/organizer/state":
            return {
                "ok": True,
                "run_id": str(query_obj.get("run_id") or self._wizard_run_id),
                "organizer": {"applied_profile": dict(self._organizer_applied_profile)},
            }
        if path == "/api/chat/sessions":
            return {"ok": True, "sessions": list(self._sessions)}
        if path.startswith("/api/chat/session/") and path.endswith("/history"):
            session_id = path[len("/api/chat/session/") : -len("/history")]
            return {
                "ok": True,
                "session_id": session_id,
                "history": [
                    {
                        "turn_id": "turn_hist_1",
                        "session_id": session_id,
                        "timestamp": "2026-02-16T00:00:00+00:00",
                        "response_text": "History answer",
                        "decision": "NO_MEMORY",
                        "citations": [],
                        "memory_route": "none",
                        "route_reason": "smalltalk_routine",
                    }
                ],
            }
        if path.startswith("/api/turns/") and path.endswith("/why"):
            return {
                "ok": True,
                "why": {
                    "decision": "PASS",
                    "reason": "evidence present",
                    "decision_reason": "direct citation alignment",
                    "plain_summary": "safe",
                    "evidence_time_window": {"display": "unknown"},
                    "top_evidence": [
                        {"section": "core", "evidence_id": "ev_1", "summary": "Evidence row one", "citations": ["conv_1#m_1"]},
                        {"section": "core", "evidence_id": "ev_2", "summary": "Evidence row two", "citations": ["conv_2#m_2"]},
                    ],
                    "citations": ["conv_1#m_1", "conv_2#m_2"],
                    "citations_hidden": False,
                    "package_version": "v2",
                },
            }
        if path.startswith("/api/archive/citation/"):
            token = path[len("/api/archive/citation/") :]
            context_window = int(query_obj.get("context_window") or 3)
            return {
                "ok": True,
                "citation": token,
                "source_id": "conv_1",
                "message_id": "m_1",
                "context_window": context_window,
                "matches": [
                    {
                        "source_id": "conv_1",
                        "message_id": "m_1",
                        "timestamp": "2026-02-16T00:00:00+00:00",
                        "excerpt": "Evidence excerpt one.",
                        "is_target": True,
                        "distance": 0,
                    },
                    {
                        "source_id": "conv_1",
                        "message_id": "m_2",
                        "timestamp": "2026-02-16T00:01:00+00:00",
                        "excerpt": "Evidence excerpt two.",
                        "is_target": False,
                        "distance": 1,
                    },
                ],
            }
        if path == "/api/memory/proposals":
            status = str(query_obj.get("status") or "all")
            rows = list(self._proposals)
            if status != "all":
                rows = [row for row in rows if str(row.get("status") or "").lower() == status]
            return {"ok": True, "proposals": rows}
        if path == "/api/wizard/review/cards":
            return {
                "ok": True,
                "run_id": str(query_obj.get("run_id") or self._wizard_run_id),
                "cards": [
                    {
                        "episode_id": "ep_1",
                        "title": "Tea preference",
                        "summary": "User prefers tea in late sessions.",
                        "review_decision": "pending",
                    }
                ],
                "total": 1,
            }
        return {"ok": True}

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        headers: dict[str, object] | None = None,
        allow_error_status: bool = False,
    ) -> tuple[int, dict[str, object]]:
        del payload, headers
        method_text = str(method or "").strip().upper()
        query_obj = dict(query or {})
        if method_text != "GET":
            raise RuntimeApiError("runtime_api_missing_fixture", detail=f"{method_text} {path}")
        if path == "/api/memory/graph/neighbors":
            self.calls.append((path, query_obj))
            if not self.native_graph_neighbors_available:
                if allow_error_status:
                    return 404, {"error": "not found"}
                raise RuntimeApiError("runtime_api_http_error", status_code=404, detail="not found")
            atom_id = str(query_obj.get("atom_id") or "")
            depth = int(query_obj.get("depth") or 1)
            node_limit = int(query_obj.get("node_limit") or query_obj.get("limit") or 60)
            link_limit = int(query_obj.get("link_limit") or 120)
            include_shared_language = str(query_obj.get("include_shared_language") or "false").strip().lower() == "true"
            include_root_detail_raw = query_obj.get("include_root_detail")
            include_root_detail = (
                True
                if include_root_detail_raw is None
                else str(include_root_detail_raw).strip().lower() == "true"
            )
            if atom_id == "atom_1":
                neighbors = [
                    {"atom_id": "atom_2", "kind": "event_card", "distance": 1, "via_edge_kind": "conflict"},
                    {"atom_id": "atom_3", "kind": "relationship_card", "distance": 2, "via_edge_kind": "narrative_arc"},
                ]
                links = [
                    {"source": "atom_1", "target": "atom_2", "kind": "conflict"},
                    {"source": "atom_2", "target": "atom_3", "kind": "narrative_arc"},
                ]
                if include_shared_language:
                    neighbors.append(
                        {"atom_id": "atom_4", "kind": "event_card", "distance": 1, "via_edge_kind": "shared_language"}
                    )
                    links.append({"source": "atom_1", "target": "atom_4", "kind": "shared_language"})
                node_payload: dict[str, object] = {"atom_id": "atom_1", "kind": "event_card"}
                if include_root_detail:
                    node_payload.update(
                        {
                            "card_id": "card_atom_1",
                            "status": "active",
                            "summary": "Tea memory node",
                        }
                    )
                kept_neighbors = neighbors[:node_limit]
                kept_links = links[:link_limit]
                dropped_shared_language = False
                if include_shared_language:
                    all_shared_neighbor_ids = {
                        str(row.get("atom_id") or "")
                        for row in neighbors
                        if str(row.get("via_edge_kind") or "") == "shared_language"
                    }
                    kept_shared_neighbor_ids = {
                        str(row.get("atom_id") or "")
                        for row in kept_neighbors
                        if str(row.get("via_edge_kind") or "") == "shared_language"
                    }
                    all_shared_links = [row for row in links if str(row.get("kind") or "") == "shared_language"]
                    kept_shared_links = [row for row in kept_links if str(row.get("kind") or "") == "shared_language"]
                    dropped_shared_language = (
                        all_shared_neighbor_ids != kept_shared_neighbor_ids
                        or len(all_shared_links) != len(kept_shared_links)
                    )
                return 200, {
                    "ok": True,
                    "node": node_payload,
                    "neighbors": kept_neighbors,
                    "links": kept_links,
                    "depth": depth,
                    "node_limit": node_limit,
                    "link_limit": link_limit,
                    "requests_used": 2,
                    "truncated": len(neighbors) > node_limit or len(links) > link_limit,
                    "truncation": {
                        "node_limit_hit": len(neighbors) > node_limit,
                        "link_limit_hit": len(links) > link_limit,
                        "request_budget_hit": False,
                        "dropped_shared_language": dropped_shared_language,
                    },
                }
            if allow_error_status:
                return 404, {"error": "atom not found"}
            raise RuntimeApiError("runtime_api_http_error", status_code=404, detail="atom not found")
        return 200, self.get_json(path, query=query_obj)

    def post_json(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        payload_obj = dict(payload or {})
        self.post_calls.append((path, payload_obj))
        if path == "/api/methodology/create":
            methodology_id = f"meth_{len(self._methodology_records) + 1}"
            record = {
                "methodology_id": methodology_id,
                "trigger_condition": str(payload_obj.get("trigger_condition") or ""),
                "action": str(payload_obj.get("action") or ""),
                "rationale": str(payload_obj.get("rationale") or ""),
                "version": 1,
                "status": "draft",
                "approval_state": "pending",
                "created_at": "2026-02-16T00:00:00+00:00",
                "updated_at": "2026-02-16T00:00:00+00:00",
                "canary": {},
            }
            self._methodology_records.append(record)
            self._methodology_events.append({"event_type": "methodology_created", "methodology_id": methodology_id})
            return {"ok": True, "record": record}
        if path == "/api/methodology/review":
            methodology_id = str(payload_obj.get("methodology_id") or "")
            decision = str(payload_obj.get("decision") or "approve")
            for idx, row in enumerate(self._methodology_records):
                if str(row.get("methodology_id") or "") != methodology_id:
                    continue
                updated = dict(row)
                updated["approval_state"] = "approved" if decision == "approve" else "rejected"
                if decision == "reject":
                    updated["status"] = "retired"
                updated["updated_at"] = "2026-02-16T00:00:00+00:00"
                self._methodology_records[idx] = updated
                self._methodology_events.append({"event_type": "methodology_reviewed", "methodology_id": methodology_id})
                return {"ok": True, "record": updated}
            return {"ok": False}
        if path == "/api/methodology/canary/start":
            methodology_id = str(payload_obj.get("methodology_id") or "")
            for idx, row in enumerate(self._methodology_records):
                if str(row.get("methodology_id") or "") != methodology_id:
                    continue
                updated = dict(row)
                updated["status"] = "canary"
                updated["canary"] = {
                    "started_at": "2026-02-16T00:00:00+00:00",
                    "baseline_snapshot": {"turns_considered": 12, "clarify_rate": 0.0},
                    "latest_snapshot": {"turns_considered": 12, "clarify_rate": 0.0},
                    "latest_compare": {},
                    "evaluation_count": 0,
                    "rollback_triggered": False,
                    "auto_rollback": bool(payload_obj.get("auto_rollback", True)),
                    "previous_active_id": self._methodology_active_id,
                }
                updated["updated_at"] = "2026-02-16T00:00:00+00:00"
                self._methodology_records[idx] = updated
                self._methodology_events.append({"event_type": "methodology_canary_started", "methodology_id": methodology_id})
                return {"ok": True, "record": updated}
            return {"ok": False}
        if path == "/api/methodology/canary/evaluate":
            methodology_id = str(payload_obj.get("methodology_id") or "")
            for idx, row in enumerate(self._methodology_records):
                if str(row.get("methodology_id") or "") != methodology_id:
                    continue
                updated = dict(row)
                canary = dict(updated.get("canary") or {})
                count = int(canary.get("evaluation_count") or 0) + 1
                compare = {"should_rollback": False, "risk_label": "low", "reasons": [], "delta": {"clarify_rate": 0.0}}
                canary["evaluation_count"] = count
                canary["latest_compare"] = compare
                canary["latest_snapshot"] = {"turns_considered": 15, "clarify_rate": 0.0}
                updated["canary"] = canary
                updated["updated_at"] = "2026-02-16T00:00:00+00:00"
                self._methodology_records[idx] = updated
                self._methodology_events.append({"event_type": "methodology_canary_evaluated", "methodology_id": methodology_id})
                return {
                    "ok": True,
                    "methodology_id": methodology_id,
                    "status": updated["status"],
                    "canary": canary,
                    "comparison": compare,
                    "active_methodology_id": self._methodology_active_id,
                }
            return {"ok": False}
        if path == "/api/methodology/activate":
            methodology_id = str(payload_obj.get("methodology_id") or "")
            for idx, row in enumerate(self._methodology_records):
                if str(row.get("methodology_id") or "") == self._methodology_active_id and self._methodology_active_id != methodology_id:
                    retired = dict(row)
                    retired["status"] = "retired"
                    self._methodology_records[idx] = retired
            for idx, row in enumerate(self._methodology_records):
                if str(row.get("methodology_id") or "") != methodology_id:
                    continue
                updated = dict(row)
                updated["status"] = "active"
                updated["updated_at"] = "2026-02-16T00:00:00+00:00"
                self._methodology_records[idx] = updated
                self._methodology_active_id = methodology_id
                self._methodology_events.append({"event_type": "methodology_activated", "methodology_id": methodology_id})
                return {"ok": True, "record": updated, "active_methodology_id": self._methodology_active_id}
            return {"ok": False}
        if path == "/api/methodology/rollback":
            methodology_id = str(payload_obj.get("methodology_id") or "")
            restored = ""
            for idx, row in enumerate(self._methodology_records):
                if str(row.get("methodology_id") or "") != methodology_id:
                    continue
                retired = dict(row)
                retired["status"] = "retired"
                retired["updated_at"] = "2026-02-16T00:00:00+00:00"
                self._methodology_records[idx] = retired
            self._methodology_active_id = restored
            self._methodology_events.append({"event_type": "methodology_rollback", "methodology_id": methodology_id})
            return {
                "ok": True,
                "rolled_back_methodology_id": methodology_id,
                "restored_methodology_id": restored,
                "active_methodology_id": self._methodology_active_id,
            }
        if path == "/api/methodology/corrections/record":
            text = str(payload_obj.get("text") or "").strip()
            fingerprint = text.lower().replace(" ", "_")[:32] or "empty"
            cluster = dict(self._methodology_clusters.get(fingerprint) or {})
            cluster["cluster_id"] = str(cluster.get("cluster_id") or f"corr_cluster_{len(self._methodology_clusters) + 1}")
            cluster["fingerprint"] = fingerprint
            cluster["count"] = int(cluster.get("count") or 0) + 1
            cluster["last_seen_at"] = "2026-02-16T00:00:00+00:00"
            cluster["example_text"] = str(cluster.get("example_text") or text)
            generated: dict[str, object] = {}
            if int(cluster.get("count") or 0) >= 3 and not str(cluster.get("generated_methodology_id") or ""):
                generated_id = f"meth_{len(self._methodology_records) + 1}"
                generated = {
                    "methodology_id": generated_id,
                    "trigger_condition": "Repeated user correction pattern.",
                    "action": f"Address correction: {text}",
                    "rationale": "Auto-generated from repeated corrections.",
                    "version": 1,
                    "status": "draft",
                    "approval_state": "pending",
                    "created_at": "2026-02-16T00:00:00+00:00",
                    "updated_at": "2026-02-16T00:00:00+00:00",
                    "canary": {},
                }
                self._methodology_records.append(generated)
                cluster["generated_methodology_id"] = generated_id
            self._methodology_clusters[fingerprint] = cluster
            correction = {
                "correction_id": f"corr_{len(self._methodology_events) + 1}",
                "raw_text": text,
                "fingerprint": fingerprint,
                "created_at": "2026-02-16T00:00:00+00:00",
            }
            self._methodology_events.append({"event_type": "correction_recorded", "fingerprint": fingerprint})
            return {
                "ok": True,
                "correction": correction,
                "cluster": cluster,
                "generated_methodology": generated,
            }
        if path == "/api/methodology/maintenance/evaluate":
            evaluation = {
                "evaluation_id": f"maint_{len(self._methodology_events) + 1}",
                "created_at": "2026-02-16T00:00:00+00:00",
                "triggered": bool(payload_obj.get("force", False)),
                "risk_label": "medium" if bool(payload_obj.get("force", False)) else "low",
                "triggers": [{"trigger": "manual_probe", "severity": "low"}] if bool(payload_obj.get("force", False)) else [],
                "snapshot": {"turns_considered": 20, "clarify_rate": 0.0},
            }
            self._methodology_events.append({"event_type": "maintenance_evaluated", "evaluation_id": evaluation["evaluation_id"]})
            return {"ok": True, "evaluation": evaluation}
        if path == "/api/memory/quicknote/propose":
            assistant_id = str(payload_obj.get("assistant_id") or "assistant_default")
            session_id = str(payload_obj.get("session_id") or "session_default")
            key = f"{assistant_id}::{session_id}"
            row = dict(self._quicknote_buffers.get(key) or {"cap": 24, "notes_proposed": 0, "note_ids": []})
            note_id = f"qn_{len(self._quicknote_notes) + 1}"
            revision = len(self._quicknote_notes) + 1
            note = {
                "note_id": note_id,
                "assistant_id": assistant_id,
                "session_id": session_id,
                "summary": str(payload_obj.get("text") or ""),
                "importance": str(payload_obj.get("importance") or "normal"),
                "tags": list(payload_obj.get("tags") or []),
                "status": "proposed",
                "revision": revision,
                "updated_at": "2026-02-16T00:00:00+00:00",
            }
            self._quicknote_notes.append(note)
            note_ids = [str(item).strip() for item in list(row.get("note_ids") or []) if str(item).strip()]
            note_ids.append(note_id)
            row["note_ids"] = note_ids
            row["notes_proposed"] = int(row.get("notes_proposed") or 0) + 1
            row["cap"] = int(row.get("cap") or 24)
            row["last_activity_at"] = "2026-02-16T00:00:00+00:00"
            self._quicknote_buffers[key] = row
            return {
                "ok": True,
                "accepted": True,
                "status": "proposed",
                "note": {"note_id": note_id, "summary": str(note["summary"]), "status": "proposed"},
                "status_info": {
                    "assistant_id": assistant_id,
                    "session_id": session_id,
                    "pending_count": len(note_ids),
                    "cap": int(row.get("cap") or 24),
                    "cap_used": int(row.get("notes_proposed") or 0),
                    "cap_remaining": max(0, int(row.get("cap") or 24) - int(row.get("notes_proposed") or 0)),
                },
                "inactivity_flushes": [],
            }
        if path == "/api/memory/quicknote/propose-batch":
            notes_raw = list(payload_obj.get("notes") or [])
            accepted = 0
            results: list[dict[str, object]] = []
            for index, row in enumerate(notes_raw):
                if not isinstance(row, dict) or not str(row.get("text") or "").strip():
                    results.append({"index": index, "accepted": False, "status": "invalid_item"})
                    continue
                single = self.post_json(
                    "/api/memory/quicknote/propose",
                    {
                        "assistant_id": payload_obj.get("assistant_id"),
                        "session_id": payload_obj.get("session_id"),
                        "text": row.get("text"),
                        "importance": row.get("importance") or payload_obj.get("importance"),
                        "tags": row.get("tags") or payload_obj.get("tags") or [],
                    },
                )
                results.append({"index": index, "accepted": True, "status": "proposed", "note": dict(single.get("note") or {})})
                accepted += 1
            assistant_id = str(payload_obj.get("assistant_id") or "assistant_default")
            session_id = str(payload_obj.get("session_id") or "session_default")
            key = f"{assistant_id}::{session_id}"
            row = dict(self._quicknote_buffers.get(key) or {})
            return {
                "ok": True,
                "assistant_id": assistant_id,
                "session_id": session_id,
                "accepted_count": accepted,
                "duplicate_count": 0,
                "rejected_count": max(0, len(notes_raw) - accepted),
                "results": results,
                "status": {
                    "assistant_id": assistant_id,
                    "session_id": session_id,
                    "pending_count": len(list(row.get("note_ids") or [])),
                    "cap": int(row.get("cap") or 24),
                    "cap_used": int(row.get("notes_proposed") or 0),
                    "cap_remaining": max(0, int(row.get("cap") or 24) - int(row.get("notes_proposed") or 0)),
                },
                "inactivity_flushes": [],
            }
        if path == "/api/memory/quicknote/flush":
            assistant_id = str(payload_obj.get("assistant_id") or "assistant_default")
            session_id = str(payload_obj.get("session_id") or "session_default")
            key = f"{assistant_id}::{session_id}"
            row = dict(self._quicknote_buffers.get(key) or {"cap": 24, "notes_proposed": 0, "note_ids": []})
            note_ids = [str(item).strip() for item in list(row.get("note_ids") or []) if str(item).strip()]
            for note in self._quicknote_notes:
                if str(note.get("note_id") or "") in note_ids:
                    note["status"] = "submitted"
                    note["updated_at"] = "2026-02-16T00:00:00+00:00"
            flushed_count = len(note_ids)
            row["note_ids"] = []
            row["last_flush_at"] = "2026-02-16T00:00:00+00:00"
            row["last_flush_reason"] = str(payload_obj.get("reason") or "manual")
            row["flush_count"] = int(row.get("flush_count") or 0) + 1
            self._quicknote_buffers[key] = row
            return {
                "ok": True,
                "assistant_id": assistant_id,
                "session_id": session_id,
                "reason": str(payload_obj.get("reason") or "manual"),
                "flushed_count": flushed_count,
                "noop": flushed_count == 0,
                "status_counts": {"submitted": flushed_count} if flushed_count else {},
                "status": {
                    "assistant_id": assistant_id,
                    "session_id": session_id,
                    "pending_count": 0,
                    "cap": int(row.get("cap") or 24),
                    "cap_used": int(row.get("notes_proposed") or 0),
                    "cap_remaining": max(0, int(row.get("cap") or 24) - int(row.get("notes_proposed") or 0)),
                },
                "inactivity_flushes": [],
            }
        if path == "/api/chat/session/start":
            label = str(payload_obj.get("label") or "session")
            return {
                "ok": True,
                "session": {
                    "session_id": "sess_new",
                    "label": label,
                    "created_at": "2026-02-16T00:00:00+00:00",
                    "updated_at": "2026-02-16T00:00:00+00:00",
                    "turn_count": 0,
                },
            }
        if path in {"/api/chat", "/api/chat/session/sess_1/turn"}:
            return {
                "ok": True,
                "turn": {
                    "turn_id": "turn_1",
                    "session_id": "sess_1",
                    "timestamp": "2026-02-16T00:00:00+00:00",
                    "response_text": "Memory-backed answer",
                    "decision": "PASS",
                    "citations": ["conv_1#m_1"],
                    "memory_route": "ltm_light",
                    "route_reason": "memory_signal_probe",
                    "retrieval_stop_reason": "single_pass",
                    "retrieval_passes": 1,
                    "memory_cards": [
                        {
                            "card_id": "card_atom_1",
                            "summary": "Raw excerpt summary.",
                            "summary_abstractive": "User favors tea for late sessions.",
                            "raw_excerpt": "User said tea keeps sessions smooth during late hours.",
                            "confidence": 0.84,
                            "citations": ["conv_1#m_1"],
                        }
                    ],
                },
            }
        if path == "/api/chat/session/sess_1/label":
            return {
                "ok": True,
                "session": {
                    "session_id": "sess_1",
                    "label": str(payload_obj.get("label") or "renamed"),
                    "created_at": "2026-02-16T00:00:00+00:00",
                    "updated_at": "2026-02-16T00:05:00+00:00",
                    "turn_count": 1,
                },
            }
        if path == "/api/chat/route-preview":
            return {
                "ok": True,
                "preview": {
                    "route": "none",
                    "reason": "smalltalk_routine",
                    "reason_text": "Routine small talk, memory lookup skipped.",
                },
            }
        if path == "/api/chat/context-package":
            return {
                "ok": True,
                "package": {
                    "package_version": "v2",
                    "message": str(payload_obj.get("message") or ""),
                    "retrieval_stats": {
                        "memory_route": "ltm_light",
                        "retrieval_stop_reason": "single_pass",
                        "retrieved_atom_ids": ["atom_1", "atom_2"],
                    },
                },
            }
        if path.startswith("/api/memory/episodes/") and path.endswith("/disable"):
            episode_id = path[len("/api/memory/episodes/") : -len("/disable")]
            return {"ok": True, "episode": {"episode_id": episode_id, "promotion_status": "disabled"}}
        if path.startswith("/api/memory/episodes/") and path.endswith("/enable"):
            episode_id = path[len("/api/memory/episodes/") : -len("/enable")]
            return {"ok": True, "episode": {"episode_id": episode_id, "promotion_status": "approved"}}
        if path.startswith("/api/memory/episodes/") and path.endswith("/edit"):
            episode_id = path[len("/api/memory/episodes/") : -len("/edit")]
            title = str(payload_obj.get("title") or "Edited")
            return {"ok": True, "episode": {"episode_id": episode_id, "promotion_status": "approved", "title": title}}
        if path == "/api/memory/episodes/undo-last":
            return {
                "ok": True,
                "undo": {"action": "episode_edit", "restored_path": "runtime/backups/test_backup.json"},
                "reload": {"loaded_cards": 2},
            }
        if path == "/api/memory/proposals/create-edit":
            proposal = {
                "proposal_id": "prop_edit_1",
                "kind": "edit",
                "status": "pending",
                "created_at": "2026-02-16T00:00:00+00:00",
                "reason_code": str(payload_obj.get("reason_code") or ""),
            }
            self._proposals.append(proposal)
            return {"ok": True, "proposal": proposal}
        if path == "/api/memory/proposals/create-delete":
            proposal = {
                "proposal_id": "prop_delete_1",
                "kind": "delete",
                "status": "pending",
                "created_at": "2026-02-16T00:00:00+00:00",
                "reason_code": str(payload_obj.get("reason_code") or ""),
            }
            self._proposals.append(proposal)
            return {"ok": True, "proposal": proposal}
        if path.startswith("/api/memory/proposals/") and path.endswith("/approve"):
            proposal_id = path[len("/api/memory/proposals/") : -len("/approve")]
            status = "applied" if bool(payload_obj.get("apply")) else "approved"
            for row in self._proposals:
                if str(row.get("proposal_id")) == proposal_id:
                    row["status"] = status
                    return {"ok": True, "proposal": row}
            return {"ok": True, "proposal": {"proposal_id": proposal_id, "status": status}}
        if path.startswith("/api/memory/proposals/") and path.endswith("/reject"):
            proposal_id = path[len("/api/memory/proposals/") : -len("/reject")]
            for row in self._proposals:
                if str(row.get("proposal_id")) == proposal_id:
                    row["status"] = "rejected"
                    return {"ok": True, "proposal": row}
            return {"ok": True, "proposal": {"proposal_id": proposal_id, "status": "rejected"}}
        if path == "/api/wizard/start":
            mode = str(payload_obj.get("mode") or "resume")
            return {
                "ok": True,
                "run_id": self._wizard_run_id,
                "state": {"run_id": self._wizard_run_id, "current_stage": "welcome_resume", "mode": mode},
            }
        if path == "/api/wizard/import/validate":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "status": "safe",
                "conversation_count": 2,
                "message_count": 6,
                "issues": [],
            }
        if path == "/api/wizard/import/run":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "store_path": str(payload_obj.get("store_path") or "runtime/imports/atoms.sqlite3"),
                "reports": {"json": "runtime/imports/import.json", "md": "runtime/imports/import.md"},
            }
        if path == "/api/wizard/build/run":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "policy_preset": str(payload_obj.get("policy_preset") or "strict"),
                "draft_path": "runtime/episodes/draft.json",
                "rejects_path": "runtime/episodes/rejects.json",
                "readout_path": "runtime/episodes/readout.md",
                "counts": {"episode_count": 1},
            }
        if path == "/api/wizard/review/update":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "episode_id": str(payload_obj.get("episode_id") or ""),
            }
        if path == "/api/wizard/review/compile":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "reviewed_path": "runtime/episodes/episode_cards.reviewed.json",
                "reviewed_snapshot_path": "runtime/episodes/episode_cards.reviewed_stamp.json",
                "episode_count": 1,
            }
        if path == "/api/wizard/verify/run":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "status": "Safe",
                "checks": [{"id": "store", "status": "ok"}],
                "actionable_links": [{"id": "review", "api_path": "/api/wizard/review/cards"}],
            }
        if path == "/api/wizard/go-live":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "runtime_url": "http://127.0.0.1:7340/",
                "provider_config": {"model_name": "test-model", "adapters": ["openai"]},
                "published_pointers": {"store_path": "runtime/imports/atoms.sqlite3"},
            }
        if path == "/api/wizard/restore-last-published":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "published_pointers": {"store_path": "runtime/imports/atoms.sqlite3"},
            }
        if path == "/api/explore/preferences":
            anchor_id = str(payload_obj.get("anchor_id") or "").strip().lower()
            anchor_type = str(payload_obj.get("anchor_type") or "topic").strip().lower()
            action = str(payload_obj.get("action") or "").strip().lower()
            key = f"{anchor_type}:{anchor_id}"
            if action == "clear":
                self._explore_preferences.pop(key, None)
                return {
                    "ok": True,
                    "applied": True,
                    "removed": True,
                    "count": len(self._explore_preferences),
                }
            row = {
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "action": action,
                "weight": 1.0,
                "updated_at": "2026-02-16T00:10:00+00:00",
            }
            self._explore_preferences[key] = row
            return {
                "ok": True,
                "applied": True,
                "removed": False,
                "preference": row,
                "count": len(self._explore_preferences),
            }
        if path == "/api/wizard/organizer/inventory":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "inventory": {
                    "status": "ready",
                    "counts": {"atom_count": 3, "total_anchors": 2, "typed_candidates": 2},
                    "typed_candidates": [
                        {
                            "anchor_id": "xander",
                            "label": "Xander",
                            "anchor_type": "person",
                            "score": 2.1,
                            "confidence": 0.86,
                            "support_count": 3,
                            "risk_class": "safe",
                        },
                        {
                            "anchor_id": "numquamoblita",
                            "label": "NumquamOblita",
                            "anchor_type": "project",
                            "score": 1.9,
                            "confidence": 0.83,
                            "support_count": 2,
                            "risk_class": "safe",
                        },
                    ],
                },
            }
        if path == "/api/wizard/organizer/dedupe":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "dedupe": {
                    "counts": {"proposal_count": 1, "safe_count": 1, "review_count": 0},
                    "proposals": [
                        {
                            "proposal_id": "org_dedupe_0001",
                            "anchor_type": "project",
                            "canonical_label": "NumquamOblita",
                            "aliases": ["NumquamOblita", "NO"],
                            "support_count": 4,
                            "confidence": 0.84,
                            "risk_class": "safe",
                        }
                    ],
                },
            }
        if path == "/api/wizard/organizer/conflicts":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "conflicts": {
                    "counts": {"conflicts": 1, "ambiguities": 1},
                    "conflict_queue": [{"atom_id": "atom_9", "severity": "medium"}],
                    "ambiguity_queue": [{"anchor_id": "arc-1", "risk_class": "review"}],
                },
            }
        if path == "/api/wizard/organizer/package":
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "package": {
                    "package_id": "org_pkg_test",
                    "counts": {"safe_operations": 1, "review_operations": 0, "conflicts": 1, "ambiguities": 1},
                    "safe_operations": [{"proposal_id": "org_dedupe_0001"}],
                    "review_operations": [],
                },
            }
        if path == "/api/wizard/organizer/apply":
            dry_run = bool(payload_obj.get("dry_run"))
            if dry_run:
                return {
                    "ok": True,
                    "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                    "applied": False,
                    "dry_run": True,
                    "safe_operation_count": 1,
                    "profile_preview": {"package_id": "org_pkg_test"},
                }
            previous = dict(self._organizer_applied_profile)
            self._organizer_rollback.append({"rollback_id": "org_rb_test", "applied_profile": previous})
            self._organizer_applied_profile = {
                "package_id": "org_pkg_test",
                "safe_operation_count": 1,
                "applied_operation_ids": ["org_dedupe_0001"],
            }
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "applied": True,
                "dry_run": False,
                "rollback_id": "org_rb_test",
                "safe_operation_count": 1,
                "profile": dict(self._organizer_applied_profile),
            }
        if path == "/api/wizard/organizer/verify":
            status = "safe" if self._organizer_applied_profile else "needs_attention"
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "verify": {
                    "status": status,
                    "metrics": {
                        "typed_candidates": 2,
                        "dedupe_proposals": 1,
                        "safe_operations": 1,
                        "applied_safe_operations": len(list(self._organizer_applied_profile.get("applied_operation_ids") or [])),
                        "conflicts_open": 1,
                        "ambiguities_open": 1,
                        "quality_delta": 1,
                    },
                    "recommendation": "review_conflicts_and_ambiguities" if status != "safe" else "ready_for_next_cycle",
                },
            }
        if path == "/api/wizard/organizer/restore-last":
            if self._organizer_rollback:
                snapshot = self._organizer_rollback.pop()
                self._organizer_applied_profile = dict(snapshot.get("applied_profile") or {})
                return {
                    "ok": True,
                    "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                    "restored": True,
                    "snapshot": snapshot,
                    "applied_profile": dict(self._organizer_applied_profile),
                    "remaining_snapshots": len(self._organizer_rollback),
                }
            return {
                "ok": True,
                "run_id": str(payload_obj.get("run_id") or self._wizard_run_id),
                "restored": False,
                "snapshot": {},
                "applied_profile": dict(self._organizer_applied_profile),
                "remaining_snapshots": 0,
            }
        return {"ok": True}


def _call(server: MCPServer, request_id: int, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    result = server.handle_request(payload)
    assert isinstance(result, dict)
    return result


_PHASE4_PERMISSION_TOOL_CALLS: list[tuple[str, dict[str, object]]] = [
    ("memory.disable_episode", {"episode_id": "ep_1", "reason": "test"}),
    ("memory.enable_episode", {"episode_id": "ep_1"}),
    ("memory.edit_episode", {"episode_id": "ep_1", "patch": {"title": "Updated"}, "dry_run": True}),
    ("memory.undo_last_change", {"scope": "episode_edits"}),
    ("proposals.list", {"status": "open"}),
    (
        "proposals.create_edit",
        {
            "target_id": "atom_1",
            "patch": {"canonical_text": "Edited canonical text"},
            "reason": "manual_edit",
            "dry_run": True,
        },
    ),
    ("proposals.create_delete", {"target_id": "atom_2", "reason": "cleanup", "dry_run": True}),
    ("proposals.approve", {"proposal_id": "prop_edit_1", "apply": False}),
    ("proposals.reject", {"proposal_id": "prop_delete_1", "note": "invalid"}),
]

_PHASE4_MUTATION_TOOL_CALLS: list[tuple[str, dict[str, object]]] = [
    row for row in _PHASE4_PERMISSION_TOOL_CALLS if row[0] != "proposals.list"
]


def _decode_framed_json_messages(buffer: bytes) -> list[dict[str, object]]:
    index = 0
    out: list[dict[str, object]] = []
    while index < len(buffer):
        head_end = buffer.find(b"\r\n\r\n", index)
        if head_end < 0:
            break
        header_blob = buffer[index:head_end].decode("utf-8", errors="replace")
        content_length = 0
        for line in header_blob.split("\r\n"):
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() == "content-length":
                content_length = int(value.strip())
                break
        body_start = head_end + 4
        body_end = body_start + content_length
        if body_end > len(buffer):
            break
        body = buffer[body_start:body_end]
        out.append(json.loads(body.decode("utf-8")))
        index = body_end
    return out


def _http_post_json(url: str, payload: dict[str, object], *, token: str | None = None) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            return int(response.status), body
    except HTTPError as exc:
        body_raw = exc.read().decode("utf-8", errors="replace")
        body = json.loads(body_raw) if body_raw.strip() else {}
        return int(exc.code), body


def _http_post_with_headers(url: str, payload: dict[str, object], *, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
    parsed = urlparse(url)
    assert parsed.hostname is not None
    assert parsed.port is not None
    body = json.dumps(payload).encode("utf-8")
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.putrequest("POST", parsed.path or "/")
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.endheaders()
        connection.send(body)
        response = connection.getresponse()
        payload_text = response.read().decode("utf-8", errors="replace")
        payload_obj = json.loads(payload_text) if payload_text.strip() else {}
        return int(response.status), payload_obj
    finally:
        connection.close()


def test_mcp_initialize_and_tools_list_default_role() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    init = _call(server, 1, "initialize", {"clientInfo": {"name": "unit"}})
    assert "result" in init
    result = dict(init["result"])
    assert result["protocolVersion"] == config.protocol_version

    tools = _call(server, 2, "tools/list")
    listed = list(dict(tools["result"]).get("tools") or [])
    names = {str(item.get("name") or "") for item in listed if isinstance(item, dict)}
    assert "capabilities.get" in names
    assert "ops.health" in names
    assert "memory.list_episodes" in names
    assert "memory.graph_neighbors" in names
    assert "chat.turn" in names
    assert "chat.build_context_package" in names
    assert "why.explain_turn" in names
    assert "evidence.resolve_citation" in names


def test_mcp_initialize_requires_token_when_configured() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer", viewer_token="v", operator_token="o", admin_token="a"),
    )
    server = MCPServer(config=config, api_client=client)

    denied = _call(server, 1, "initialize", {})
    assert "error" in denied
    assert int(dict(denied["error"]).get("code") or 0) == -32001

    init = _call(server, 2, "initialize", {"auth_token": "o"})
    assert "result" in init

    called = _call(server, 3, "tools/call", {"name": "capabilities.get", "arguments": {}})
    result = dict(called["result"])
    structured = dict(result.get("structuredContent") or {})
    auth = dict(structured.get("auth") or {})
    assert auth.get("session_role") == "operator"


def test_mcp_tool_ops_health_calls_runtime_api() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    response = _call(server, 2, "tools/call", {"name": "ops.health", "arguments": {}})
    result = dict(response["result"])
    structured = dict(result.get("structuredContent") or {})
    assert structured.get("status") == "safe"
    assert client.calls == [("/api/runtime/health", {})]


def test_mcp_resources_and_prompts() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    _call(server, 2, "tools/call", {"name": "capabilities.get", "arguments": {}})
    resources = _call(server, 3, "resources/list")
    listed = list(dict(resources["result"]).get("resources") or [])
    uris = {str(item.get("uri") or "") for item in listed if isinstance(item, dict)}
    assert "resource://capabilities" in uris
    assert "resource://audit/summary" in uris

    read = _call(server, 4, "resources/read", {"uri": "resource://audit/summary"})
    contents = list(dict(read["result"]).get("contents") or [])
    assert contents
    text = str(dict(contents[0]).get("text") or "")
    payload = json.loads(text)
    assert int(payload.get("event_count") or 0) >= 1

    prompts = _call(server, 5, "prompts/list")
    rows = list(dict(prompts["result"]).get("prompts") or [])
    names = {str(item.get("name") or "") for item in rows if isinstance(item, dict)}
    assert "memory_safe_recall" in names

    prompt = _call(server, 6, "prompts/get", {"name": "citation_discipline"})
    messages = list(dict(prompt["result"]).get("messages") or [])
    assert messages


def test_mcp_memory_list_episodes_and_get_episode() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
        max_text_chars=80,
        max_list_limit=2,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    listed = _call(
        server,
        2,
        "tools/call",
        {"name": "memory.list_episodes", "arguments": {"status": "all", "limit": 50, "offset": 0}},
    )
    payload = dict(dict(listed["result"]).get("structuredContent") or {})
    episodes = list(payload.get("episodes") or [])
    assert payload.get("limit") == 2
    assert len(episodes) == 2
    assert str(dict(episodes[0]).get("summary") or "").endswith("…")
    assert client.calls[-1][0] == "/api/memory/episodes"

    detail = _call(
        server,
        3,
        "tools/call",
        {"name": "memory.get_episode", "arguments": {"episode_id": "ep_1"}},
    )
    episode = dict(dict(detail["result"]).get("structuredContent") or {}).get("episode")
    assert isinstance(episode, dict)
    assert str(dict(episode).get("episode_id") or "") == "ep_1"
    assert "linked_atom_ids" in dict(episode)


def test_mcp_memory_atoms_graph_and_neighbors_bounds() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
        max_text_chars=72,
        max_list_limit=2,
        max_graph_nodes=2,
        max_graph_links=2,
        max_neighbor_expansion_requests=4,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    atoms_call = _call(
        server,
        2,
        "tools/call",
        {
            "name": "memory.list_atoms",
            "arguments": {"status": "all", "kind": "all", "contradiction": "all", "limit": 20, "offset": 0},
        },
    )
    atoms_payload = dict(dict(atoms_call["result"]).get("structuredContent") or {})
    atoms = list(atoms_payload.get("atoms") or [])
    assert atoms_payload.get("limit") == 2
    assert len(atoms) == 2
    assert str(dict(atoms[0]).get("atom_id") or "").startswith("atom_")

    atom_detail = _call(server, 3, "tools/call", {"name": "memory.get_atom", "arguments": {"atom_id": "atom_1"}})
    atom_payload = dict(dict(atom_detail["result"]).get("structuredContent") or {})
    atom = dict(atom_payload.get("atom") or {})
    assert atom.get("atom_id") == "atom_1"
    assert str(atom.get("canonical_text") or "").endswith("…")
    assert atom_payload.get("mode") == "compact"
    graph_compact = dict(atom_payload.get("graph") or {})
    neighbors_compact = list(graph_compact.get("neighbor_summaries") or [])
    assert neighbors_compact
    assert "constellation_neighbors" not in graph_compact

    atom_detail_full = _call(
        server,
        3_1,
        "tools/call",
        {"name": "memory.get_atom", "arguments": {"atom_id": "atom_1", "mode": "full"}},
    )
    atom_payload_full = dict(dict(atom_detail_full["result"]).get("structuredContent") or {})
    graph_full = dict(atom_payload_full.get("graph") or {})
    assert atom_payload_full.get("mode") == "full"
    assert list(graph_full.get("constellation_neighbors") or [])

    graph_map = _call(server, 4, "tools/call", {"name": "memory.graph_map", "arguments": {"limit": 10}})
    graph_payload = dict(dict(graph_map["result"]).get("structuredContent") or {})
    nodes = list(graph_payload.get("nodes") or [])
    links = list(graph_payload.get("links") or [])
    assert len(nodes) == 2
    assert len(links) == 2
    assert bool(graph_payload.get("truncated")) is True

    neighbors = _call(
        server,
        5,
        "tools/call",
        {
            "name": "memory.graph_neighbors",
            "arguments": {
                "node_id": "atom_1",
                "depth": 2,
                "limit": 5,
                "include_shared_language": True,
            },
        },
    )
    neighbor_payload = dict(dict(neighbors["result"]).get("structuredContent") or {})
    neighbor_rows = list(neighbor_payload.get("neighbors") or [])
    assert any(str(dict(row).get("atom_id") or "") == "atom_2" for row in neighbor_rows)
    assert any(str(dict(row).get("atom_id") or "") == "atom_3" for row in neighbor_rows)
    assert int(neighbor_payload.get("requests_used") or 0) == 2
    assert int(neighbor_payload.get("node_limit") or 0) == 2
    assert int(neighbor_payload.get("link_limit") or 0) == 2
    assert dict(neighbor_payload.get("truncation") or {}).get("request_budget_hit") is False


def test_mcp_memory_graph_neighbors_native_includes_shared_language_when_within_bounds() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
        max_graph_nodes=5,
        max_graph_links=5,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    neighbors = _call(
        server,
        2,
        "tools/call",
        {
            "name": "memory.graph_neighbors",
            "arguments": {"node_id": "atom_1", "depth": 2, "limit": 5, "include_shared_language": True},
        },
    )
    payload = dict(dict(neighbors["result"]).get("structuredContent") or {})
    rows = list(payload.get("neighbors") or [])
    assert any(str(dict(row).get("atom_id") or "") == "atom_4" for row in rows)
    assert any(str(dict(link).get("kind") or "") == "shared_language" for link in list(payload.get("links") or []))


def test_mcp_memory_graph_neighbors_native_can_omit_root_detail() -> None:
    client = _FakeApiClient()
    server = MCPServer(
        config=ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer")),
        api_client=client,
    )

    _call(server, 1, "initialize", {})
    neighbors = _call(
        server,
        2,
        "tools/call",
        {"name": "memory.graph_neighbors", "arguments": {"node_id": "atom_1", "include_root_detail": False}},
    )
    payload = dict(dict(neighbors["result"]).get("structuredContent") or {})
    node = dict(payload.get("node") or {})
    assert node.get("atom_id") == "atom_1"
    assert node.get("kind") == "event_card"
    assert "card_id" not in node
    assert "summary" not in node


def test_mcp_memory_graph_neighbors_falls_back_when_native_endpoint_is_unavailable() -> None:
    client = _FakeApiClient()
    client.native_graph_neighbors_available = False
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
        max_graph_nodes=5,
        max_graph_links=5,
        max_neighbor_expansion_requests=4,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    neighbors = _call(
        server,
        2,
        "tools/call",
        {"name": "memory.graph_neighbors", "arguments": {"node_id": "atom_1", "depth": 2, "limit": 5}},
    )
    payload = dict(dict(neighbors["result"]).get("structuredContent") or {})
    rows = list(payload.get("neighbors") or [])
    assert any(str(dict(row).get("atom_id") or "") == "atom_2" for row in rows)
    assert any(str(dict(row).get("atom_id") or "") == "atom_3" for row in rows)
    assert any(
        str(dict(row).get("atom_id") or "") == "atom_3" and int(dict(row).get("distance") or 0) == 2
        for row in rows
    )
    native_query = next(query for path, query in client.calls if path == "/api/memory/graph/neighbors")
    assert native_query.get("limit") == 5
    assert int(payload.get("requests_used") or 0) >= 2
    assert any(path == "/api/memory/graph/neighbors" for path, _query in client.calls)
    assert any(path == "/api/memory/graph" for path, _query in client.calls)


def test_mcp_memory_graph_neighbors_fallback_continues_expanding_kept_nodes_after_node_cap() -> None:
    class _LegacyOnlyClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def get_json(self, path: str, query: dict[str, object] | None = None) -> dict[str, object]:
            query_obj = dict(query or {})
            self.calls.append((path, query_obj))
            if path != "/api/memory/graph":
                raise RuntimeApiError("runtime_api_missing_fixture", detail=path)
            atom_id = str(query_obj.get("atom_id") or "")
            mapping = {
                "atom_1": [
                    {"source": "atom_1", "target": "atom_2", "kind": "conflict"},
                    {"source": "atom_1", "target": "atom_3", "kind": "narrative_arc"},
                ],
                "atom_2": [{"source": "atom_2", "target": "atom_3", "kind": "narrative_arc"}],
                "atom_3": [],
            }
            return {
                "ok": True,
                "atom": {"atom_id": atom_id, "canonical_text": f"{atom_id} canonical", "status": "active"},
                "links": list(mapping.get(atom_id, [])),
            }

    client = _LegacyOnlyClient()
    server = MCPServer(
        config=ServerConfig(
            runtime_base_url="http://127.0.0.1:7340",
            auth=AuthConfig(default_role="viewer"),
            max_graph_nodes=5,
            max_graph_links=5,
            max_neighbor_expansion_requests=4,
        ),
        api_client=client,
    )

    _call(server, 1, "initialize", {})
    neighbors = _call(
        server,
        2,
        "tools/call",
        {"name": "memory.graph_neighbors", "arguments": {"node_id": "atom_1", "depth": 2, "limit": 2}},
    )
    payload = dict(dict(neighbors["result"]).get("structuredContent") or {})
    rows = list(payload.get("neighbors") or [])
    assert [str(dict(row).get("atom_id") or "") for row in rows] == ["atom_2", "atom_3"]
    links = list(payload.get("links") or [])
    assert {"source": "atom_1", "target": "atom_2", "kind": "conflict"} in links
    assert {"source": "atom_1", "target": "atom_3", "kind": "narrative_arc"} in links
    assert {"source": "atom_2", "target": "atom_3", "kind": "narrative_arc"} in links


def test_mcp_memory_graph_neighbors_fallback_honors_root_detail_and_truthfully_marks_shared_language_loss() -> None:
    client = _FakeApiClient()
    client.native_graph_neighbors_available = False
    server = MCPServer(
        config=ServerConfig(
            runtime_base_url="http://127.0.0.1:7340",
            auth=AuthConfig(default_role="viewer"),
            max_graph_nodes=5,
            max_graph_links=5,
            max_neighbor_expansion_requests=4,
        ),
        api_client=client,
    )

    _call(server, 1, "initialize", {})
    neighbors = _call(
        server,
        2,
        "tools/call",
        {
            "name": "memory.graph_neighbors",
            "arguments": {
                "node_id": "atom_1",
                "depth": 2,
                "limit": 5,
                "include_root_detail": False,
                "include_shared_language": True,
            },
        },
    )
    payload = dict(dict(neighbors["result"]).get("structuredContent") or {})
    node = dict(payload.get("node") or {})
    assert node == {"atom_id": "atom_1"}
    truncation = dict(payload.get("truncation") or {})
    assert truncation.get("dropped_shared_language") is True


def test_mcp_memory_graph_neighbors_fallback_marks_internal_link_buffer_truncation() -> None:
    client = _FakeApiClient()
    client.native_graph_neighbors_available = False
    server = MCPServer(
        config=ServerConfig(
            runtime_base_url="http://127.0.0.1:7340",
            auth=AuthConfig(default_role="viewer"),
            max_graph_nodes=5,
            max_graph_links=1,
            max_neighbor_expansion_requests=4,
        ),
        api_client=client,
    )

    _call(server, 1, "initialize", {})
    neighbors = _call(
        server,
        2,
        "tools/call",
        {"name": "memory.graph_neighbors", "arguments": {"node_id": "atom_1", "depth": 2, "limit": 5}},
    )
    payload = dict(dict(neighbors["result"]).get("structuredContent") or {})
    rows = list(payload.get("neighbors") or [])
    assert [str(dict(row).get("atom_id") or "") for row in rows] == ["atom_2"]
    assert list(payload.get("links") or []) == [{"source": "atom_1", "target": "atom_2", "kind": "conflict"}]
    truncation = dict(payload.get("truncation") or {})
    assert truncation.get("link_limit_hit") is True


def test_fake_api_client_graph_neighbors_missing_atom_requires_allow_error_status() -> None:
    client = _FakeApiClient()

    status_code, payload = client.request_json(
        "GET",
        "/api/memory/graph/neighbors",
        query={"atom_id": "missing"},
        allow_error_status=True,
    )
    assert status_code == 404
    assert payload == {"error": "atom not found"}

    try:
        client.request_json(
            "GET",
            "/api/memory/graph/neighbors",
            query={"atom_id": "missing"},
            allow_error_status=False,
        )
    except RuntimeApiError as exc:
        assert exc.status_code == 404
        assert exc.detail == "atom not found"
    else:
        raise AssertionError("expected RuntimeApiError for missing atom without allow_error_status")


def test_mcp_memory_list_atoms_definition_view() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    compact = _call(
        server,
        2,
        "tools/call",
        {"name": "memory.list_atoms", "arguments": {"q": "dyad", "view": "definition"}},
    )
    compact_payload = dict(dict(compact["result"]).get("structuredContent") or {})
    assert compact_payload.get("view") == "definition"
    assert compact_payload.get("mode") == "compact"
    assert int(compact_payload.get("limit") or 0) == 8
    definition = dict(compact_payload.get("definition") or {})
    assert definition.get("term") == "dyad"
    assert str(definition.get("summary") or "").strip()
    rows = list(compact_payload.get("atoms") or [])
    assert rows
    assert "snippet" in dict(rows[0])
    assert "excerpt" not in dict(rows[0])

    full = _call(
        server,
        3,
        "tools/call",
        {"name": "memory.list_atoms", "arguments": {"q": "dyad", "view": "definition", "mode": "full", "limit": 2}},
    )
    full_payload = dict(dict(full["result"]).get("structuredContent") or {})
    assert full_payload.get("mode") == "full"
    full_rows = list(full_payload.get("atoms") or [])
    assert full_rows
    assert "excerpt" in dict(full_rows[0])
    assert "citations" in dict(full_rows[0])


def test_mcp_chat_tools_phase2_surface() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})

    start = _call(server, 2, "tools/call", {"name": "chat.start_session", "arguments": {"label": "phase2"}})
    start_payload = dict(dict(start["result"]).get("structuredContent") or {})
    assert start_payload.get("session_id") == "sess_new"

    rename = _call(
        server,
        3,
        "tools/call",
        {"name": "chat.rename_session", "arguments": {"session_id": "sess_1", "label": "phase2-updated"}},
    )
    rename_payload = dict(dict(rename["result"]).get("structuredContent") or {})
    assert rename_payload.get("session_id") == "sess_1"
    assert rename_payload.get("label") == "phase2-updated"

    sessions = _call(server, 4, "tools/call", {"name": "chat.list_sessions", "arguments": {"limit": 1, "offset": 0}})
    session_payload = dict(dict(sessions["result"]).get("structuredContent") or {})
    assert len(list(session_payload.get("sessions") or [])) == 1

    history = _call(
        server,
        5,
        "tools/call",
        {"name": "chat.session_history", "arguments": {"session_id": "sess_1", "limit": 5}},
    )
    history_payload = dict(dict(history["result"]).get("structuredContent") or {})
    assert history_payload.get("session_id") == "sess_1"
    assert len(list(history_payload.get("history") or [])) == 1

    route = _call(
        server,
        6,
        "tools/call",
        {"name": "chat.route_preview", "arguments": {"message": "hello"}},
    )
    route_payload = dict(dict(route["result"]).get("structuredContent") or {})
    assert route_payload.get("route") == "none"
    assert route_payload.get("estimated_route_cost_class") == "low"
    assert route_payload.get("expected_memory_touch") == "none"
    token_band = dict(route_payload.get("estimated_token_band") or {})
    assert token_band.get("request") in {"low", "medium", "high"}

    turn = _call(
        server,
        7,
        "tools/call",
        {
            "name": "chat.turn",
            "arguments": {"session_id": "sess_1", "message": "what do you remember?", "peek": True, "include_why": True},
        },
    )
    turn_payload = dict(dict(turn["result"]).get("structuredContent") or {})
    assert turn_payload.get("decision") == "PASS"
    assert turn_payload.get("turn_id") == "turn_1"
    peek = dict(turn_payload.get("peek") or {})
    snippets = list(peek.get("snippets") or [])
    assert int(peek.get("count") or 0) == 1
    assert snippets
    assert float(dict(snippets[0]).get("confidence") or 0.0) > 0.0
    assert str(dict(snippets[0]).get("source_id") or "") == "conv_1"
    assert "why" in turn_payload

    package = _call(
        server,
        8,
        "tools/call",
        {"name": "chat.build_context_package", "arguments": {"message": "build package", "package_version": "v2"}},
    )
    package_payload = dict(dict(package["result"]).get("structuredContent") or {})
    stats = dict(package_payload.get("stats") or {})
    assert stats.get("retrieved_count") == 2
    assert stats.get("route") == "ltm_light"


def test_mcp_exploration_tools_surface() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    tools = _call(server, 2, "tools/list")
    names = {str(item.get("name") or "") for item in list(dict(tools["result"]).get("tools") or []) if isinstance(item, dict)}
    assert "explore.start_here" in names
    assert "explore.orient" in names
    assert "explore.expand_anchor" in names
    assert "explore.peek" in names
    assert "explore.anchor_brief" in names
    assert "explore.set_preference" in names

    start_here = _call(server, 3, "tools/call", {"name": "explore.start_here", "arguments": {"limit": 5}})
    start_payload = dict(dict(start_here["result"]).get("structuredContent") or {})
    assert start_payload.get("status") == "ready"
    people = list(dict(start_payload.get("buckets") or {}).get("people") or [])
    assert people

    expanded = _call(
        server,
        4,
        "tools/call",
        {"name": "explore.expand_anchor", "arguments": {"anchor_id": "xander", "anchor_type": "person", "limit": 5}},
    )
    expanded_payload = dict(dict(expanded["result"]).get("structuredContent") or {})
    assert expanded_payload.get("status") == "ready"
    assert list(expanded_payload.get("connected_atoms") or [])
    next_hops = list(expanded_payload.get("next_hops") or [])
    assert expanded_payload.get("mode") == "compact"
    assert len(next_hops) == 2

    expanded_full = _call(
        server,
        4_1,
        "tools/call",
        {"name": "explore.expand_anchor", "arguments": {"anchor_id": "xander", "anchor_type": "person", "limit": 5, "mode": "full"}},
    )
    expanded_full_payload = dict(dict(expanded_full["result"]).get("structuredContent") or {})
    connected_full = list(expanded_full_payload.get("connected_atoms") or [])
    assert expanded_full_payload.get("mode") == "full"
    assert "card_id" in dict(connected_full[0])

    peek = _call(
        server,
        5,
        "tools/call",
        {"name": "explore.peek", "arguments": {"anchor_id": "xander", "anchor_type": "person", "limit": 3}},
    )
    peek_payload = dict(dict(peek["result"]).get("structuredContent") or {})
    assert peek_payload.get("mode") == "compact"
    assert int(peek_payload.get("count") or 0) >= 1
    snippet_compact = dict(list(peek_payload.get("snippets") or [])[0])
    assert "raw_excerpt" not in snippet_compact

    peek_full = _call(
        server,
        5_1,
        "tools/call",
        {"name": "explore.peek", "arguments": {"anchor_id": "xander", "anchor_type": "person", "limit": 3, "mode": "full"}},
    )
    peek_full_payload = dict(dict(peek_full["result"]).get("structuredContent") or {})
    snippet_full = dict(list(peek_full_payload.get("snippets") or [])[0])
    assert "raw_excerpt" in snippet_full

    orient = _call(server, 5_2, "tools/call", {"name": "explore.orient", "arguments": {"limit": 3}})
    orient_payload = dict(dict(orient["result"]).get("structuredContent") or {})
    assert orient_payload.get("status") == "ready"
    assert list(orient_payload.get("what_matters_now") or [])

    brief = _call(
        server,
        5_3,
        "tools/call",
        {"name": "explore.anchor_brief", "arguments": {"anchor_id": "xander", "anchor_type": "person", "limit": 2}},
    )
    brief_payload = dict(dict(brief["result"]).get("structuredContent") or {})
    assert str(brief_payload.get("summary") or "").strip()
    assert list(brief_payload.get("top_snippets") or [])

    set_pref = _call(
        server,
        6,
        "tools/call",
        {"name": "explore.set_preference", "arguments": {"anchor_id": "xander", "anchor_type": "person", "action": "pin"}},
    )
    set_pref_payload = dict(dict(set_pref["result"]).get("structuredContent") or {})
    assert set_pref_payload.get("applied") is True

    get_pref = _call(server, 7, "tools/call", {"name": "explore.get_preferences", "arguments": {}})
    get_pref_payload = dict(dict(get_pref["result"]).get("structuredContent") or {})
    assert int(get_pref_payload.get("count") or 0) >= 1

    cleared = _call(
        server,
        8,
        "tools/call",
        {"name": "explore.set_preference", "arguments": {"anchor_id": "xander", "anchor_type": "person", "action": "clear"}},
    )
    cleared_payload = dict(dict(cleared["result"]).get("structuredContent") or {})
    assert cleared_payload.get("removed") is True


def test_mcp_quicknote_and_whats_new_tools_surface() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    tools = _call(server, 2, "tools/list")
    names = {str(item.get("name") or "") for item in list(dict(tools["result"]).get("tools") or []) if isinstance(item, dict)}
    assert "memory.quicknote.status" in names
    assert "memory.quicknote.propose" in names
    assert "memory.quicknote.propose_batch" in names
    assert "memory.quicknote.flush" in names
    assert "explore.whats_new" in names
    assert "system.usage_guide" in names

    status = _call(
        server,
        3,
        "tools/call",
        {"name": "memory.quicknote.status", "arguments": {"assistant_id": "claude", "session_id": "sess_a"}},
    )
    status_payload = dict(dict(status["result"]).get("structuredContent") or {})
    assert dict(status_payload.get("status") or {}).get("assistant_id") == "claude"

    proposed = _call(
        server,
        4,
        "tools/call",
        {
            "name": "memory.quicknote.propose",
            "arguments": {
                "assistant_id": "claude",
                "session_id": "sess_a",
                "text": "Remember the project launch blocker and fallback path.",
                "importance": "high",
                "tags": ["project", "blocker"],
            },
        },
    )
    proposed_payload = dict(dict(proposed["result"]).get("structuredContent") or {})
    assert proposed_payload.get("accepted") is True
    assert str(dict(proposed_payload.get("note") or {}).get("note_id") or "").startswith("qn_")

    batch = _call(
        server,
        5,
        "tools/call",
        {
            "name": "memory.quicknote.propose_batch",
            "arguments": {
                "assistant_id": "claude",
                "session_id": "sess_a",
                "notes": [
                    {"text": "Remember citation window default is ±3."},
                    {"text": "Remember optional citation window ±5 for deep review."},
                ],
            },
        },
    )
    batch_payload = dict(dict(batch["result"]).get("structuredContent") or {})
    assert int(batch_payload.get("accepted_count") or 0) == 2

    whats_new = _call(
        server,
        6,
        "tools/call",
        {"name": "explore.whats_new", "arguments": {"assistant_id": "claude", "limit": 5}},
    )
    whats_new_payload = dict(dict(whats_new["result"]).get("structuredContent") or {})
    assert int(dict(whats_new_payload.get("changes") or {}).get("added_count") or 0) >= 1

    flushed = _call(
        server,
        7,
        "tools/call",
        {
            "name": "memory.quicknote.flush",
            "arguments": {"assistant_id": "claude", "session_id": "sess_a", "reason": "manual"},
        },
    )
    flushed_payload = dict(dict(flushed["result"]).get("structuredContent") or {})
    assert int(flushed_payload.get("flushed_count") or 0) >= 1

    usage = _call(server, 8, "tools/call", {"name": "system.usage_guide", "arguments": {}})
    usage_payload = dict(dict(usage["result"]).get("structuredContent") or {})
    assert str(dict(usage_payload.get("guide") or {}).get("version") or "").startswith("quicknote.")


def test_mcp_methodology_tools_surface_and_lifecycle() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    tools = _call(server, 2, "tools/list")
    names = {str(item.get("name") or "") for item in list(dict(tools["result"]).get("tools") or []) if isinstance(item, dict)}
    assert "methodology.list" in names
    assert "methodology.get" in names
    assert "methodology.readout" in names
    assert "methodology.create_draft" in names
    assert "methodology.review" in names
    assert "methodology.start_canary" in names
    assert "methodology.evaluate_canary" in names
    assert "methodology.activate" in names
    assert "methodology.rollback" in names
    assert "methodology.record_correction" in names
    assert "methodology.evaluate_maintenance" in names

    created = _call(
        server,
        3,
        "tools/call",
        {
            "name": "methodology.create_draft",
            "arguments": {
                "trigger_condition": "When user asks for legal-memory recall.",
                "action": "Prefer citation-anchored response with verify-first.",
                "rationale": "Preserve zero false-memory behavior under legal recall prompts.",
            },
        },
    )
    created_payload = dict(dict(created["result"]).get("structuredContent") or {})
    record = dict(created_payload.get("record") or {})
    methodology_id = str(record.get("methodology_id") or "")
    assert methodology_id.startswith("meth_")
    assert record.get("status") == "draft"

    reviewed = _call(
        server,
        4,
        "tools/call",
        {
            "name": "methodology.review",
            "arguments": {"methodology_id": methodology_id, "decision": "approve", "reviewer": "dex"},
        },
    )
    reviewed_payload = dict(dict(reviewed["result"]).get("structuredContent") or {})
    assert str(dict(reviewed_payload.get("record") or {}).get("approval_state") or "") == "approved"

    canary_started = _call(
        server,
        5,
        "tools/call",
        {"name": "methodology.start_canary", "arguments": {"methodology_id": methodology_id}},
    )
    canary_started_payload = dict(dict(canary_started["result"]).get("structuredContent") or {})
    assert str(dict(canary_started_payload.get("record") or {}).get("status") or "") == "canary"

    canary_eval = _call(
        server,
        6,
        "tools/call",
        {"name": "methodology.evaluate_canary", "arguments": {"methodology_id": methodology_id}},
    )
    canary_eval_payload = dict(dict(canary_eval["result"]).get("structuredContent") or {})
    comparison = dict(canary_eval_payload.get("comparison") or {})
    assert comparison.get("should_rollback") is False

    activated = _call(
        server,
        7,
        "tools/call",
        {"name": "methodology.activate", "arguments": {"methodology_id": methodology_id}},
    )
    activated_payload = dict(dict(activated["result"]).get("structuredContent") or {})
    assert str(activated_payload.get("active_methodology_id") or "") == methodology_id

    for idx in range(3):
        _call(
            server,
            8 + idx,
            "tools/call",
            {
                "name": "methodology.record_correction",
                "arguments": {
                    "text": "Stop using speculative framing when citation evidence is thin.",
                    "assistant_id": "claude",
                    "session_id": "sess_corr",
                },
            },
        )

    clusters = _call(server, 20, "tools/call", {"name": "methodology.list_correction_clusters", "arguments": {"limit": 5}})
    clusters_payload = dict(dict(clusters["result"]).get("structuredContent") or {})
    cluster_rows = list(clusters_payload.get("clusters") or [])
    assert cluster_rows
    assert int(dict(cluster_rows[0]).get("count") or 0) >= 3

    maintenance = _call(
        server,
        21,
        "tools/call",
        {"name": "methodology.evaluate_maintenance", "arguments": {"force": True}},
    )
    maintenance_payload = dict(dict(maintenance["result"]).get("structuredContent") or {})
    assert bool(dict(maintenance_payload.get("evaluation") or {}).get("triggered")) is True

    readout = _call(server, 22, "tools/call", {"name": "methodology.readout", "arguments": {}})
    readout_payload = dict(dict(readout["result"]).get("structuredContent") or {})
    assert str(dict(readout_payload.get("readout") or {}).get("active_methodology_id") or "") == methodology_id

    got = _call(server, 23, "tools/call", {"name": "methodology.get", "arguments": {"methodology_id": methodology_id}})
    got_payload = dict(dict(got["result"]).get("structuredContent") or {})
    assert str(dict(got_payload.get("record") or {}).get("methodology_id") or "") == methodology_id

    listed = _call(server, 24, "tools/call", {"name": "methodology.list", "arguments": {"status": "all"}})
    listed_payload = dict(dict(listed["result"]).get("structuredContent") or {})
    assert int(listed_payload.get("total") or 0) >= 1

    rollback = _call(
        server,
        25,
        "tools/call",
        {"name": "methodology.rollback", "arguments": {"methodology_id": methodology_id, "reason": "manual verification"}},
    )
    rollback_payload = dict(dict(rollback["result"]).get("structuredContent") or {})
    assert str(rollback_payload.get("rolled_back_methodology_id") or "") == methodology_id


def test_mcp_organizer_tools_surface() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    tools = _call(server, 2, "tools/list")
    names = {str(item.get("name") or "") for item in list(dict(tools["result"]).get("tools") or []) if isinstance(item, dict)}
    assert "wizard.organizer_inventory" in names
    assert "wizard.organizer_apply" in names
    assert "wizard.organizer_run" in names

    inventory = _call(server, 3, "tools/call", {"name": "wizard.organizer_inventory", "arguments": {"run_id": "wizard_test_1"}})
    inventory_payload = dict(dict(inventory["result"]).get("structuredContent") or {})
    assert inventory_payload.get("status") == "ready"

    dedupe = _call(server, 4, "tools/call", {"name": "wizard.organizer_dedupe", "arguments": {"run_id": "wizard_test_1"}})
    dedupe_payload = dict(dict(dedupe["result"]).get("structuredContent") or {})
    assert int(dict(dedupe_payload.get("counts") or {}).get("proposal_count") or 0) >= 1

    conflicts = _call(server, 5, "tools/call", {"name": "wizard.organizer_conflicts", "arguments": {"run_id": "wizard_test_1"}})
    conflicts_payload = dict(dict(conflicts["result"]).get("structuredContent") or {})
    assert int(dict(conflicts_payload.get("counts") or {}).get("conflicts") or 0) >= 0

    package = _call(server, 6, "tools/call", {"name": "wizard.organizer_package", "arguments": {"run_id": "wizard_test_1"}})
    package_payload = dict(dict(package["result"]).get("structuredContent") or {})
    assert str(package_payload.get("package_id") or "").startswith("org_pkg")

    apply_dry = _call(
        server,
        7,
        "tools/call",
        {"name": "wizard.organizer_apply", "arguments": {"run_id": "wizard_test_1", "dry_run": True}},
    )
    apply_dry_payload = dict(dict(apply_dry["result"]).get("structuredContent") or {})
    assert apply_dry_payload.get("applied") is False

    apply_live = _call(
        server,
        8,
        "tools/call",
        {"name": "wizard.organizer_apply", "arguments": {"run_id": "wizard_test_1"}},
    )
    apply_live_payload = dict(dict(apply_live["result"]).get("structuredContent") or {})
    assert apply_live_payload.get("applied") is True

    verify = _call(server, 9, "tools/call", {"name": "wizard.organizer_verify", "arguments": {"run_id": "wizard_test_1"}})
    verify_payload = dict(dict(verify["result"]).get("structuredContent") or {})
    assert verify_payload.get("status") in {"safe", "needs_attention"}

    restore = _call(server, 10, "tools/call", {"name": "wizard.organizer_restore_last", "arguments": {"run_id": "wizard_test_1"}})
    restore_payload = dict(dict(restore["result"]).get("structuredContent") or {})
    assert restore_payload.get("restored") is True

    run_summary = _call(
        server,
        11,
        "tools/call",
        {"name": "wizard.organizer_run", "arguments": {"run_id": "wizard_test_1", "apply_changes": True}},
    )
    run_payload = dict(dict(run_summary["result"]).get("structuredContent") or {})
    assert run_payload.get("ok") is True
    assert run_payload.get("applied") is True
    assert str(run_payload.get("status") or "").strip()

def test_mcp_chat_retrieval_query_requires_operator_role() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    denied = _call(
        server,
        2,
        "tools/call",
        {"name": "chat.turn", "arguments": {"message": "query override", "retrieval_query": "force"}},
    )
    assert "error" in denied
    assert int(dict(denied["error"]).get("code") or 0) == -32002


def test_mcp_chat_retrieval_query_operator_role_forwards_structured_override() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="operator"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    _call(
        server,
        2,
        "tools/call",
        {"name": "chat.turn", "arguments": {"message": "query override", "retrieval_query": "force anchor"}},
    )
    path, payload = client.post_calls[-1]
    assert path == "/api/chat"
    assert "retrieval_query" not in payload
    override_payload = dict(payload.get("retrieval_override") or {})
    assert override_payload.get("query") == "force anchor"
    assert override_payload.get("invoker") == "engine.mcp.server.chat.turn"
    assert override_payload.get("scope") == "mcp_chat_turn"


def test_mcp_context_package_operator_role_forwards_structured_override() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="operator"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    _call(
        server,
        2,
        "tools/call",
        {
            "name": "chat.build_context_package",
            "arguments": {"message": "hello", "package_version": "v2", "retrieval_query": "force anchor"},
        },
    )
    path, payload = client.post_calls[-1]
    assert path == "/api/chat/context-package"
    assert "retrieval_query" not in payload
    override_payload = dict(payload.get("retrieval_override") or {})
    assert override_payload.get("query") == "force anchor"
    assert override_payload.get("invoker") == "engine.mcp.server.chat.build_context_package"
    assert override_payload.get("scope") == "mcp_context_package"
    assert "auth_context" not in override_payload


def test_mcp_chat_turn_accepts_answer_alias_fields() -> None:
    class _AliasTurnClient(_FakeApiClient):
        def post_json(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/chat":
                return {
                    "ok": True,
                    "turn": {
                        "turn_id": "turn_alias",
                        "session_id": "",
                        "timestamp": "2026-02-16T00:00:00+00:00",
                        "decision": "NO_MEMORY",
                        "answer": "Alias answer field",
                        "citations": [],
                    },
                }
            return super().post_json(path, payload)

    client = _AliasTurnClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    turn = _call(server, 2, "tools/call", {"name": "chat.turn", "arguments": {"message": "hello"}})
    payload = dict(dict(turn["result"]).get("structuredContent") or {})
    assert payload.get("answer") == "Alias answer field"


def test_mcp_context_package_retrieved_ids_string_is_counted_once() -> None:
    class _StringRetrievedIdsClient(_FakeApiClient):
        def post_json(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/chat/context-package":
                return {
                    "ok": True,
                    "package": {
                        "package_version": "v2",
                        "retrieval_stats": {
                            "memory_route": "ltm_light",
                            "retrieval_stop_reason": "single_pass",
                            "retrieved_atom_ids": "atom_1",
                        },
                    },
                }
            return super().post_json(path, payload)

    client = _StringRetrievedIdsClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    package = _call(
        server,
        2,
        "tools/call",
        {"name": "chat.build_context_package", "arguments": {"message": "hello", "package_version": "v2"}},
    )
    payload = dict(dict(package["result"]).get("structuredContent") or {})
    stats = dict(payload.get("stats") or {})
    assert stats.get("retrieved_count") == 1


def test_mcp_why_and_citation_tools_phase3_surface() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
        max_citation_matches=1,
        max_why_evidence_items=1,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    why = _call(
        server,
        2,
        "tools/call",
        {"name": "why.explain_turn", "arguments": {"turn_id": "turn_1", "include_citations": True}},
    )
    why_payload = dict(dict(why["result"]).get("structuredContent") or {})
    assert why_payload.get("decision") == "PASS"
    assert why_payload.get("reason") == "evidence present"
    assert why_payload.get("decision_reason") == "direct citation alignment"
    assert len(list(why_payload.get("evidence") or [])) == 1
    assert len(list(why_payload.get("citations") or [])) == 1

    citation = _call(
        server,
        3,
        "tools/call",
        {
            "name": "evidence.resolve_citation",
            "arguments": {"citation_token": "conv_1#m_1", "max_matches": 5, "context_window": 5},
        },
    )
    citation_payload = dict(dict(citation["result"]).get("structuredContent") or {})
    matches = list(citation_payload.get("matches") or [])
    assert citation_payload.get("citation_token") == "conv_1#m_1"
    assert int(citation_payload.get("context_window") or 0) == 5
    assert len(matches) == 1
    assert bool(dict(matches[0]).get("is_target")) is True
    assert int(dict(matches[0]).get("distance") or 0) == 0
    assert bool(citation_payload.get("truncated")) is True


def test_mcp_citation_token_length_is_bounded() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    too_long_token = f"{'a' * 130}#m_1"
    denied = _call(
        server,
        2,
        "tools/call",
        {"name": "evidence.resolve_citation", "arguments": {"citation_token": too_long_token}},
    )
    assert "error" in denied
    assert int(dict(denied["error"]).get("code") or 0) == -32602


def test_mcp_phase4_mutations_blocked_when_policy_disabled() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=False,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    denied = _call(
        server,
        2,
        "tools/call",
        {"name": "memory.disable_episode", "arguments": {"episode_id": "ep_1"}},
    )
    assert "error" in denied
    assert int(dict(denied["error"]).get("code") or 0) == -32002

    denied_list = _call(
        server,
        3,
        "tools/call",
        {"name": "proposals.list", "arguments": {"status": "open"}},
    )
    assert "error" in denied_list
    assert int(dict(denied_list["error"]).get("code") or 0) == -32002

    denied_preference = _call(
        server,
        4,
        "tools/call",
        {"name": "explore.set_preference", "arguments": {"anchor_id": "xander", "anchor_type": "person", "action": "pin"}},
    )
    assert "error" in denied_preference
    assert int(dict(denied_preference["error"]).get("code") or 0) == -32002


def test_mcp_phase4_mutation_and_proposal_tools() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    tools = _call(server, 2, "tools/list")
    names = {str(item.get("name") or "") for item in list(dict(tools["result"]).get("tools") or []) if isinstance(item, dict)}
    assert "memory.disable_episode" in names
    assert "proposals.create_edit" in names

    disabled = _call(
        server,
        3,
        "tools/call",
        {"name": "memory.disable_episode", "arguments": {"episode_id": "ep_1", "reason": "test"}},
    )
    disabled_payload = dict(dict(disabled["result"]).get("structuredContent") or {})
    assert disabled_payload.get("status") == "disabled"

    enabled = _call(server, 4, "tools/call", {"name": "memory.enable_episode", "arguments": {"episode_id": "ep_1"}})
    enabled_payload = dict(dict(enabled["result"]).get("structuredContent") or {})
    assert enabled_payload.get("status") == "approved"

    dry_edit = _call(
        server,
        5,
        "tools/call",
        {
            "name": "memory.edit_episode",
            "arguments": {"episode_id": "ep_1", "patch": {"title": "Updated"}, "dry_run": True},
        },
    )
    dry_edit_payload = dict(dict(dry_edit["result"]).get("structuredContent") or {})
    assert dry_edit_payload.get("applied") is False

    empty_edit = _call(
        server,
        6,
        "tools/call",
        {"name": "memory.edit_episode", "arguments": {"episode_id": "ep_1", "patch": {"title": "  "}}},
    )
    assert "error" in empty_edit
    assert int(dict(empty_edit["error"]).get("code") or 0) == -32602

    edit = _call(
        server,
        7,
        "tools/call",
        {
            "name": "memory.edit_episode",
            "arguments": {"episode_id": "ep_1", "patch": {"title": "Updated", "tags": ["tea"], "actors": ["user"]}},
        },
    )
    edit_payload = dict(dict(edit["result"]).get("structuredContent") or {})
    assert edit_payload.get("applied") is True

    undo = _call(server, 8, "tools/call", {"name": "memory.undo_last_change", "arguments": {"scope": "episode_edits"}})
    undo_payload = dict(dict(undo["result"]).get("structuredContent") or {})
    assert dict(undo_payload.get("undone") or {}).get("kind") == "episode_edit"

    listed = _call(server, 9, "tools/call", {"name": "proposals.list", "arguments": {"status": "open"}})
    listed_payload = dict(dict(listed["result"]).get("structuredContent") or {})
    assert int(listed_payload.get("total") or 0) >= 1

    create_edit = _call(
        server,
        10,
        "tools/call",
        {
            "name": "proposals.create_edit",
            "arguments": {
                "target_id": "atom_1",
                "patch": {"canonical_text": "Edited canonical text"},
                "reason": "manual_edit",
            },
        },
    )
    create_edit_payload = dict(dict(create_edit["result"]).get("structuredContent") or {})
    assert str(create_edit_payload.get("proposal_id") or "").startswith("prop_edit_")

    create_delete = _call(
        server,
        11,
        "tools/call",
        {"name": "proposals.create_delete", "arguments": {"target_id": "atom_2", "reason": "cleanup"}},
    )
    create_delete_payload = dict(dict(create_delete["result"]).get("structuredContent") or {})
    assert str(create_delete_payload.get("proposal_id") or "").startswith("prop_delete_")

    approve = _call(
        server,
        12,
        "tools/call",
        {"name": "proposals.approve", "arguments": {"proposal_id": "prop_edit_1", "apply": True}},
    )
    approve_payload = dict(dict(approve["result"]).get("structuredContent") or {})
    assert approve_payload.get("status") == "applied"

    reject = _call(
        server,
        13,
        "tools/call",
        {"name": "proposals.reject", "arguments": {"proposal_id": "prop_delete_1", "note": "invalid"}},
    )
    reject_payload = dict(dict(reject["result"]).get("structuredContent") or {})
    assert reject_payload.get("status") == "rejected"


@pytest.mark.parametrize(
    ("role", "expect_allowed"),
    [
        ("viewer", False),
        ("operator", True),
        ("admin", True),
    ],
)
def test_mcp_phase4_permissions_matrix_and_audit(role: str, expect_allowed: bool) -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role=role),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    baseline_events = len(list(server._audit))

    request_id = 2
    for tool_name, arguments in _PHASE4_PERMISSION_TOOL_CALLS:
        response = _call(
            server,
            request_id,
            "tools/call",
            {"name": tool_name, "arguments": dict(arguments)},
        )
        request_id += 1
        if expect_allowed:
            assert "error" not in response
        else:
            assert "error" in response
            assert int(dict(response["error"]).get("code") or 0) == -32002

    new_events = list(server._audit)[baseline_events:]
    assert len(new_events) == len(_PHASE4_PERMISSION_TOOL_CALLS)
    assert all(str(row.get("method") or "") == "tools/call" for row in new_events)
    expected_status = "ok" if expect_allowed else "error"
    assert all(str(row.get("status") or "") == expected_status for row in new_events)


def test_mcp_phase4_mutations_are_persisted_in_audit_log(tmp_path: Path) -> None:
    client = _FakeApiClient()
    audit_log_path = tmp_path / "mcp_phase4_audit.jsonl"
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=True,
        audit_log_path=str(audit_log_path),
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    request_id = 2
    for tool_name, arguments in _PHASE4_MUTATION_TOOL_CALLS:
        response = _call(
            server,
            request_id,
            "tools/call",
            {"name": tool_name, "arguments": dict(arguments)},
        )
        request_id += 1
        assert "error" not in response

    assert audit_log_path.exists()
    rows = [json.loads(line) for line in audit_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1 + len(_PHASE4_MUTATION_TOOL_CALLS)
    mutation_rows = [row for row in rows if str(row.get("method") or "") == "tools/call"]
    assert len(mutation_rows) == len(_PHASE4_MUTATION_TOOL_CALLS)
    assert all(str(row.get("status") or "") == "ok" for row in mutation_rows)


def test_mcp_phase5_wizard_operator_surface_and_dry_run() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    tools = _call(server, 2, "tools/list")
    names = {str(item.get("name") or "") for item in list(dict(tools["result"]).get("tools") or []) if isinstance(item, dict)}
    assert "wizard.start_or_resume" in names
    assert "wizard.go_live" not in names

    started = _call(
        server,
        3,
        "tools/call",
        {"name": "wizard.start_or_resume", "arguments": {"mode": "new"}},
    )
    started_payload = dict(dict(started["result"]).get("structuredContent") or {})
    assert str(started_payload.get("run_id") or "").startswith("wizard_")

    validated = _call(
        server,
        4,
        "tools/call",
        {
            "name": "wizard.validate_archive",
            "arguments": {"run_id": "wizard_test_1", "archive_descriptor": {"archive_path": "runtime/archive/db.json"}},
        },
    )
    validated_payload = dict(dict(validated["result"]).get("structuredContent") or {})
    assert validated_payload.get("ok") is True

    import_dry = _call(
        server,
        5,
        "tools/call",
        {
            "name": "wizard.import_run",
            "arguments": {
                "run_id": "wizard_test_1",
                "archive_descriptor": {"archive_path": "runtime/archive/db.json"},
                "dry_run": True,
            },
        },
    )
    import_dry_payload = dict(dict(import_dry["result"]).get("structuredContent") or {})
    assert import_dry_payload.get("applied") is False

    imported = _call(
        server,
        6,
        "tools/call",
        {
            "name": "wizard.import_run",
            "arguments": {"run_id": "wizard_test_1", "archive_descriptor": {"archive_path": "runtime/archive/db.json"}},
        },
    )
    imported_payload = dict(dict(imported["result"]).get("structuredContent") or {})
    assert imported_payload.get("applied") is True

    build = _call(
        server,
        7,
        "tools/call",
        {"name": "wizard.build_episodes", "arguments": {"run_id": "wizard_test_1", "policy_preset": "balanced"}},
    )
    build_payload = dict(dict(build["result"]).get("structuredContent") or {})
    assert build_payload.get("applied") is True

    review_list = _call(
        server,
        8,
        "tools/call",
        {"name": "wizard.review_list", "arguments": {"run_id": "wizard_test_1"}},
    )
    review_list_payload = dict(dict(review_list["result"]).get("structuredContent") or {})
    assert int(dict(review_list_payload.get("counts") or {}).get("total") or 0) >= 1

    review_update_dry = _call(
        server,
        9,
        "tools/call",
        {
            "name": "wizard.review_update",
            "arguments": {"run_id": "wizard_test_1", "updates": [{"episode_id": "ep_1", "decision": "approved"}], "dry_run": True},
        },
    )
    review_update_dry_payload = dict(dict(review_update_dry["result"]).get("structuredContent") or {})
    assert review_update_dry_payload.get("applied") is False

    review_update = _call(
        server,
        10,
        "tools/call",
        {
            "name": "wizard.review_update",
            "arguments": {"run_id": "wizard_test_1", "updates": [{"episode_id": "ep_1", "decision": "approved"}]},
        },
    )
    review_update_payload = dict(dict(review_update["result"]).get("structuredContent") or {})
    assert review_update_payload.get("updated") == 1

    invalid_update = _call(
        server,
        11,
        "tools/call",
        {"name": "wizard.review_update", "arguments": {"run_id": "wizard_test_1", "updates": [{"decision": "approved"}]}},
    )
    assert "error" in invalid_update
    assert int(dict(invalid_update["error"]).get("code") or 0) == -32602

    compile_reviewed = _call(
        server,
        12,
        "tools/call",
        {"name": "wizard.compile_reviewed", "arguments": {"run_id": "wizard_test_1"}},
    )
    compile_payload = dict(dict(compile_reviewed["result"]).get("structuredContent") or {})
    assert compile_payload.get("applied") is True

    verify = _call(
        server,
        13,
        "tools/call",
        {"name": "wizard.verify", "arguments": {"run_id": "wizard_test_1"}},
    )
    verify_payload = dict(dict(verify["result"]).get("structuredContent") or {})
    assert verify_payload.get("status") == "safe"

    denied_go_live = _call(server, 14, "tools/call", {"name": "wizard.go_live", "arguments": {"run_id": "wizard_test_1"}})
    assert "error" in denied_go_live
    assert int(dict(denied_go_live["error"]).get("code") or 0) == -32002


def test_mcp_phase5_wizard_admin_tools() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="admin"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    go_live = _call(server, 2, "tools/call", {"name": "wizard.go_live", "arguments": {"run_id": "wizard_test_1"}})
    go_live_payload = dict(dict(go_live["result"]).get("structuredContent") or {})
    assert go_live_payload.get("applied") is True

    restore = _call(
        server,
        3,
        "tools/call",
        {"name": "wizard.restore_last_published", "arguments": {"run_id": "wizard_test_1"}},
    )
    restore_payload = dict(dict(restore["result"]).get("structuredContent") or {})
    assert restore_payload.get("restored") is True


def test_mcp_phase5_wizard_verify_unsafe_maps_to_needs_attention() -> None:
    class _UnsafeWizardClient(_FakeApiClient):
        def post_json(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/wizard/verify/run":
                return {"ok": True, "status": "unsafe", "checks": [], "actionable_links": []}
            return super().post_json(path, payload)

    client = _UnsafeWizardClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="operator"),
        mutations_enabled=True,
    )
    server = MCPServer(config=config, api_client=client)
    _call(server, 1, "initialize", {})
    verify = _call(server, 2, "tools/call", {"name": "wizard.verify", "arguments": {"run_id": "wizard_test_1"}})
    payload = dict(dict(verify["result"]).get("structuredContent") or {})
    assert payload.get("status") == "needs_attention"


def test_mcp_phase6_ops_tools_and_policy_patch(tmp_path: Path) -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="admin"),
        diagnostics_dir=str(tmp_path / "diag"),
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    provider = _call(server, 2, "tools/call", {"name": "ops.get_provider_config", "arguments": {}})
    provider_payload = dict(dict(provider["result"]).get("structuredContent") or {})
    assert provider_payload.get("model_name") == "test-model"

    dry_patch = _call(
        server,
        3,
        "tools/call",
        {"name": "ops.set_policy", "arguments": {"policy_patch": {"mutations_enabled": True}, "dry_run": True}},
    )
    dry_patch_payload = dict(dict(dry_patch["result"]).get("structuredContent") or {})
    assert dry_patch_payload.get("applied") is False
    assert config.mutations_enabled is False

    applied_patch = _call(
        server,
        4,
        "tools/call",
        {"name": "ops.set_policy", "arguments": {"policy_patch": {"mutations_enabled": True}}},
    )
    applied_patch_payload = dict(dict(applied_patch["result"]).get("structuredContent") or {})
    assert applied_patch_payload.get("applied") is True
    assert config.mutations_enabled is True

    exported = _call(
        server,
        5,
        "tools/call",
        {"name": "ops.export_diagnostics", "arguments": {"include_recent_turns": True}},
    )
    exported_payload = dict(dict(exported["result"]).get("structuredContent") or {})
    descriptor = dict(exported_payload.get("bundle_descriptor") or {})
    bundle_path = Path(str(descriptor.get("path") or ""))
    assert bundle_path.exists()
    assert int(descriptor.get("event_count") or 0) >= 1


def test_mcp_phase6_capabilities_remote_hardening_checklist_passes_when_configured(tmp_path: Path) -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        transport="http",
        auth=AuthConfig(default_role="viewer", viewer_token="viewer-token"),
        enforce_https=True,
        trust_proxy_headers=True,
        http_security_log_path=str(tmp_path / "mcp_http_security.jsonl"),
        http_nonce_replay_window_seconds=300,
    )
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {"auth_token": "viewer-token"})
    capabilities = _call(server, 2, "tools/call", {"name": "capabilities.get", "arguments": {}})
    payload = dict(dict(capabilities["result"]).get("structuredContent") or {})
    remote = dict(payload.get("remote_hardening") or {})
    assert remote.get("checklist_pass") is True
    assert dict(remote.get("tls") or {}).get("pass") is True
    assert dict(remote.get("limits") or {}).get("pass") is True
    assert dict(remote.get("structured_logs") or {}).get("pass") is True
    assert dict(remote.get("pen_test") or {}).get("pass") is True


def test_mcp_phase6_http_transport_auth_limits_and_rate_limit() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        transport="http",
        auth=AuthConfig(default_role="viewer", viewer_token="viewer-token"),
        http_max_request_bytes=220,
        http_rate_limit_per_minute=1,
    )
    server = MCPServer(config=config, api_client=client)
    http_server, thread = start_http_server(server, host="127.0.0.1", port=0)
    host, port = http_server.server_address
    url = f"http://{host}:{port}/mcp"

    try:
        status_unauth, _payload_unauth = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            token=None,
        )
        assert status_unauth == 401

        status_init, payload_init = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
            token="viewer-token",
        )
        assert status_init == 200
        assert "result" in payload_init

        status_rate, payload_rate = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}},
            token="viewer-token",
        )
        assert status_rate == 429
        assert "rate limit" in str(payload_rate.get("error") or "").lower()

        large_payload = {"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {"blob": "x" * 1000}}
        status_large, _payload_large = _http_post_json(url, large_payload, token="viewer-token")
        assert status_large == 413
    finally:
        stop_http_server(http_server, thread)


def test_mcp_phase6_http_transport_rejects_invalid_content_length_header() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        transport="http",
        auth=AuthConfig(default_role="viewer", viewer_token="viewer-token"),
    )
    server = MCPServer(config=config, api_client=client)
    http_server, thread = start_http_server(server, host="127.0.0.1", port=0)
    host, port = http_server.server_address
    url = f"http://{host}:{port}/mcp"

    try:
        status, payload = _http_post_with_headers(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "Authorization": "Bearer viewer-token",
                "Content-Type": "application/json",
                "Content-Length": "abc",
            },
        )
        assert status == 400
        assert "content-length" in str(payload.get("error") or "").lower()
    finally:
        stop_http_server(http_server, thread)


def test_mcp_phase6_http_transport_rejects_replayed_nonce() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        transport="http",
        auth=AuthConfig(default_role="viewer", viewer_token="viewer-token"),
        http_rate_limit_per_minute=20,
        http_nonce_replay_window_seconds=300,
    )
    server = MCPServer(config=config, api_client=client)
    http_server, thread = start_http_server(server, host="127.0.0.1", port=0)
    host, port = http_server.server_address
    url = f"http://{host}:{port}/mcp"

    try:
        init_payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        init_body = json.dumps(init_payload).encode("utf-8")
        status_init, payload_init = _http_post_with_headers(
            url,
            init_payload,
            headers={
                "Authorization": "Bearer viewer-token",
                "Content-Type": "application/json",
                "Content-Length": str(len(init_body)),
                "X-MCP-Nonce": "nonce-123",
            },
        )
        assert status_init == 200
        assert "result" in payload_init

        ping_payload = {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
        ping_body = json.dumps(ping_payload).encode("utf-8")
        status_replay, replay_payload = _http_post_with_headers(
            url,
            ping_payload,
            headers={
                "Authorization": "Bearer viewer-token",
                "Content-Type": "application/json",
                "Content-Length": str(len(ping_body)),
                "X-MCP-Nonce": "nonce-123",
            },
        )
        assert status_replay == 409
        assert "replay" in str(replay_payload.get("error") or "").lower()
    finally:
        stop_http_server(http_server, thread)


def test_mcp_phase6_http_transport_requires_initialize_per_client_key() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        transport="http",
        auth=AuthConfig(default_role="viewer", viewer_token="viewer-token", operator_token="operator-token"),
        http_rate_limit_per_minute=20,
    )
    server = MCPServer(config=config, api_client=client)
    http_server, thread = start_http_server(server, host="127.0.0.1", port=0)
    host, port = http_server.server_address
    url = f"http://{host}:{port}/mcp"

    try:
        status_init_viewer, payload_init_viewer = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            token="viewer-token",
        )
        assert status_init_viewer == 200
        assert "result" in payload_init_viewer

        status_viewer_tools, payload_viewer_tools = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            token="viewer-token",
        )
        assert status_viewer_tools == 200
        assert "result" in payload_viewer_tools

        status_operator_tools, payload_operator_tools = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
            token="operator-token",
        )
        assert status_operator_tools == 200
        assert int(dict(payload_operator_tools.get("error") or {}).get("code") or 0) == -32002

        status_init_operator, payload_init_operator = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {}},
            token="operator-token",
        )
        assert status_init_operator == 200
        assert "result" in payload_init_operator

        status_operator_tools_after_init, payload_operator_tools_after_init = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}},
            token="operator-token",
        )
        assert status_operator_tools_after_init == 200
        assert "result" in payload_operator_tools_after_init
    finally:
        stop_http_server(http_server, thread)


def test_mcp_phase6_http_rate_limit_prunes_stale_buckets() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", transport="http")
    server = MCPServer(config=config, api_client=client)

    now = time.monotonic()
    with server._state_lock:
        server._rate_windows["stale-client"] = deque([now - 120.0])
        server._rate_windows["fresh-client"] = deque([now - 10.0])

    assert server.allow_http_request(client_key="current-client") is True
    assert "stale-client" not in server._rate_windows
    assert "fresh-client" in server._rate_windows
    assert "current-client" in server._rate_windows


def test_mcp_phase6_http_security_logs_redact_token_values(tmp_path: Path) -> None:
    client = _FakeApiClient()
    log_path = tmp_path / "mcp_http_security.jsonl"
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        transport="http",
        auth=AuthConfig(default_role="viewer", viewer_token="viewer-token"),
        http_rate_limit_per_minute=20,
        http_security_log_path=str(log_path),
    )
    server = MCPServer(config=config, api_client=client)
    http_server, thread = start_http_server(server, host="127.0.0.1", port=0)
    host, port = http_server.server_address
    url = f"http://{host}:{port}/mcp"

    try:
        status_unauth, _payload_unauth = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            token=None,
        )
        assert status_unauth == 401

        status_auth, auth_payload = _http_post_json(
            url,
            {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
            token="viewer-token",
        )
        assert status_auth == 200
        assert "result" in auth_payload
    finally:
        stop_http_server(http_server, thread)

    raw = log_path.read_text(encoding="utf-8")
    assert "viewer-token" not in raw
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert rows
    assert any(str(row.get("reason") or "") == "auth_failed" for row in rows)
    assert any(str(row.get("reason") or "") == "request_completed" for row in rows)
    assert any(str(row.get("auth_token_hash") or "").strip() for row in rows)


def test_mcp_runtime_api_client_rejects_absolute_or_traversal_paths() -> None:
    client = RuntimeApiClient(base_url="http://127.0.0.1:7340", timeout_s=1.0)
    with pytest.raises(RuntimeApiError, match="runtime_api_invalid_path") as exc_info:
        client.request_json("GET", "/http://example.com/evil")
    assert "absolute url" in str(exc_info.value.detail).lower()
    with pytest.raises(RuntimeApiError, match="runtime_api_invalid_path"):
        client.request_json("GET", "/../../etc/passwd")


def test_mcp_phase7_lenient_compat_mode_supports_method_and_field_aliases() -> None:
    client = _FakeApiClient()
    config = ServerConfig(
        runtime_base_url="http://127.0.0.1:7340",
        auth=AuthConfig(default_role="viewer"),
        compat_mode="lenient_v1",
    )
    server = MCPServer(config=config, api_client=client)
    _call(server, 1, "initialize", {})

    tools = _call(server, 2, "tools.list")
    tool_rows = [row for row in list(dict(tools["result"]).get("tools") or []) if isinstance(row, dict)]
    assert tool_rows
    assert "input_schema" in tool_rows[0]

    health = _call(server, 3, "tools.call", {"name": "ops.health", "args": {}})
    health_payload = dict(health["result"])
    assert "structured_content" in health_payload
    assert "is_error" in health_payload

    capabilities = _call(server, 4, "tools/call", {"name": "capabilities.get", "arguments": {}})
    capability_payload = dict(dict(capabilities["result"]).get("structuredContent") or {})
    server_meta = dict(capability_payload.get("server") or {})
    compat_meta = dict(capability_payload.get("compatibility") or {})
    assert server_meta.get("compat_mode") == "lenient_v1"
    assert compat_meta.get("method_aliases_enabled") is True
    assert compat_meta.get("field_aliases_enabled") is True


def test_mcp_rejects_non_object_tool_arguments() -> None:
    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    _call(server, 1, "initialize", {})
    response = _call(server, 2, "tools/call", {"name": "ops.health", "arguments": "bad"})
    assert "error" in response
    error = dict(response["error"])
    assert int(error.get("code") or 0) == -32602
    assert "arguments" in str(error.get("message") or "")


def test_server_config_rejects_non_http_runtime_base_url() -> None:
    with pytest.raises(ValueError):
        ServerConfig(runtime_base_url="file:///tmp/runtime")


def test_server_config_rejects_invalid_compat_mode() -> None:
    with pytest.raises(ValueError):
        ServerConfig(runtime_base_url="http://127.0.0.1:7340", compat_mode="legacy")


def test_stdio_server_parse_error_recovery() -> None:
    bad_body = b"{not-json"
    bad_message = (
        f"Content-Length: {len(bad_body)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8") + bad_body
    )
    good_payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    good_message = (
        f"Content-Length: {len(good_payload)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8") + good_payload
    )
    stdin_buffer = BytesIO(bad_message + good_message)
    stdout_buffer = BytesIO()

    client = _FakeApiClient()
    config = ServerConfig(runtime_base_url="http://127.0.0.1:7340", auth=AuthConfig(default_role="viewer"))
    server = MCPServer(config=config, api_client=client)

    exit_code = run_stdio_server(server, stdin_buffer=stdin_buffer, stdout_buffer=stdout_buffer)
    assert exit_code == 0

    frames = _decode_framed_json_messages(stdout_buffer.getvalue())
    assert len(frames) == 2
    first_obj = frames[0]
    second_obj = frames[1]

    assert dict(first_obj["error"]).get("code") == -32700
    assert "result" in second_obj
