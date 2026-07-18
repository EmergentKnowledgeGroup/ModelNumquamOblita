# MNO v0.2.2 Temporal Agency Execution Checklist

**Spec:** `docs/MNO_V0_2_2_TEMPORAL_AGENCY_SPEC_2026-07-18.md` (LOCKED)
**Initial status:** all implementation items PENDING

## A. Baseline and contract

- [x] Record reconciled DEV/CLEAN heads, tracked-snapshot branch, and reviewed release ledger.
- [x] Add failing contract tests for neutral context, exact budgets, clock provenance, and capabilities.
- [x] Add failing timezone/resolver tests for UTC fallback, IANA, DST gap/fold, elapsed/calendar offsets, month-end, leap day, and ambiguity errors.
- [x] Add half-open exact/date/approximate/snooze window boundary tests.

## B. Persistence and migration

- [x] Upgrade provisional schema v3 -> v4 transactionally and repeat-safely.
- [x] Add scoped temporal fields, revision, state-event, turn-clock, delivery-event, and durable idempotency storage.
- [x] Prove idempotency namespace, same-payload replay-before-CAS, conflicting payload rejection, atomic commit, and retention.
- [x] Add indexes for scoped due reads and bounded turn/delivery history.
- [x] Prove fresh v4, v3 migration, rollback injection, live WAL backup, restore/reopen, and moved-workspace behavior.
- [x] Prove safety checks cover every new persistence surface.

## C. Runtime temporal core

- [x] Add injectable server clock and IANA timezone resolver with packaged `tzdata`.
- [x] Implement strict structured temporal resolution and safe reason codes.
- [x] Record built-in receipt/completion and external callback receipt events without content.
- [x] Build `mno.temporal-context.v1` with honest unavailable/anomaly states.
- [x] Replace imperative `agent_context` prose with neutral `agent_context_v2` facts.
- [x] Enforce 2,800-token default / 4,096-token hard total context cap and 192/256 temporal cap using whole-section truncation.

## D. Temporal memory operations

- [x] Implement scoped `schedule`, `list`, `get`, and `resolve` operations.
- [x] Fail temporal writes closed with `TEMPORAL_DURABLE_STORE_REQUIRED` on non-SQLite runtimes.
- [x] Enforce permissions, quotas, horizon, idempotency, revision/CAS, and terminal-state rules.
- [x] Add scoped `context.why` expansion for temporal opaque IDs and cross-scope not-found tests.
- [x] Add HTTP/MCP parity and capability discovery.
- [x] Keep raw import incapable of scheduling; add structured live-writeback coverage.

## E. Maintenance and retrieval

- [x] Protect pending temporal records through due-window end plus grace.
- [x] Age from the effective post-protection anchor without support/maturity drift.
- [x] Select due records independently of lexical routing using separate bounds.
- [x] Pin canonical conflicts above due provisional notes.
- [x] Add penalized, cue-aware dormant fallback; keep archived content explicit-only.
- [x] Add signed delivery IDs and exact-once observation telemetry without context writes.
- [x] Snapshot the complete truth/evidence projection and prove it unchanged across reads, rendering, polls, repeated delivery, and delivery callbacks.
- [x] Add read-only heartbeat poll seam with no daemon/thread/network behavior.
- [x] Prove due ordering, exact/claim-key canonical association, and observed-delivery redelivery suppression.

## F. Integration and reporting

- [x] Extend `mno-report` with redacted temporal policy/schema/count/reason diagnostics only.
- [x] Update integration bundle, HTTP examples, MCP examples, compatibility fallbacks, and blind-agent fixtures.
- [x] Prove generic clients need no Lux/Hermes/Claude-specific executable.

## G. Documentation and visuals

- [x] Update root README, LLMS, QUICKSTART, CONFIGURATION, SECURITY, TROUBLESHOOTING, API, MCP, AGENT_INTEGRATION, COMPATIBILITY, DISTRIBUTION, packaged QUICKSTART, and public docs.
- [x] Add direct LLM-facing temporal operation/mental-model section.
- [x] Correct v0.2.1 lifecycle documentation (`active -> dormant -> archived`, cue fallback, evidence-only reactivation).
- [x] Update canonical `.drawio` sources, visual specs/indexes, public/engineering generators, and PNG/SVG exports.
- [x] Run structural, source/export, link, schema, example, and blind-LLM checks.

## H. Verification and release

- [x] Run targeted TDD suites after every slice.
- [x] Run full release-scope Python, integration, security, migration, report, blind-LLM, performance, desktop, and packaging suites in DEV; preserve and exclude unrelated dirty experimental lanes.
- [x] Run supported Python 3.12-3.14 and timezone portability gates where locally available; rely on required CI matrix for supported OS proof.
- [x] Build wheel/sdist, install in isolated environment, and run temporal smoke.
- [x] Audit DEV diff scope and produce explicit reviewed-file ledger.
- [x] Checkpoint post-green DEV.
- [x] Stage only reviewed files into CLEAN and prove content equivalence.
- [x] Run full CLEAN gates and secret/runtime-data scan.
- [ ] Commit/push `codex/v0.2.2-temporal-agency`, open ready PR, and checkpoint PR-open.
- [ ] Run `pr-review-ci-loop`; resolve all actionable review/CI findings.
- [ ] Merge and close PR, tag `v0.2.2`, publish release notes/artifacts/checksums, and checkpoint post-merge.
- [ ] Verify public repo/release and fresh-clone install/smoke.
- [ ] Mark goal complete only after every required release surface is green.
