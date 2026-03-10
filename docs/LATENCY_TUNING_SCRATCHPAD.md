# Latency Tuning Scratchpad

## Goal
- Routine chat p95 under 4s.
- Memory-heavy p95 under 6-8s.
- No trust regression (false memory remains 0, citations remain intact).

## Baseline (real export run)
- Run: `runtime/live_runs/live_20260211_080915`
- Input: `/mnt/z/openAIdata/User Online Activity/conversations.json`
- Atom count: 10,025
- Signoff decision: `FAIL` (latency only)
- Eval p95: ~19.3s
- Load p95: ~18.3s
- Accuracy/citation/false-memory metrics: strong (`1.0 / 1.0 / 0.0`)

## Hypotheses
1. Per-turn retrieval recomputation is too expensive.
2. Conflict graph lookups are doing too many sqlite round-trips.
3. Canonical text tokenization + ngram extraction should not be rebuilt every turn.

## Experiment log

### 2026-02-11 - Iteration 1 (implemented)
- Change:
  - Added retrieval cache invalidation token support.
  - Added `conflict_map()` and `cache_token()` to memory stores.
  - Switched retriever to precompute token sets + ngrams per atom on cache refresh.
  - Switched graph relevance to use one preloaded conflict map instead of per-atom neighbor queries.
- Expected effect:
  - Major drop in per-turn retrieval CPU and sqlite calls.
- Status:
  - Implemented; benchmark rerun pending.

### 2026-02-11 - Iteration 1 resume (current)
- Validation plan:
  - Run focused unit tests covering retrieval + runtime load harness.
  - Re-run safe latency loops using real imported atoms.
  - Compare before/after p95 latency and verify trust metrics unchanged.
- Risk watch:
  - Cache staleness if invalidation token misses structural store changes.
  - Fallback path correctness for stores without bulk conflict map support.
- Status:
  - In progress.

### 2026-02-11 - Iteration 1A (failed run profile)
- Command shape:
  - Full-bias load harness against `.runtime/imports/atoms.sqlite3` with 12 turns and scan budget 600000.
- Observation:
  - CPU saturation stayed ~93-95% for >90s on a single process.
  - WSL stability risk remained high under this profile.
- Decision:
  - Abort and downshift benchmark profile to staged runs:
    1) low-budget smoke,
    2) medium budget,
    3) high budget only after stable evidence.

### 2026-02-11 - Iteration 1B (measured, still too slow)
- Artifacts:
  - `runtime/tmp/latency_iter1b_safe/load/load_summary.json`
  - `runtime/tmp/latency_iter1b_safe/eval/summary.json`
- Result:
  - load p95: `15784.68 ms`
  - eval p95: `16461.08 ms`
  - trust metrics remained perfect.
- Profiling finding:
  - Main bottleneck was continuity graph recomputation per turn (`ContinuityStore.arc_neighbors` rebuilding full maps each retrieval).

### 2026-02-11 - Iteration 2 (implemented + measured)
- Change set:
  - Added token-postings candidate scoring path in retriever.
  - Added snapshot-level continuity graph caching (`constellation_neighbors` + `arc_neighbors` + atom-id set).
  - Added retrieval/continuity prewarm at runtime init to remove cold-start penalty from first measured turn.
- Artifacts:
  - `runtime/tmp/latency_iter2_cached/load/load_summary.json`
  - `runtime/tmp/latency_iter2_cached/eval/summary.json`
- Result:
  - load p95: `4330.17 ms` (from `15784.68 ms`)
  - load avg: `3378.08 ms` (from `13291.00 ms`)
  - eval p95: `4566.10 ms` (from `16461.08 ms`)
  - eval avg: `3656.40 ms` (from `13450.53 ms`)
  - trust metrics: unchanged (`decision/citation/retrieval/abstain precision = 1.0`, `false_memory_rate = 0.0`)

### Remaining gap
- Routine-chat p95 target `< 4000 ms` is close but not yet met in harness (currently ~4.3-4.6s).
- Memory-heavy target `< 6000 ms` is met.

### 2026-02-11 - Iteration 2A (rejected)
- Attempt:
  - Tightened candidate envelope (`posting_cutoff` lower and `min_pool` lower) to force more aggressive pruning.
- Result:
  - Load p95 regressed to `4572.59 ms` (`runtime/tmp/latency_iter3_tight/load/load_summary.json`).
- Decision:
  - Reverted this tuning; retained Iteration 2 settings.

### Next iteration queue
1. Add route-aware retrieval budget for routine/light lane (smaller candidate/rerank envelope).
2. Preserve deep lane quality path for explicit memory recall.
3. Re-run signoff profile (`safe`) and verify gate outcome.

### 2026-02-11 - Iteration 3 (root-cause fix, accepted)
- Root cause:
  - Retriever cache token was accidentally shadowed inside `_get_cache()` while building token postings.
  - Effect: cache key became a random lexical token (for example, `"int"`) instead of the store token, forcing full cache rebuild every retrieval.
- Additional hardening:
  - Retrieval cache invalidation token now tracks structural changes only (atom/conflict/shared-language counts), not per-turn `updated_at` churn.
  - Added unit regression guard to ensure stable token reuses cache without a second `list_atoms()` rebuild.
- Artifacts:
  - `runtime/tmp/final_mile_baseline/eval/summary.json`
  - `runtime/tmp/final_mile_baseline/load/load_summary.json`
  - `runtime/tmp/final_mile_iter3/eval/summary.json`
  - `runtime/tmp/final_mile_iter3/load/load_summary.json`
- Result:
  - Before fix (baseline):
    - eval p95: `4568.60 ms`
    - load p95: `4895.21 ms`
  - After fix:
    - eval p95: `248.19 ms`
    - load p95: `214.07 ms`
  - Trust metrics remained perfect (`decision/citation/retrieval/abstain precision = 1.0`, `false_memory_rate = 0.0`).
- Decision:
  - Accept Iteration 3 as new latency baseline.
