# API Matrix

## Primary public orchestration

- `integration-v1`

## Primary agent tool surface

- MCP parity tools over stdio or HTTP

## Native automatic host layers

- Hermes Agent v0.19.0 `mno-memory` plugin
- OpenClaw plugin API `2026.8.1+` `mno-openclaw-memory` plugin

Both use bounded `context.build` before eligible host turns and one
post-success provisional `memory.observe` attempt. Their dedicated credentials
have no review or canonical-memory authority.

## Runtime context helper surface

- WSS `work_session_context` in strict project/thread/workstream scoped v2 context packages
- `mno.agent_context.v2` neutral facts contract, including optional `mno.temporal-context.v1`

WSS uses trust tier `scratchpad_ephemeral`. It is work-continuity helper state, not retrieval evidence, reviewed truth, or a writeback path.

## Temporal operations

- `memory.temporal.schedule` — operator/admin, source-backed structured live schedule, idempotency required
- `memory.temporal.list` / `memory.temporal.get` — viewer-readable scoped inspection, read-only
- `memory.temporal.resolve` — operator/admin acknowledge/snooze/cancel with revision and idempotency

`capabilities.get` advertises `temporal_context_v1`, `temporal_memory_v1`, and `temporal_due_poll`. The optional heartbeat is the bounded read-only list call with `due_only=true`, `include_upcoming=false`, and `limit=3`; it is not a scheduler, daemon, notification, or action path.

## Internal/operator surfaces

- native `/api/memory/*`
- native `/api/wizard/*`
- HCR `GET /curate/<run_id>` and `GET /api/wizard/hcr/status?run_id=...` — loopback operator handoff over the existing wizard truth state
- runtime diagnostics and packaging helpers

The model-facing HCR MCP profile is bound to one wizard run and allowlists only the eight `wizard.draft_curation_*` read/lease/proposal tools. Human promotion, direct review, publish, verify, activate, installation, force-release, and unrelated runtime tools are excluded.
