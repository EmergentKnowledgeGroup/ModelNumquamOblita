# MNO v0.2.2 Temporal Agency Blockerboard

**Board status:** RELEASE GREEN
**Spec status:** LOCKED
**Release status:** PUBLISHED AND PUBLICLY VERIFIED

Normative links: [locked spec](MNO_V0_2_2_TEMPORAL_AGENCY_SPEC_2026-07-18.md) · [execution checklist](MNO_V0_2_2_TEMPORAL_AGENCY_EXECUTION_CHECKLIST_2026-07-18.md)

| ID | Gate / owner | State | Detection evidence and exit condition | Fallback / backout |
|---|---|---|---|---|
| B-001 | DEV reconciliation / primary | CLEARED | DEV starts at public `190e056`; immutable tracked snapshot `f65fa8a1a315868378cc868b086a455779a416e2`; selected hashes unchanged; focused baseline green. | Restore reviewed tracked content from snapshot branch; preserve untracked DEV data. |
| B-002 | CLEAN untouched / primary | CLEARED | `Z:\numquamoblita-clean` clean at `190e056` / `v0.2.1`; recheck before staging. | Stop and discard only the uncommitted CLEAN staging delta if contamination appears. |
| B-003 | SpecSwarm decision completeness / primary + final QA | CLEARED | Final Sol xhigh reviewer PASSed half-open windows, attribution-only session semantics, durable replay/CAS, exact budgets, expansion/poll seams, full zero-drift projection, retention, and this board. | Reopen spec; implementation remains DEV-only. |
| B-004 | Schema v4 and migration / persistence slice owner | CLEARED | Fresh/v3/repeat/crash/WAL backup/restore/move, concurrency, retention, and restore coverage passed. | Disable v0.2.2 binary; restore verified pre-v4 backup with disclosed RPO. |
| B-005 | Clock/resolver/turn continuity / temporal-core owner | CLEARED | Timezone/DST/calendar/window/provenance/restart/anomaly tests passed; wheel installs packaged `tzdata` and `tzlocal`. | Keep current UTC clock only; temporal scheduling remains disabled. |
| B-006 | Operations/API/MCP / integration owner | CLEARED | Durable fail-closed, scope/auth/idempotency/CAS/quota/parity/context expansion tests passed. | Disable temporal operations/capability while preserving v4 data. |
| B-007 | Maintenance/retrieval/zero drift / runtime owner | CLEARED | Horizon/anchor/due/order/conflict/dormant/redelivery/read-purity and full projection tests passed. | Disable due injection and dormant fallback; preserve ordinary v0.2.1 retrieval. |
| B-008 | Lean neutral context / runtime owner | CLEARED | Neutral `agent_context_v2`, inclusive budgets, UTF-8 bounds, whole-item drops, and expansion operations passed. | Disable agent-context rendering; structured API facts remain available. |
| B-009 | Security/privacy/report / security QA owner | CLEARED | Scoped persistence, receipt, redacted report, backup, secret scan, and quoted-memory-data tests passed. | Disable report additions/temporal writes and retain sanitized diagnostics only. |
| B-010 | Docs and flowcharts / documentation owner | CLEARED | Canonical/public/LLM docs, draw.io source, strict architecture export, clean export, schema, and blind-agent checks passed. | Do not stage or publish until sources and exports agree. |
| B-011 | Full DEV QA/package / release owner | CLEARED | Release slice passed 289 tests plus desktop 63/63; wheel/sdist and isolated install verified. Unrelated dirty experiments were excluded. | Keep CLEAN untouched and release v0.2.1 current. |
| B-012 | CLEAN staging equivalence / release owner | CLEARED | Exact 66-file ledger byte-matched DEV to CLEAN; full CLEAN Python suite, desktop 63/63, strict visuals, diff scope, and scans passed. | Remove only staged v0.2.2 delta from CLEAN and restage from ledger. |
| B-013 | PR review and CI / release owner | CLEARED | PR #14 passed the complete Python 3.12-3.14 Linux/macOS/Windows matrix, all desktop jobs, artifact proof, CodeRabbit re-review, and all actionable threads before merge. | Leave PR open or close without merge; no tag/release. |
| B-014 | Merge/tag/release/public smoke / release owner | CLEARED | PR #14 merged/closed at `1fc1a4a`; annotated `v0.2.2` and the public GitHub release include CI-built wheel/sdist/checksums. Fresh tag clone and public-wheel install passed CLI/import plus durable-store proof: advertised temporal capabilities, server-clock facts, source-backed schedule/list/get/resolve, and two bounded heartbeat polls (`due_only=true`, `include_upcoming=false`, `limit=3`) that left revision 1 unchanged before explicit cancel advanced it to revision 2. Post-release checkpoint: `runtime/checkpoints/context_checkpoint_20260718T232236Z_checkpoint.md`. | If already merged, publish a corrective patch or withdraw broken artifacts; never rewrite public history. |

## Scope ledger rules

- DEV is the only implementation SSoT.
- CLEAN remains untouched until B-004 through B-011 are cleared.
- Stage an explicit file ledger only; never copy the DEV tree wholesale.
- Exclude runtime databases, WAL/SHM, checkpoints, logs, temporary files, secrets, personal data, and unreviewed DEV artifacts.
- Preserve unrelated DEV changes, including the existing shell portability fix, unless independently reviewed into this release.

## Release stop conditions

Stop publication and reopen the relevant blocker if any test shows canonical mutation, read-time writes, self-reinforcement, cross-scope leakage, fabricated time, unbounded context, reminder text acting as instructions, silent downgrade loss, or background/unsolicited action.
