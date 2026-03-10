# MNO Lean Retrieval Upgrade Blockerboard

Status: Locked after second SpecSwarm + author QA  
Updated: 2026-03-10  
Spec source: `docs/MNO_LEAN_RETRIEVAL_UPGRADES_SPEC.md`  
Execution source: `docs/MNO_LEAN_RETRIEVAL_EXECUTION_CHECKLIST.md`

## Purpose

Track the concrete blockers required to ship lean retrieval upgrades without breaking MNO's evidence-first trust contract.

Done is not “retrieval looks better.” Done is:

- `safety_verdict=PASS`
- `human_quality_verdict=PASS`
- `false_memory_rate=0.0`
- `abstain_precision=1.0`
- numeric improvement against a frozen baseline
- no high-severity human-readout defects
- latency still inside conversational budget

## Current State

- `MLRB-001..009`: carried forward as closed from the historical implementation record and re-verified by the focused standalone lean retrieval unit suite on 2026-03-10
- `MLRB-101..105`: carried forward as closed from the historical implementation record and re-verified by the focused standalone lean retrieval unit suite on 2026-03-10
- Standalone corpus parity was restored on 2026-03-10 by porting the missing eval-integrity slice from source commit `de0c732` (`PR C: harden signoff eval integrity`).
- `Phase 7` signoff re-verification now passes on both reference corpora:
  - `runtime/evals/claude_no_phase7_signoff_20260310_standalone_reverify`
  - `runtime/evals/no_lyra_phase7_signoff_20260310_standalone_reverify`
- `MLRB-201..203`: optional and still open

If standalone verification disproves any carried-forward closed item, reopen it immediately.

## Non-Negotiable Constraints

- `P0` may touch only:
  - `engine/retrieval/*`
  - `engine/memory/*`
  - `engine/continuity/*`
  - `engine/write_gate/*` only if needed for safety regressions
  - `tests/unit/*`
  - `docs/*`
- `P0` must not add dependencies, new config knobs, shared contracts, API fields, or tooling/readout changes.
- Router logic in `P0` runs only after the existing routine-chat skip and explicit-memory-request gating has already chosen to invoke LTM retrieval.
- Empty retrieval results are valid and must never force `PASS`.
- Conflict neighbors must be fetched before routing/type filters can exclude them.
- BM25 in `P0` must remain dependency-free and must not require schema migration.
- `P0` diagnostics must stay process-local, non-persistent, and redacted.
- Cache uncertainty bypasses cache and runs fresh retrieval.
- Never declare success without both verdicts and the required defect table.

## Must-Hit Metrics

| Metric | Rule |
| --- | --- |
| `false_memory_rate` | `== 0.0` |
| `abstain_precision` | `== 1.0` |
| `routine_over_recall_rate` | `== 0.0` |
| `conflict_coverage` | `== 1.0` on the dedicated conflict-edge subset |
| `retrieval_hit_rate` | paraphrase-heavy supported subset improves by `>= +5pp`, unless already at ceiling |
| `evidence_precision@k` / `junk_rate@k` | `precision >= +10pp` or `junk_rate <= -20% relative`, unless already at ceiling/floor |
| `supported-case abstains caused by missed obvious support` | `>= 25%` relative reduction, unless already `0` |
| `anti_gaming_memory_claim_coverage` | known-support subset must stay `>= baseline - 0.03` |
| `fanout_max` | fused candidates stay `<= rerank_limit` |
| `latency_budget` | `p50` and `p95` within agreed conversational budget and not beyond approved baseline delta |

## Baseline Discipline

Every gate run must record:

- `run_id`
- corpus/dataset ID
- case count
- owner
- git commit
- timestamp
- baseline reference
- thresholds used
- observed values

Do not use “hold,” “improve,” or “green” language without numeric comparison against the frozen baseline.

For carried-forward parity checks, do not reinterpret baseline-relative retrieval-improvement metrics (`retrieval_hit_rate`, `evidence_precision@k`, `junk_rate@k`, missed-support abstains) as standalone absolute floors. Use them for candidate-vs-frozen-baseline comparisons, not for ad hoc parity smoke runs.

## P0 Blockers

| ID | Priority | Blocker | Lean Fix Scope | Allowed Touchpoints | Strict Exit Gate | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `MLRB-001` | `P0` | Query-profile router must stay deterministic and safe | Router shapes budgets/channels only after existing LTM invocation and falls back safely on low confidence | `engine/retrieval/*`, `tests/unit/test_retrieval_engine.py`, `tests/unit/test_retrieval_shared_language.py` | Profile tests prove fallback union behavior, no empty-pack coercion, and no runtime gate expansion | Closed (carried forward) |
| `MLRB-002` | `P0` | BM25 channel must stay lean and schema-safe | In-process BM25 over `canonical_text` only in `P0`, with stopword/high-DF control and relevance floor | `engine/retrieval/*`, `engine/memory/*`, `tests/unit/test_retrieval_engine.py`, `tests/unit/test_sqlite_atom_store.py` | Rare-keyword rescue passes; stopword-noise stays bounded; no schema migration or persistent-index incompatibility | Closed (carried forward) |
| `MLRB-003` | `P0` | Fusion must be deterministic and bounded | RRF over ranked channel outputs with empty-channel ignore and no double-counting | `engine/retrieval/*`, `tests/unit/test_retrieval_engine.py`, `tests/unit/test_retrieval_shared_language.py` | Deterministic tie-break passes; channel-rescue tests pass; no extra config knobs introduced | Closed (carried forward) |
| `MLRB-004` | `P0` | Conflict coverage must never be pruned away | Fetch conflict neighbors before filters; reserve coverage for up to two direct contradictions; fail closed if coverage cannot fit | `engine/retrieval/engine.py`, `engine/retrieval/verifier.py`, `tests/unit/test_claim_verifier.py` | One-sided contradiction packs cannot `PASS`; missing neighbor gets deterministic conflict-rank or verdict fails closed | Closed (carried forward) |
| `MLRB-005` | `P0` | Dropped-item reasons must remain internal and safe | Stable internal reason codes without runtime payload changes or text persistence | `engine/retrieval/*`, `tests/unit/test_retrieval_engine.py` | Stable reason-code coverage passes; raw text never lands in logs/artifacts in `P0` | Closed (carried forward) |
| `MLRB-006` | `P0` | Temporal policy must not erase correct older evidence | Type-specific decay only if concrete values are justified; otherwise keep current values and defer retuning | `engine/memory/store.py`, `engine/memory/sqlite_store.py`, `engine/continuity/*`, `tests/unit/test_memory_store.py`, `tests/unit/test_consolidator.py` | Time-intent and multi-timeframe tests pass; older but relevant evidence remains retrievable | Closed (carried forward) |
| `MLRB-007` | `P0` | Cache scoping and rollback safety must be explicit | Cache key includes scope, revisions, profile, channels, thresholds, and retrieval-version salt | `engine/retrieval/engine.py`, `engine/memory/*`, `engine/continuity/store.py`, `tests/unit/test_sqlite_atom_store.py`, `tests/unit/test_retrieval_engine.py` | Cache parity passes; stale reuse blocked; rollback procedure clears caches and rebuilds droppable index | Closed (carried forward) |
| `MLRB-008` | `P0` | Regression suite must catch safe-routing failures | Negative coverage for recency injection, router fallback, conflict pruning, derived-only evidence, cache parity, conflict subset, multi-timeframe cases | `tests/unit/test_retrieval_engine.py`, `tests/unit/test_claim_verifier.py`, `tests/unit/test_retrieval_shared_language.py` | New negatives fail on bad patterns and pass on fixed behavior | Closed (carried forward) |
| `MLRB-009` | `P0` | P0 success language must be numerically and procedurally gated | Dual verdict, defect table, frozen baseline reference, and numeric comparisons are mandatory before any success claim | `docs/*` | Every required P0 run summary includes both verdicts, defect table, thresholds, observed values, owner, commit, and baseline reference | Closed (carried forward) |

## P1 Blockers

| ID | Priority | Blocker | Lean Fix Scope | Touchpoints | Strict Exit Gate | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `MLRB-101` | `P1` | Diagnostics must be auditable without leaking raw text | Safe diagnostics in runtime/readout paths with redaction by default | `engine/runtime/*`, `tools/*`, `engine/contracts.py` | Readouts show selected/dropped evidence audit and reason summaries while defaulting to ids/scores/reasons only | Closed (carried forward) |
| `MLRB-102` | `P1` | New retrieval behavior needs typed runtime/config control | Add typed flags/thresholds once `P0` defaults are proven | `engine/config.py`, `engine/runtime/*`, tests | Config-load tests pass and defaults preserve `P0` behavior | Closed (carried forward) |
| `MLRB-103` | `P1` | Override-query path must stay internal-only | Internal debug/eval override with strict guardrails and trace audit | `engine/runtime/*`, `tools/*`, tests | Disabled by default, explicit auth context required, cannot bypass routine-chat skip without explicit memory request | Closed (carried forward) |
| `MLRB-104` | `P1` | Eval integrity metrics must be wired into gates | Add gate enforcement for `evidence_precision@k`, `junk_rate@k`, `conflict_coverage`, anti-gaming coverage | `tools/*`, `engine/runtime/live_eval.py`, tests | Oneclick fails on broad unrelated retrieval even if safety-only metrics still look green | Closed (carried forward) |
| `MLRB-105` | `P1` | Human-quality reporting must be non-optional | Dual verdict, defect count, top failures, and baseline reference must always emit | `tools/build_responder_eval_readout.py`, `tools/run_oneclick_eval.py`, tests | Missing fields or missing top failures automatically fail the gate | Closed (carried forward) |

## P2 Blockers

| ID | Priority | Blocker | Lean Fix Scope | Touchpoints | Strict Exit Gate | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `MLRB-201` | `P2` | No embedding channel for paraphrase-heavy misses | Optional embedding retrieval with strict bounds and migration plan | `engine/retrieval/*`, `pyproject.toml`, `engine/config.py`, tests | Quality improves on justified gap without safety regression or fanout growth | Open |
| `MLRB-202` | `P2` | No cross-encoder reranker for final precision | Optional post-fusion reranker with bounded top-N to top-M path | `engine/retrieval/*`, `engine/config.py`, tests | Precision rises with bounded p95 latency and no candidate expansion | Open |
| `MLRB-203` | `P2` | No heavy-channel drift gate | Pinned-version drift gates plus offline replay checks | `tools/*`, `engine/runtime/live_eval.py`, tests | Version bump is blocked until replay proves no unvalidated ranking drift | Open |

## Regression Gate Matrix

Every blocker closure PR must pass:

- targeted tests for the touched retrieval/memory/continuity/verifier paths
- full suite: `python3 -m pytest -q`
- required eval/readout gate for the phase
- dual-verdict signoff
- explicit negative tests for:
  - router misclassification fallback
  - recency-injection suppression
  - conflict-neighbor pruning under budget pressure
  - derived-only evidence guard
  - cache parity and stale reuse
- if applicable, dedicated conflict-edge subset and known-support anti-gaming coverage

## Pragmatic Execution Sequence

1. Keep `P0` and `P1` carried forward as closed unless standalone verification reopens them.
2. If any carried-forward item fails standalone verification, reopen only that blocker and fix it in a small slice.
3. Treat `P2` as optional until a measured gap proves it is worth the complexity.
4. Do not start heavy retrieval work before confirming the lighter stack is still passing the stricter gates above.

## Stop-Ship Conditions

- any increase in unsupported memory claims
- any PASS language with only one verdict passing
- any run missing `human_quality_verdict` or the per-case defect table
- any one-sided contradiction handling that still returns `PASS`
- any broad retrieval pattern that inflates junk rate and still passes alignment
- any default-on diagnostics mode that emits raw memory or raw user text
- any cache uncertainty path that still allows cached evidence to justify `PASS`
