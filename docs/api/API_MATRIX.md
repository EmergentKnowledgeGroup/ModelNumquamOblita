# API Matrix

## Primary public orchestration

- `integration-v1`

## Primary agent tool surface

- MCP parity tools over stdio or HTTP

## Runtime context helper surface

- WSS `work_session_context` in strict project/thread/workstream scoped v2 context packages
- `mno.agent_context.v2` neutral facts contract, including optional `mno.temporal-context.v1`

WSS uses trust tier `scratchpad_ephemeral`. It is work-continuity helper state, not retrieval evidence, reviewed truth, or a writeback path.

## Lean packet and draft surfaces

| Surface | Contract | Authority/write behavior |
| --- | --- | --- |
| HTTP `POST /api/integration/v1/context/build`, MCP `integration.context.build` | Optional v2 `answer_claims`; full `service_verdict`, compact `agent_context.verification`, bounded canonical `related_text` | Existing read-only context path; unverified answers abstain |
| MCP `integration.learning.propose` | Existing source IDs → `context.why` → `writeback.propose`; `lesson`/`summary` host-authored draft | Operator/admin plus mutations enabled; pending human review only; no new HTTP endpoint |
| MCP `explore.anchor_brief`, runtime anchor briefs, wake-up-pack anchor briefs | Source-selection `summary_kind`, selected-row `summary_support`, source reference first | Existing inspection path; aggregate confidence preserved; no generation or promotion |

`retrieved_evidence` verification does not certify a proposed answer. The additions introduce no model, runtime dependency, migration, or automatic host hook. The HCR tool allowlist is unchanged. See [API](../API.md#answer-claims-and-verification) and [MCP](../MCP_INTEGRATION.md#source-linked-learning-drafts).

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
