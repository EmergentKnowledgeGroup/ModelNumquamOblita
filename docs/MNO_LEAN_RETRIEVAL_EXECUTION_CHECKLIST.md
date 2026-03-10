# MNO Lean Retrieval Execution Checklist

Derived from: `docs/MNO_LEAN_RETRIEVAL_UPGRADES_SPEC.md`  
Companion board: `docs/MNO_LEAN_RETRIEVAL_BLOCKERBOARD.md`  
Top-level goal: lean, bounded, verifiable retrieval upgrades without breaking the evidence-first trust contract  
Status: Active

## Current Execution State

- `P0`: historically landed in the source lineage carried into the standalone repo and re-verified by the focused standalone lean retrieval unit suite on 2026-03-10.
- `P1`: historically landed in the source lineage carried into the standalone repo and re-verified by the focused standalone lean retrieval unit suite on 2026-03-10.
- Standalone corpus re-verification was restored on 2026-03-10 after porting the missing eval-integrity slice from source commit `de0c732` (`PR C: harden signoff eval integrity`).
- Standalone `Phase 7` signoff now passes again on both reference corpora:
  - `runtime/evals/claude_no_phase7_signoff_20260310_standalone_reverify`
  - `runtime/evals/no_lyra_phase7_signoff_20260310_standalone_reverify`
- `evidence_precision@k` / `junk_rate@k` remain baseline-relative improvement metrics for closure work. Do not reinterpret them as ad hoc absolute floors when doing carried-forward parity verification.
- `P2`: optional and deferred until a measured gap justifies extra dependencies or latency cost.

## Global Execution Rules

- `P0` may touch only retrieval-core safe zones:
  - `engine/retrieval/*`
  - `engine/memory/*`
  - `engine/continuity/*`
  - `engine/write_gate/*` only if needed for safety regressions
  - `tests/unit/*`
  - `docs/*`
- `P0` must not add dependencies, new config knobs, shared runtime contracts, API fields, or tooling/readout changes.
- Router logic in `P0` runs only after the existing routine-chat skip and explicit-memory-request detection has already chosen to invoke LTM retrieval.
- Empty retrieval is acceptable. Empty retrieval must never force `PASS`.
- Conflict neighbors must be fetched before routing/type filters can exclude them.
- Cache keys must include store/continuity revision state plus retrieval-version salt.
- `P0` baseline freeze must record corpus ID, case count, owner, git commit, and timestamp before candidate changes.
- One blocker slice per PR. Do not hide unrelated refactors inside retrieval work.
- Any carried-forward completed item must be reopened if standalone verification or code audit disproves it.

## Global Done Rules

The program is not done unless all of these hold:

- `false_memory_rate == 0.0`
- `abstain_precision == 1.0`
- no memory claim passes without direct evidence in the delivered evidence pack
- contradiction handling is explicit or fail-closed
- cache uncertainty bypasses cache and runs fresh retrieval
- dual verdict is present for required gate runs
- per-case defect table is present for required gate runs
- all claimed improvements use numeric baseline comparisons, not qualitative wording

## P0: Retrieval-Core Safe Upgrades

Status: carried forward as closed from the historical implementation record; use this checklist to verify or reopen.

- [x] `MLRB-001` deterministic query-profile router
  - router shapes channel budgets only after existing LTM invocation
  - low-confidence or `mixed` routing falls back to the union of baseline channels
  - no new probabilistic threshold/config knob added in `P0`
- [x] `MLRB-002` bounded BM25 keyword channel
  - `canonical_text` indexing only in `P0`
  - no schema migration
  - any persistent index is droppable and rebuildable from existing atoms
- [x] `MLRB-003` RRF fusion contract
  - fixed internal RRF constant
  - empty channels ignored
  - deterministic tie-break order
  - no double-counting against existing weighted scoring
- [x] `MLRB-004` conflict coverage failsafe
  - fetch contradiction neighbors before filters
  - reserve coverage for up to 2 directly conflicting atoms by default
  - if missing from candidate list, assign deterministic conflict-rank below lowest non-conflict item
  - drop lowest non-conflict items first or fail closed
- [x] `MLRB-005` internal-only dropped-item reasons
  - stable reason codes
  - process-local only in `P0`
  - no raw text persistence to disk/logs
- [x] `MLRB-006` temporal decay safety
  - either ship concrete type-specific values backed by tests
  - or keep current values and defer retuning
  - multi-timeframe queries must not erase the older side
- [x] `MLRB-007` cache scoping and invalidation
  - scope includes user/store, revisions, profile, channels, critical thresholds, retrieval-version salt
  - cache parity is testable
  - rollback includes cache clear and index rebuild
- [x] `MLRB-008` regression negatives
  - recency injection
  - router misclassification fallback
  - conflict-neighbor pruning
  - derived-only evidence guard
  - cache parity and stale reuse
  - dedicated conflict-edge subset
  - multi-timeframe coverage
- [x] `MLRB-009` P0 release discipline
  - dual verdict required
  - per-case defect table required
  - frozen baseline reference required
  - numeric comparison required before any “green” language

P0 closes only when:

- `false_memory_rate == 0.0`
- `abstain_precision == 1.0`
- `retrieval_hit_rate` on the paraphrase-heavy supported subset improves by at least `+5pp`, unless already at ceiling
- `evidence_precision@k` improves by at least `+10pp` or `junk_rate@k` decreases by at least `20%` relative, unless baseline is already at ceiling/floor
- supported-case abstains caused by missed obvious support decrease by at least `25%` relative, unless baseline count is already `0`
- anti-gaming memory-claim coverage on the known-support subset does not drop below `baseline - 0.03`

## P1: Runtime / Tooling / Eval Integrity

Status: carried forward as closed from the historical implementation record; use this checklist to verify or reopen.

- [x] `MLRB-101` safe diagnostics surfacing
  - ids/scores/reasons only by default
  - raw text requires explicit opt-in plus redaction/retention rules
- [x] `MLRB-102` typed config/feature controls
  - defaults preserve `P0`
  - no silent drift from config expansion
- [x] `MLRB-103` internal override-query contract
  - disabled by default
  - cannot bypass routine-chat skip without explicit memory request signal
  - auditable invoker/reason/scope
- [x] `MLRB-104` eval integrity wiring
  - `evidence_precision@k`
  - `junk_rate@k`
  - `conflict_coverage`
  - anti-gaming coverage
  - fail-closed semantics for broad unrelated retrieval
- [x] `MLRB-105` human-quality reporting contract
  - dual verdict always emitted
  - defect count emitted
  - top failures emitted
  - baseline reference and thresholds printed

P1 closes only when:

- required eval/readout artifacts are emitted without missing fields
- default diagnostics stay redacted
- override path remains internal-only and default-off
- oneclick/readout gates fail when new integrity metrics or verdicts are missing

## P2: Optional Heavy Retrieval

Status: open only if measured gaps remain after `P0` and `P1`.

- [ ] `MLRB-201` optional embedding retrieval channel
  - strict top-k bounds
  - dependency/config work allowed only in this phase
  - re-embed migration plan required
- [ ] `MLRB-202` optional cross-encoder reranker
  - bounded top-N to top-M
  - no fanout increase
  - pinned model versions
- [ ] `MLRB-203` model-drift protection
  - offline replay checks
  - pinned-version drift gates
  - block unvalidated ranking drift

P2 closes only when:

- the measured retrieval gap justifies extra complexity
- heavy channels improve quality without safety regression
- p95 latency stays inside the agreed conversational budget

## Rollout / Backout Checklist

- [ ] freeze baseline before candidate work
- [ ] record thresholds used and observed values
- [ ] run targeted tests for touched surfaces
- [ ] run full suite: `python3 -m pytest -q`
- [ ] run required eval gate with dual verdict
- [ ] attach per-case defect table and top failures
- [ ] for cache/index changes, clear caches and rebuild droppable indexes on rollout
- [ ] if rollback is needed, revert slice, clear caches via retrieval-version salt, rebuild droppable index, rerun frozen baseline
