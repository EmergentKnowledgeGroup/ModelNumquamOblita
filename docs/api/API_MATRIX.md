# API Matrix

This matrix documents the **runtime HTTP API contract** used by the web UI and operator tooling.

Primary references:
- End-to-end pipeline: `docs/guides/PIPELINE_END_TO_END.md`
- Judged surface: `docs/CONTEXT_PACKAGE_V2_EXTERNAL_RESPONDER_EVAL_SPEC.md`

## Conventions

- JSON success responses typically include `{"ok": true, ...}`.
- JSON error responses typically include `{"error": "..."}` with an HTTP status (`400`, `404`, `500`).
- Query params use `offset/limit` for paging, and `q` for text search.

---

## Runtime chat + sessions

### `POST /api/chat/session/start`
- Purpose: create a new chat session.
- Body: `{ "label": "optional label" }`
- Success: `{ "ok": true, "session": { "session_id": "sess_...", ... } }`

### `GET /api/chat/sessions`
- Purpose: list sessions (newest updated first).
- Success: `{ "ok": true, "sessions": [ ... ] }`

### `POST /api/chat/session/<session_id>/turn`
- Purpose: send a turn in a session.
- Body: `{ "message": "...", "memory_preference": "auto|chat_first|memory_assist", "retrieval_query": "optional override" }`
- Success: `{ "ok": true, "turn": { "turn_id": "turn_...", "memory_route": "none|stm_only|ltm_light|ltm_deep", ... } }`

### `GET /api/chat/session/<session_id>/history`
- Purpose: list session turns.

### `GET /api/chat/session/<session_id>/telemetry`
- Purpose: session aggregate telemetry (routes, latency, counts).

### `POST /api/chat/route-preview`
- Purpose: preview routing without sending a turn.
- Body: `{ "message": "...", "session_id": "optional", "memory_preference": "auto|chat_first|memory_assist", "high_risk": false }`
- Success: `{ "ok": true, "preview": { "route": "...", "reason": "...", ... } }`

### `POST /api/chat/context-package`
- Purpose: build a context package without sending a turn.
- Body: `{ "message": "...", "session_id": "optional", "package_version": "v1|v2", "render_citations": false }`
- Success: `{ "ok": true, "package": { "package_version": "v1|v2", ... } }`

### `POST /api/chat`
- Purpose: send a single non-session turn (debug / single-turn mode).
- Body: `{ "message": "...", "package_version": "v1|v2", "render_citations": false }`

---

## Turns + “Why this answer?”

### `GET /api/turns`
- Purpose: list recent turns.

### `GET /api/turns/<turn_id>`
- Purpose: fetch one turn record.

### `GET /api/turns/<turn_id>/why`
- Purpose: “Why panel” payload for a turn.
- Query: `citations=true|false`

---

## Wizard (pipeline UI)

Wizard runs are persisted and resumable (run ids are `wizard_<stamp>`).

### `GET /api/wizard/state`
- Purpose: load latest wizard state (or a requested run id).
- Query: `run_id=wizard_...` (optional)

### `POST /api/wizard/start`
- Purpose: start or resume a wizard run.
- Body: `{ "mode": "new|resume", "run_id": "optional" }`

### `POST /api/wizard/import/validate`
- Purpose: validate an archive JSON file (counts, roles, obvious issues).
- Body: `{ "run_id": "wizard_...", "archive_path": "/path/to/db.json" }`

### `POST /api/wizard/import/run`
- Purpose: import archive into sqlite store via repo tool.
- Body: `{ "run_id": "wizard_...", "archive_path": "/path/to/db.json", "store_path": "optional", "out_dir": "optional" }`
- Output includes report paths and updated wizard pointers.

### `POST /api/wizard/build/run`
- Purpose: build episode cards (draft + rejects + readout).
- Body: `{ "run_id": "wizard_...", "store_path": "optional", "policy_preset": "strict|..." }`

### `POST /api/wizard/builder/profile/save`
- Purpose: save builder profile (entities/cues/domains) and bind it to the run.

### `GET /api/wizard/builder/profile`
- Purpose: fetch selected builder profile for the run.
- Query: `run_id=wizard_...`

### `GET /api/wizard/review/cards`
- Purpose: list episode cards with per-card review decision overlay.
- Query: `run_id=wizard_...`, plus `status/q` filters.

### `POST /api/wizard/review/update`
- Purpose: set per-episode review decisions (`approved|edited|rejected|pending`).

### `POST /api/wizard/review/compile`
- Purpose: compile reviewed set and publish `runtime/episodes/episode_cards.reviewed.json`.

### `POST /api/wizard/verify/run`
- Purpose: run local verification checks and summarize “Safe / Needs attention”.
- Output includes `actionable_links` with API/navigation targets for follow-up fixes.

### `POST /api/wizard/go-live`
- Purpose: mark pointers as “published” and return runtime URL + config snapshot.
- Output includes provider/model snapshot and `config_entrypoint` for runtime provider settings.

### `POST /api/wizard/restore-last-published`
- Purpose: restore wizard published pointers to the previous snapshot (rollback safety action).
- Body: `{ "run_id": "wizard_..." }`
- Output includes restored pointers and remaining snapshot count.

### `GET /api/wizard/artifacts`
- Purpose: return canonical artifact paths for the run (open-folder hints, reports).
- Query: `run_id=wizard_...`

---

## Memory management (episodes, cards, atoms, proposals)

### Episodes (episodic memory layer)

### `GET /api/memory/episodes`
- Purpose: list episode cards from the active episodes source (reviewed/draft by run pointer).
- Query: `run_id=wizard_...` (optional), `status=all|approved|disabled`, `q=...`

### `POST /api/memory/episodes/<episode_id>/disable`
### `POST /api/memory/episodes/<episode_id>/enable`
### `POST /api/memory/episodes/<episode_id>/edit`
- Purpose: operator control for episode cards (title/summary/tags edits, enable/disable).

### `POST /api/memory/episodes/undo-last`
- Purpose: undo the most recent episode edit/enable/disable action.

### Evidence cards + atoms (lower-level views)

### `GET /api/memory/cards`
### `GET /api/memory/cards/<card_id>`
### `GET /api/memory/atoms`
### `GET /api/memory/atom/<atom_id>`
- Purpose: browse and inspect memory at card/atom levels (provenance + graph).

### `POST /api/memory/atoms/<atom_id>/conflict`
- Purpose: mark a conflict with a reason for operator visibility.

### Graph views
### `GET /api/memory/graph?atom_id=...`
### `GET /api/memory/graph-map?...`

### Mutation proposals (safe writeback / operator review)

### `GET /api/memory/proposals`
- Purpose: list proposals (or report `queue_unavailable`).

### `POST /api/memory/proposals/create-delete`
### `POST /api/memory/proposals/create-edit`
- Purpose: create proposals (delete/edit) when the queue is enabled.

### `POST /api/memory/proposals/<proposal_id>/approve`
### `POST /api/memory/proposals/<proposal_id>/reject`

### Consolidation
### `POST /api/memory/decay/recompute`

---

## Ops + diagnostics

### `GET /api/state`
- Purpose: runtime state summary (turn counts, routing stats, costs).

### `GET /api/runtime/decision-reasons`
- Purpose: canonical labels for routes and reason codes (UI explainability).

### `GET /api/runtime/provider/config`
- Purpose: expose active provider/model/adapters config used by Go Live and runtime diagnostics.

### `GET /api/runtime/telemetry/summary`
- Purpose: aggregate telemetry counters/latency/cost metrics for the runtime session ledger panel.

### `GET /api/runtime/telemetry/turns`
- Purpose: paged turn-level telemetry feed for the runtime ledger panel.
- Query: `limit=...` (bounded server-side).

### `GET /api/runtime/health`
### `POST /api/runtime/health/export`
- Purpose: run health checks and export a diagnostics bundle.

### `GET /api/runtime/packaging/instructions`
- Purpose: operator-friendly packaging/run instructions.
- Output includes one-click runtime commands plus `single_exe` build metadata (`build_command`, wrapper entrypoints, artifact hint, script availability).

### `GET /api/runtime/writeback/policy`
### `POST /api/runtime/writeback/policy`
- Purpose: read/update writeback policy (OFF by default).

### `GET /api/archive/citation/<source_id>%23<message_id>`
- Purpose: resolve a citation token into matching archive snippets. (Note: URL-encode `#` as `%23` in clients.)

---

## Adapters (compat payloads)

### `GET /api/adapters`
### `POST /api/adapters/<adapter>/chat`
### `POST /api/adapters/<adapter>/context-package`
