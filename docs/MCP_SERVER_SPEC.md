# MCP Server Spec (Self‑Hosted) — Full Tool Surface + Guards + Packaging

## 0) Goal (what we are building)

Build a **self-hosted MCP server** that lets any MCP-capable agent/client connect to NumquamOblita as a trusted “memory subsystem”, without bypassing:
- evidence requirements,
- bounded retrieval,
- abstain/clarify fail-closed behavior,
- operator review gates for mutations.

The MCP server is the **universal integration layer**: it normalizes client requests into the system’s native operations and returns stable, schema’d outputs.

## 1) Non‑negotiables (contract)

- **Offline-first default**: everything works with local data + optional local model provider.
- **No memory claim without evidence**: supported answers must remain traceable to evidence IDs.
- **Boundedness**: retrieval fanout and payload size are capped; “retrieve everything” is never allowed.
- **Fail closed**: weak or conflicting evidence yields abstain or a single clarifying question.
- **Mutations are gated**: changes to memory require explicit operator approval and are reversible.
- **Security by default**: local-only binding unless explicitly enabled; auth required for remote use.

## 2) What “MCP integration” means here

The server exposes:
- **Tools**: callable operations (chat, retrieval, browse, proposals, wizard steps, ops).
- **Resources**: read-only objects (episodes, atoms, cards, graphs, run summaries) addressable by IDs.
- **Prompts** (optional): curated instruction templates for consistent agent usage (e.g., “ask a clarifying question safely”).

It supports the transport(s) required by target clients (stdio first; optionally HTTP-based transport for remote access).

## 3) Architecture (one mental model)

```mermaid
flowchart LR
  C[Agent / Client] -->|MCP| S[MCP Server]
  S -->|local calls| R[Runtime Memory Service]
  R --> D[(Local evidence + episode artifacts)]
  R -->|optional| M[Responder model endpoint\n(local or cloud)]
  R --> V[Verifier\n(evidence check)]
```

Key design point: the MCP server **does not implement memory logic**. It delegates to the runtime memory service and enforces integration policies at the boundary (auth, rate limits, tool permissions, redaction, audit logs).

## 4) Iteration SOP (required)

Apply this SOP **for every codebase change** during implementation:

**Pass 1 — targeted correctness**
- [ ] Make the smallest change that advances one checklist item.
- [ ] Add/adjust targeted tests for the change (unit or narrow integration).
- [ ] Run the targeted tests; fix until green.

**Pass 2 — regression + integration**
- [ ] Run the full test suite (or the closest available substitute).
- [ ] Run a smoke flow end-to-end (chat + browse + at least one tool in the changed area).
- [ ] Confirm no behavior drift on “routine chat should not over-recall” and “unsupported recall must abstain”.

If Pass 2 fails, do not proceed to the next checklist item.

## 5) Security + policy model

### 5.1 Deployment modes

**Mode A: Local desktop (default)**
- Transport: stdio (spawned by the client)
- Binding: local only
- Auth: optional token (still recommended)

**Mode B: Self-hosted service (explicit opt-in)**
- Transport: HTTP-based
- Binding: configurable interface/port behind TLS
- Auth: required (token + optional mTLS / SSO front door)
- Rate limiting + audit logs: required

### 5.2 Authentication

Minimum:
- One bearer token for the MCP server (“server access token”).
- Optional per-client tokens for audit attribution.

Recommended:
- Token rotation support.
- Separate tokens per permission tier: read-only vs operator vs admin.
- Secret-manager-backed token source for remote deployments (`env_json` or command/file-backed sync).
- Production mode must fail closed if local default tokens are enabled.

### 5.3 Authorization (permissions)

Define roles:
- **viewer**: read-only tools + resources.
- **operator**: viewer + mutation proposals + episode enable/disable/edit.
- **admin**: operator + wizard publish/go-live + policy toggles + diagnostics export.

Enforce:
- Per-tool allowlist by role.
- Default role = viewer.
- Mutating tools must require operator/admin and explicit “mutations_enabled=true”.

### 5.4 Mutation policy

All mutation tools must be one of:
- **proposal-based** (create an edit/delete proposal; requires explicit approve/reject step), or
- **reversible toggles** (enable/disable/undo) with audit trail.

Hard rule: no “silent writeback” in response to a chat tool call.

### 5.5 Audit + observability

For every MCP request:
- record tool name, caller identity, timestamp, latency, result status,
- redact secrets and large payloads,
- include correlation ids to trace runtime actions.

Expose a read-only “audit summary” resource for operators.

## 6) Tool surface (full list)

Tool names are stable, lowercase, dot‑separated. Each tool has:
- `purpose`
- `inputs`
- `outputs`
- `errors`
- `side_effects`
- `permission`

### 6.0 Versioning and compatibility

- Expose a server `protocol_version` and `toolset_version`.
- Never break a published tool contract without:
  - adding a new tool name (preferred), or
  - adding a backward-compatible optional field.
- Include `deprecation` metadata when a tool is superseded.
- Provide a `capabilities.get` tool that returns:
  - supported transports,
  - enabled tool names,
  - permission model,
  - hard caps (max nodes/links/payload).

### 6.1 Chat + context tools

1) `chat.start_session`
- Purpose: create a new session.
- Inputs: `{ label?: string }`
- Outputs: `{ session_id: string, created_at: string }`
- Permission: viewer

2) `chat.list_sessions`
- Inputs: `{ limit?: number, offset?: number }`
- Outputs: `{ sessions: [{ session_id, label, updated_at, turn_count }] }`
- Permission: viewer

3) `chat.turn`
- Purpose: send a user message and get the final answer (with verifier gating).
- Inputs:
  - `session_id?: string`
  - `message: string`
  - `memory_preference?: "auto"|"chat_first"|"memory_assist"`
  - `retrieval_query?: string` (explicit override; treated as operator action)
  - `high_risk?: boolean`
  - `include_why?: boolean` (default false)
- Outputs:
  - `answer: string`
  - `decision: "PASS"|"ABSTAIN"|"CLARIFY"|"NO_MEMORY"|"FAIL"`
  - `citations?: string[]` (optional; gated by policy)
  - `why?: { summary, evidence, time_window, citations }` (when requested/allowed)
  - `turn_id?: string` (if session is used)
- Errors:
  - invalid message
  - policy blocked (e.g., high-risk tool not allowed)
- Permission: viewer
- Side effects: appends a turn to the session if `session_id` is provided.

4) `chat.route_preview`
- Purpose: show whether memory retrieval would be used, without sending a turn.
- Inputs: `{ message, session_id?: string, memory_preference?: ..., high_risk?: boolean }`
- Outputs: `{ route: "none"|"stm_only"|"ltm_light"|"ltm_deep", reason: string }`
- Permission: viewer

5) `chat.build_context_package`
- Purpose: generate the context package used to constrain responders.
- Inputs:
  - `message: string`
  - `session_id?: string`
  - `package_version?: "v2"` (default v2)
  - `render_citations?: boolean` (default false)
  - `high_risk?: boolean`
- Outputs: `{ package: object, stats: { retrieved_count, route, stop_reason } }`
- Permission: viewer

### 6.2 “Why” + evidence inspection tools

6) `why.explain_turn`
- Purpose: explain a stored turn (plain-language “why”).
- Inputs: `{ turn_id: string, include_citations?: boolean }`
- Outputs: `{ decision, reason, evidence: [...], citations?: [...] }`
- Permission: viewer

7) `evidence.resolve_citation`
- Purpose: expand a citation token into matching evidence snippets.
- Inputs: `{ citation_token: string, max_matches?: number }`
- Outputs: `{ citation_token, matches: [{ excerpt, timestamp, source_ref }] }`
- Permission: viewer

### 6.3 Memory browse tools (read-only)

8) `memory.list_episodes`
- Inputs: `{ q?: string, status?: "all"|"approved"|"disabled", limit?: number, offset?: number }`
- Outputs: `{ episodes: [{ episode_id, title, summary, status, tags, updated_at }] }`
- Permission: viewer

9) `memory.get_episode`
- Inputs: `{ episode_id: string }`
- Outputs: `{ episode: { ...full episode fields... } }`
- Permission: viewer

10) `memory.list_atoms`
- Inputs: `{ q?: string, status?: "all"|..., contradiction?: "all"|"true"|"false", limit?: number, offset?: number }`
- Outputs: `{ atoms: [{ atom_id, kind, status, excerpt, citations, scores... }] }`
- Permission: viewer

11) `memory.get_atom`
- Inputs: `{ atom_id: string }`
- Outputs: `{ atom: { canonical_text, provenance, links, status, conflicts... } }`
- Permission: viewer

12) `memory.graph_map`
- Purpose: return a bounded graph snapshot for visualization.
- Inputs: `{ q?: string, status?: ..., kind?: ..., contradiction?: ..., limit?: number }`
- Outputs: `{ nodes: [...], links: [...], total: number, truncated: boolean }`
- Permission: viewer

13) `memory.graph_neighbors`
- Purpose: return immediate neighbors/links for a specific atom/episode node.
- Inputs: `{ node_id: string, depth?: 1|2, limit?: number }`
- Outputs: `{ node: {...}, neighbors: [...], links: [...] }`
- Permission: viewer

### 6.4 Memory mutation tools (operator)

All mutation tools must:
- support `dry_run` where possible,
- emit an audit record,
- return a reversible handle or proposal id,
- never bypass evidence/verifier rules.

14) `memory.disable_episode`
- Inputs: `{ episode_id: string, reason?: string }`
- Outputs: `{ ok: true, episode_id, status: "disabled" }`
- Permission: operator
- Side effects: episode is no longer eligible for retrieval.

15) `memory.enable_episode`
- Inputs: `{ episode_id: string }`
- Outputs: `{ ok: true, episode_id, status: "approved" }`
- Permission: operator

16) `memory.edit_episode`
- Inputs: `{ episode_id, patch: { title?, summary?, tags?, actors? }, dry_run?: boolean }`
- Outputs: `{ ok: true, episode_id, applied: boolean, diff_summary }`
- Permission: operator

17) `memory.undo_last_change`
- Inputs: `{ scope?: "episode_edits"|"proposals"|"all" }`
- Outputs: `{ ok: true, undone: { kind, id }, state: { ... } }`
- Permission: operator

### 6.5 Proposal queue tools (safe writeback)

18) `proposals.list`
- Inputs: `{ status?: "open"|"approved"|"rejected"|"all", limit?: number, offset?: number }`
- Outputs: `{ proposals: [{ proposal_id, kind, status, created_at, summary }] }`
- Permission: operator

19) `proposals.create_edit`
- Inputs: `{ target_id: string, patch: {...}, reason: string, dry_run?: boolean }`
- Outputs: `{ proposal_id, status: "open" }`
- Permission: operator

20) `proposals.create_delete`
- Inputs: `{ target_id: string, reason: string, dry_run?: boolean }`
- Outputs: `{ proposal_id, status: "open" }`
- Permission: operator

21) `proposals.approve`
- Inputs: `{ proposal_id: string, note?: string }`
- Outputs: `{ ok: true, proposal_id, status: "approved" }`
- Permission: operator

22) `proposals.reject`
- Inputs: `{ proposal_id: string, note: string }`
- Outputs: `{ ok: true, proposal_id, status: "rejected" }`
- Permission: operator

### 6.6 Wizard/pipeline tools (operator/admin)

These exist to let non-engineering tools drive the full pipeline safely.

23) `wizard.start_or_resume`
- Inputs: `{ mode: "new"|"resume", run_id?: string }`
- Outputs: `{ run_id: string, stage: string, resume_supported: true }`
- Permission: operator

24) `wizard.validate_archive`
- Inputs: `{ run_id: string, archive_descriptor: object }`
- Outputs: `{ ok: true, counts, warnings: [...], blockers: [...] }`
- Permission: operator

25) `wizard.import_run`
- Inputs: `{ run_id: string, archive_descriptor: object }`
- Outputs: `{ ok: true, import_report, store_descriptor }`
- Permission: operator

26) `wizard.build_episodes`
- Inputs: `{ run_id: string, policy_preset?: string }`
- Outputs: `{ ok: true, episode_build_report, draft_descriptor }`
- Permission: operator

27) `wizard.review_list`
- Inputs: `{ run_id: string, q?: string, status?: ... }`
- Outputs: `{ cards: [...], counts }`
- Permission: operator

28) `wizard.review_update`
- Inputs: `{ run_id: string, updates: [{ episode_id, decision, edits? }] }`
- Outputs: `{ ok: true, updated: number }`
- Permission: operator

29) `wizard.compile_reviewed`
- Inputs: `{ run_id: string }`
- Outputs: `{ ok: true, published_descriptor, episode_count }`
- Permission: operator

30) `wizard.verify`
- Inputs: `{ run_id: string }`
- Outputs: `{ status: "safe"|"watch"|"needs_attention", checks: [...], actionable: [...] }`
- Permission: operator

31) `wizard.go_live`
- Inputs: `{ run_id: string }`
- Outputs: `{ ok: true, runtime_descriptor, provider_snapshot }`
- Permission: admin

32) `wizard.restore_last_published`
- Inputs: `{ run_id: string }`
- Outputs: `{ ok: true, restored: true, pointers }`
- Permission: admin

### 6.7 Ops/diagnostics tools (admin)

33) `ops.health`
- Outputs: `{ status: "safe"|"watch"|"needs_attention", checks: [...] }`
- Permission: viewer (read-only)

34) `ops.export_diagnostics`
- Purpose: produce a support bundle (no secrets).
- Inputs: `{ include_recent_turns?: boolean }`
- Outputs: `{ ok: true, bundle_descriptor }`
- Permission: admin

35) `ops.get_provider_config`
- Outputs: `{ model_name, provider, adapters, settings }`
- Permission: viewer

36) `ops.set_policy`
- Purpose: toggle server/runtime policies (writeback enablement, citation visibility, risk limits).
- Inputs: `{ policy_patch: object, dry_run?: boolean }`
- Outputs: `{ ok: true, applied: boolean, policy: object }`
- Permission: admin

## 7) Resources (read-only, addressable by ID)

Expose resources that mirror the tool outputs, so clients can browse without repeated tool calls:
- `episode:<id>`
- `atom:<id>`
- `turn:<id>`
- `graph:snapshot:<stamp>`
- `audit:summary:<date>`

Each resource must be bounded (size limits) and redact secrets.

## 8) Packaging + cross‑client integration (docs checklist)

Deliver a single “how to connect” page that includes:
- [x] local desktop setup (spawn stdio server)
- [x] self-hosted service setup (HTTP transport + TLS + token)
- [x] permission tiers and how to rotate tokens
- [x] troubleshooting steps and “health” verification

Phase 7 references:
- `docs/guides/MCP_CROSS_CLIENT_COMPATIBILITY_MATRIX.md`
- `docs/guides/MCP_TOOL_VERSIONING_AND_COMPAT_MODE_POLICY.md`

Minimum configuration pattern to document (client-agnostic):
- `name`: `"numquamoblita"`
- `command`: server executable
- `args`: transport mode + bind address + auth
- `env`: tokens and optional provider endpoints

Include at least two example configurations:
- **Local**: stdio transport, read-only token.
- **Remote**: HTTP transport behind TLS, operator token, rate limits enabled.

### 8.1 Client setup checklists (practical)

The goal is that an operator can connect in under 2 minutes without reading code.

**Claude Desktop (local)**
- [ ] Install the runtime + MCP server command on the same machine.
- [ ] In the client’s MCP server settings, add a new server entry:
  - command + args (stdio transport)
  - environment variables (token + optional local model provider)
- [ ] Verify with `ops.health`, then run the smoke checklist (Section 9.3).

**Cursor / IDE copilots (local)**
- [ ] Add an MCP server entry in the IDE’s MCP integration settings.
- [ ] Use stdio transport by default (spawned process).
- [ ] Verify tool discovery (tools list appears) and run `memory.list_episodes`.

**Headless agents / CI (local or remote)**
- [ ] Start the MCP server in service mode (HTTP transport) behind TLS.
- [ ] Provide bearer token via secret manager.
- [ ] Enforce read-only role in CI unless the job is explicitly “operator”.

Runtime integration auth hardening (service mode):
- `NO_INTEGRATION_SECRET_MANAGER_PROVIDER=env_json|command` enables managed bearer-token sources.
- `NO_INTEGRATION_RUNTIME_MODE=production` blocks startup when local default integration tokens are enabled.
- In production, `NO_INTEGRATION_SECRET_MANAGER_PROVIDER=command` also requires `NO_INTEGRATION_SECRET_MANAGER_COMMAND`.
- Token scopes can restrict operations via `allowed_operations` per token record.

### 8.2 Example client configs (copy/paste patterns)

**Local stdio (read-only)**

```json
{
  "mcpServers": {
    "numquamoblita": {
      "command": "numquamoblita-mcp",
      "args": ["--transport", "stdio", "--default-role", "viewer"],
      "env": {
        "NO_MCP_AUTH_TOKEN": "replace-me",
        "NO_PROVIDER": "lmstudio",
        "NO_PROVIDER_BASE_URL": "http://127.0.0.1:1234"
      }
    }
  }
}
```

**Remote HTTP (operator)**

```json
{
  "mcpServers": {
    "numquamoblita": {
      "url": "https://your-hostname.example/mcp",
      "headers": { "Authorization": "Bearer replace-me" }
    }
  }
}
```

### 8.3 Prompts (optional, recommended)

Prompts are curated templates that help agents use tools safely and consistently. Provide at least:

- `prompt.memory_safe_recall`: how to ask for recall without forcing hallucination.
- `prompt.abstain_then_clarify`: canonical “I don’t have that memory” phrasing + single-question clarify behavior.
- `prompt.operator_triage`: when to open “Why”, when to disable an episode, when to propose an edit.
- `prompt.citation_discipline`: how to keep citations internal unless explicitly requested.

## 9) Testing plan (what must exist before “done”)

### 9.1 Unit tests (fast)
- Tool input validation (schema, bounds, redaction).
- Auth + permissions matrix.
- Policy guard behavior (mutations blocked by default).

### 9.2 Integration tests (local)
- “Read-only happy path”: list episodes/atoms → graph snapshot → explain turn.
- “Chat safety path”: unsupported recall → abstain; routine chat → no retrieval.
- “Mutation path”: create proposal → approve → verify memory changes are visible and reversible.

### 9.3 End-to-end smoke (operator)
- Start server, connect with a real MCP client, run the “hello” checklist:
  - `ops.health`
  - `memory.list_episodes`
  - `chat.turn` (routine)
  - `chat.turn` (supported recall)

### 9.4 Performance budgets
- Enforce hard caps per tool: max nodes/links, max evidence items, max payload size.
- Add a regression test that fails if caps are exceeded.

## 10) Implementation phases (recommended order)

Each phase ends with **Pass 2** regression SOP completion.

### Phase 0 — Skeleton + transport
- [ ] Pick primary transport (stdio) and implement handshake.
- [ ] Implement auth token parsing (even if optional locally).
- [ ] Implement tool registry + schema validation.
- [ ] Add “health” tool and a minimal “capabilities” resource.

### Phase 1 — Read-only memory browse
- [ ] Episodes: list/get.
- [ ] Atoms: list/get.
- [ ] Graph: bounded snapshot + per-node neighbors.
- [ ] Add redaction + payload caps + tests.

### Phase 2 — Chat + context package
- [ ] Session start/list/history.
- [ ] Turn sending with route preview.
- [ ] Context package tool for audit.
- [ ] Verify routine-chat does not over-recall (regression).

### Phase 3 — “Why” + citation expansion
- [ ] Explain a turn.
- [ ] Resolve citation tokens into evidence snippets.
- [ ] Ensure citation expansion is bounded and cannot enumerate the full store.

### Phase 4 — Operator mutations (safe)
- [ ] Episode enable/disable/edit + undo.
- [ ] Proposals create/edit/delete + approve/reject.
- [x] Add permissions tests and audit log assertions.

### Phase 5 — Wizard control surface
- [ ] Start/resume, validate, import, build, review update, compile, verify.
- [ ] Go-live + rollback gated behind admin role.
- [ ] Add a “dry run” mode that never mutates persistent state.

### Phase 6 — Remote hosting hardening
- [x] HTTP transport with TLS recommendations.
- [x] Rate limits and request size limits.
- [x] Structured logs + exportable diagnostics.
- [x] Pen-test checklist (token leakage, SSRF, path traversal, replay).

Implementation notes:
- HTTP service enforces bounded request size + per-client rate limiting in transport handler.
- TLS posture is explicitly exposed in `capabilities.get` (`remote_hardening.tls`) with deploy recommendation to run behind TLS and enable `enforce_https=true`.
- Structured security logs are emitted as JSONL (`http_security_log_path`) and included in diagnostics export bundles.
- Replay hardening supports optional `X-MCP-Nonce` uniqueness windows (`http_nonce_replay_window_seconds`) with reject-on-duplicate behavior per client key.
- Runtime API client path guards block absolute URL paths and traversal sequences before outbound requests.

### Phase 7 — Cross-client docs + compatibility matrix
- [x] Document compatibility with at least 3 MCP clients.
- [x] Provide a stable tool naming/versioning policy.
- [x] Add a “compat mode” if a major client requires a slightly different shape.

## 11) Definition of done

“Done” means:
- All phases implemented through Phase 4 at minimum (read-only + safe mutation workflow).
- Remote hosting (Phase 6) is either implemented or explicitly deferred with a documented risk rationale.
- Full regression SOP is followed (Pass 1 + Pass 2 for each change).
- A real MCP client can connect and complete the end-to-end smoke checklist.
