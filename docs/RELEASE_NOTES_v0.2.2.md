# MNO v0.2.2 Release Notes

**Released:** v0.2.2 on 2026-07-18 after PR #14, CI, review, tag, artifact verification, and fresh public install/smoke gates passed.

## Human changelog

- MNO can now provide honest server-clock facts and small, source-backed provisional future notes.
- Future notes can be scheduled, listed, inspected, acknowledged, snoozed, or cancelled through matching HTTP and MCP operations.
- MNO is still not a calendar, scheduler, daemon, notification service, model wake-up service, or action executor.
- Memory trust is clearer: authority, support/maturity, recall lifecycle, and temporal state are four separate labels.
- Provisional availability now has the documented lifecycle `active -> dormant -> archived`. Seeing or repeating a memory does not make it stronger; only new eligible signed evidence can.
- Due notes are deterministic and visibly provisional. Canonical corrections remain first; dormant fallback stays lower priority and cue-gated.

## What an agent receives

The new `agent_context_v2` temporal section is a bounded neutral fact envelope. It can report server UTC/local time, timezone source, prior-turn provenance, due/upcoming facts, and opaque expansion IDs. MNO supplies facts only: it does not put behavioral instructions in the envelope, infer feelings, or tell the consuming model to notify, ask, or act.

## Operations and safety

The additive temporal operations are `memory.temporal.schedule`, `memory.temporal.list`, `memory.temporal.get`, and `memory.temporal.resolve`. Scheduling requires a durable provisional SQLite store, source-backed live structured input, authenticated operator/admin scope, and an idempotency key. Resolution additionally uses the current revision. Raw import remains evidence ingestion and cannot schedule temporal notes.

The optional heartbeat seam is `memory.temporal.list` with `due_only=true`, `include_upcoming=false`, and `limit=3`. It is a bounded read-only poll. It never retains a process, wakes a model, creates a background worker, sends a notification, or executes an action.

## Compatibility and migration

Capabilities advertise `temporal_context_v1`, `temporal_memory_v1`, `temporal_due_poll`, and `agent_context_v2`. Clock facts remain available when temporal-memory features are disabled; writes fail closed when durable storage is absent. Temporal data is part of provisional schema v4 and uses the normal atomic memory-family backup. Downgrading a binary requires an operator-approved restore of the pre-v4 backup, with the disclosed loss of newer writes.

## Documentation and visuals

- [LLM contract](../LLMS.md)
- [API reference](API.md#temporal-context-and-operations)
- [MCP integration](MCP_INTEGRATION.md#temporal-tools)
- [Agent integration](AGENT_INTEGRATION.md#temporal-agent-contract)
- [Temporal visual specification](visuals/MNO_V0_2_2_TEMPORAL_AGENCY_VISUAL_SPEC_2026-07-18.md)
- [Temporal flowchart](visuals/exports/MNO_V0_2_2_TEMPORAL_AGENCY_2026-07-18__p01_temporal-agency-contract.svg)
