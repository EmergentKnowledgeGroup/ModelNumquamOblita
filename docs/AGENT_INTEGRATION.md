# Agent Integration

## Start with this rule

If you are building a new agent integration, use:

`integration-v1`

first.

Use adapter routes only when you already have a client that expects a specific envelope like OpenClaw or Nanobot. Use MCP when you want tool-driven local agent use.

## Recommended topology

Recommended shape:

`one assistant or profile -> one MNO runtime sidecar -> one store`

Avoid a single shared multi-agent runtime unless you are ready to own the state and routing complexity yourself.

## Pre-activation curation wall

An imported store is not automatically an activated reviewed memory set. Standard `mno-runtime` and `mno-agent-mcp` launches without reviewed episode cards return `CURATION_REQUIRED`.

When that happens:

1. Run `mno-curate --store <atoms.sqlite3>` or `mno-curate --input <raw-source>`.
2. Read the emitted `hcr_status_json`, `run_id`, and loopback `curation_url`.
3. Tell the user that episode cards need review and open/share that local URL.
4. Use `mno-curation-mcp --runtime-base-url <url> --run-id <run>` for draft-only agent proposal work.
5. Do not claim readiness until the human has resolved every card and HCR completes Publish, Safe Verify, and Activate.

The HCR MCP profile is pinned to one run and exposes only draft curation. It cannot promote a proposal into `review_decisions`, publish, verify, activate, install an integration, force-release another curator, or call unrelated runtime tools. Full contract: [Headless Curation Room](HEADLESS_CURATION_ROOM.md).

## Three valid integration paths

### 1. `integration-v1`

Best for:
- OpenClaw-style orchestrators when you control the call layer
- Hermes Agent style generic agents
- Nanobot-like systems when you want a stable public contract
- custom sidecars and local orchestration loops

Endpoints:
- `GET /api/integration/v1/capabilities`
- `GET /api/integration/v1/health`
- `POST /api/integration/v1/context/build`
- `POST /api/integration/v1/context/why`
- `POST /api/integration/v1/memory/source/register`
- `POST /api/integration/v1/memory/observe`
- `POST /api/integration/v1/memory/maintain`
- `GET /api/integration/v1/memory/proposals`
- `POST /api/integration/v1/memory/proposals/{record_id}/dismiss`
- `POST /api/integration/v1/memory/proposals/{record_id}/bridge`
- `POST /api/integration/v1/writeback/propose`
- `POST /api/integration/v1/writeback/resolve`

### 2. Compatibility adapters

Best for:
- existing clients that already speak a known request/response shape

Current adapters:
- `reference`
- `openclaw`
- `nanobot`

### 3. MCP

Best for:
- Claude Code / Claude Desktop
- tool-driven assistant/agent clients
- local tool-driven agents
- operator workflows
- optional draft-curation tooling

## Easiest setup path

If you want a guided install or export flow:

1. run `./launch_setup_workspace.sh`, `./launch_setup_workspace.ps1`, or `launch_setup_workspace.bat`
2. open the setup workspace
3. choose a target
4. either install the managed local entry or export a bundle

Current target families:
- Claude Code / Claude Desktop
- generic MCP clients
- generic HTTP sidecars
- OpenClaw bundles
- Hermes Agent bundles
- Nanobot bundles

## `integration-v1` request shape

All responses use this envelope:

```json
{
  "schema_version": "integration.v1",
  "request_id": "...",
  "request_id_source": "client|server",
  "operation": "...",
  "ok": true,
  "degrade_mode": false,
  "warnings": [],
  "data": {}
}
```

Typical `context.build` request:

```json
{
  "schema_version": "integration.v1",
  "request_id": "req_CONTEXTBUILD123456",
  "session_id": "session_001",
  "run_id": "run_001",
  "data": {
    "message": "What do you remember about tea preference?",
    "retrieval": { "top_k": 5 },
    "risk_signal": "medium"
  }
}
```

## Work-session scratchpad context

WSS, the work-session scratchpad, is MNO's built-in continuity helper for active agent work. It is live-on for v2 context packages when strict project/thread/workstream scope identity is present, and it appears as `work_session_context` with trust tier `scratchpad_ephemeral`.

Agent rule:

- use WSS to avoid rereading repeated work-session background
- do not treat WSS as retrieved memory evidence
- do not use WSS to support user-facing memory claims
- keep `work_session_scope.thread_id` and `work_session_scope.workstream_key` stable for a real work lane

The stable `integration-v1` memory envelope remains evidence-focused. Context-package and adapter routes can carry WSS when strict scope is supplied. STM/session state and WSS remain helper context, never evidence. See [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md).

## Three different ways memory enters MNO

Do not collapse these workflows:

1. **Raw import**: source files/folders are normalized and materialized as durable evidence atoms for the normal build → review → publish pipeline.
2. **Live `memory.observe`**: after a completed external turn, send the bounded messages plus server-issued signed handles. MNO may record `provisional_observed`, reinforce it with independent evidence, or create a derived `provisional_consolidated` record. These records remain below evidence atoms and human-reviewed canonical truth.
3. **User says “remember this”**: send `remember_intent=user_explicit` to `memory.observe`, then explicitly call `writeback.propose`. A human with `review_apply` may call `writeback.resolve` using `decision=approve` and `apply=true`, which creates an `evidence_atom` with `human_reviewed=false`. It is still not published canonical truth.

For live observation, call `context.build` before the model turn and retain its signed `source_registration` and `retrieval_receipt`. Do not fabricate them. A receipt proves the server-side retrieval set; replays, quotes, and model summaries never add independent support.

Typical `writeback.propose` rules:
- bearer auth required
- `Idempotency-Key` header required
- proposal only by default
- no silent truth mutation

## How the hot loop should look

### Engineering flow

1. Start one runtime sidecar per assistant/profile/store.
2. Call `capabilities` once at startup.
3. Call `context.build` for each user turn when you want MNO evidence.
4. Feed `agent_context` into the agent prompt, or use `context_text` plus `evidence` if you need a custom wrapper.
5. If needed, call `context.why` for audit/debug surfaces.
6. After the turn, optionally call `memory.observe` with signed registration/receipt handles to capture low-risk provisional memory.
7. If the user explicitly wants durable writeback, call `writeback.propose`.
8. Let a human workflow holding the separate `review_apply` capability resolve with `writeback.resolve`; `apply=true` creates only a non-reviewed evidence atom.

Before every write or maintenance operation, inspect `integration.capabilities.get` (and refresh it after dependency/auth changes). Tool presence is not proof that the current principal can use it: honor each operation's backend/policy state, `authorized`, `available`, and reason fields. Never retry a denied operation by selecting a stronger credential yourself.

Exported bundles are launch plans, not installers. They call the installed `mno-runtime` or `mno-agent-mcp` command, contain no originating checkout path, and fail before mutation when that declared dependency is missing.

Capability responses also advertise the `mno.support_ticket.v1` contract. If you reproduce an MNO defect, use `mno-report` to create a redacted local issue bundle with exact steps and checks. GitHub submission is a separate explicit `--submit` action; see [Support Tickets for Agents](SUPPORT_TICKETS_FOR_AGENTS.md).

## Agent-facing facts contract

`context.build` returns both:
- `context_text`: compact memory text for custom orchestration
- `agent_context`: serialized `mno.agent_context.v2` facts

Use `agent_context` when you are frontloading memory into OpenClaw, Hermes Agent, Nanobot, or a generic sidecar prompt. It is a data contract, not a system-prompt policy.

The payload has this shape:

```json
{
  "schema_version": "mno.agent_context.v2",
  "retrieval": {"route": "ltm_deep", "confidence": 0.82, "evidence_count": 1},
  "facts": [
    {"kind": "evidence", "value": {"evidence_id": "...", "citations": ["..."]}},
    {"kind": "temporal_context", "value": {"schema_version": "mno.temporal-context.v1", "now_utc": "..."}}
  ],
  "truncation": {"truncated": false}
}
```

MNO supplies declarative facts only. It never puts "ask the user," "mention this," "remind," or other behavioral instructions in `agent_context`; reminder text is data. The consuming model/host remains responsible for its own policy and can use `context.why` or temporal `get` to inspect opaque IDs.

### Caveman flow

1. User says thing.
2. Ask MNO what memory matters.
3. MNO sends back a bounded memory bundle labeled as memory.
4. Agent answers using that bundle.
5. MNO may keep a revisable helper note with receipts, but it cannot call that note truth.
6. “Remember this” opens a human-controlled proposal.
7. Only normal human review and publish make canonical truth.

## OpenClaw

If you control the orchestration layer, prefer `integration-v1`.

If you already need OpenClaw-style chat envelopes, use:
- `POST /api/adapters/openclaw/chat`
- `POST /api/adapters/openclaw/context-package`

Why:
- faster compatibility
- preserves the existing OpenClaw-shaped payload

But the adapter is still a shim, not the main public contract.

See:
- [OpenClaw Integration](integrations/OPENCLAW.md)

## Hermes Agent

Hermes Agent has no dedicated MNO adapter in this clean repo.

Recommended path:
- use `integration-v1` for the hot loop
- or use MCP if Hermes is already tool-driven and local

See:
- [Hermes Agent Integration](integrations/HERMES_AGENT.md)

## Nanobot

If you want quick envelope compatibility, use:
- `POST /api/adapters/nanobot/chat`
- `POST /api/adapters/nanobot/context-package`

If you want the more stable long-term contract, still prefer `integration-v1`.

See:
- [Nanobot Integration](integrations/NANOBOT.md)

## Related docs

- [Generic Sidecar Integration](integrations/GENERIC_SIDECAR.md)
- [MCP Integration](MCP_INTEGRATION.md)
- [API](API.md)
- [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md)

## Temporal agent contract

Treat the `agent_context_v2` temporal section as a lean neutral fact envelope. MNO may provide server clock time, timezone provenance, prior-turn timing, due/upcoming provisional notes, citations, and opaque expansion IDs. It never supplies behavioral instructions such as “remind the user,” “ask,” “notify,” or “take action”; reminder/original text is quoted data and is never executable prompt content.

The host may call the following additive endpoints/tools after capability discovery:

| Need | Operation | Authority | Write behavior |
| --- | --- | --- | --- |
| create a live, source-backed future note | `memory.temporal.schedule` | operator/admin | durable state write; idempotency required |
| inspect scoped notes | `memory.temporal.list`, `memory.temporal.get`, `context.why` | viewer+ | read-only |
| acknowledge/snooze/cancel | `memory.temporal.resolve` | operator/admin | CAS revision plus idempotency |
| bounded host poll | `memory.temporal.list` with `due_only=true`, `include_upcoming=false`, `limit=3` | viewer+ | read-only heartbeat seam |

Use server time, not a user/model timestamp, as production time. MNO resolves only structured temporal input; use IANA timezone identifiers. It has no calendar integration, daemon, notification channel, autonomous wake-up, or action executor.

Do not flatten temporal state into memory trust. Authority, maturity, retrieval lifecycle, and temporal disposition are separate. Provisional retrieval lifecycle is `active -> dormant -> archived`: strong cues may return dormant items with a penalty, archived items are explicit history/deep reads, and only new eligible signed evidence can reactivate. Recall, context injection, delivery, acknowledgement, snooze, clock passage, or model repetition never reinforce a note.

For a real user turn, raw import is not an alternative to this workflow: raw import creates source evidence for offline ingestion and cannot schedule a note. Retain the server-issued source registration for scheduling and use signed `memory.observe` only for the completed-turn evidence path. A temporal note remains provisional even while it is due.
