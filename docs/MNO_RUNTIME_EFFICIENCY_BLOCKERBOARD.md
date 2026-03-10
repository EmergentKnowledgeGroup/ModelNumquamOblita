# MNO Runtime Efficiency Blockerboard

Status: Draft (SpecSwarm-reviewed)
Updated: 2026-03-05
Standalone note: cleaned for the standalone MNO repo on 2026-03-10. Mixed-repo freeze language is historical only and no longer governs this lane.
Source spec: `docs/MNO_RUNTIME_EFFICIENCY_SPEC.md`
Related quality tracker: `docs/MNO_LEAN_RETRIEVAL_BLOCKERBOARD.md`
Usage contract: every phase/task decision must reference both this blockerboard and the source spec.

## Purpose

Track concrete blockers to improve latency/token efficiency without weakening MNO trust/safety quality.

Done is not “faster once.” Done is:
- phase efficiency gate passes (median of 3),
- dual verdict passes,
- integrity metrics do not regress,
- required readout artifacts exist,
- CodeRabbit gate reaches `actionable=0`.

## Non-Negotiable Rules

- No PASS/green unless both verdicts pass:
  - `safety_verdict=PASS`
  - `human_quality_verdict=PASS`
- `false_memory_rate == 0.0`
- `abstain_precision == 1.0`
- Token/latency gains cannot be claimed from unstable runs (variance > 10% is fail).
- Missing/non-finite required metrics are automatic fail.
- Token budget breach is automatic stop-ship.
- Any future standalone-boundary waiver must be logged explicitly with blocker link + waiver note.

## Status Semantics

- `FROZEN DUE TO ...` means a surface is intentionally outside the standalone MNO lane and requires a separate scope decision.
- `BLOCKED DUE TO ...` means work is not complete because a gate/dependency is failing, but surfaces are still editable.
- `Closed (...)` means implementation + required gate workflow are complete.

## Standalone Boundary and Allowlisted Surfaces

Removed document-research/add-on surfaces are excluded from this standalone repo by construction.

Default allowlist:
- `engine/retrieval/*`
- `engine/memory/*`
- `engine/continuity/*`
- `tests/unit/*`
- `docs/*`

Conditional unfreeze zones (P1/P2 only, exact-file approval required):
- `engine/runtime/live_eval.py`
- `tools/run_responder_eval.py`
- `tools/run_oneclick_eval.py`
- `tools/build_responder_eval_readout.py`
- matching unit tests

## Metric and Artifact Contract

Required metrics:
- `latency_p50_ms`
- `latency_p95_ms`
- `tokens_prompt_avg`
- `tokens_completion_avg`
- `tokens_total_avg`
- `retrieval_fanout_avg`
- `retrieval_fanout_p95`
- `safety_verdict`
- `human_quality_verdict`
- `false_memory_rate`
- `abstain_precision`
- `evidence_precision_at_k`
- `junk_rate_at_k`
- `conflict_coverage`

Required artifacts:
- baseline declaration fields (`baseline_commit`, `baseline_run_ids`, dataset ID, cache mode, env/concurrency notes),
- per-run metrics for 3 repeated runs,
- per-case readout with:
  - `## Verdict Summary`
  - `## Q/A Audit Table`
  - `## Top Failure Examples`
- P0 report contract declaration fields from `docs/MNO_RUNTIME_EFFICIENCY_P0_REPORTING_CONTRACT.md` (`breach_declaration`, `waiver_declaration`, `final_status`),
- CodeRabbit gate evidence (`tools/pr_feedback_gate.py` output with `actionable=0`).

## Phase and Blockers

## P0 (Allowlist-Only Internal Efficiency)

| ID | Priority | Blocker | Lean Fix Scope | Touchpoints | Exit Gate | Status |
|---|---|---|---|---|---|---|
| MREB-000 | P0 | Preflight: baseline protocol not fully recorded for this program | Create baseline declaration + 3-run median artifact bundle | `docs/*` | Baseline declaration complete and linked in board entry | Closed (2026-03-05) |
| MREB-001 | P0 | Retrieval fanout waste inflates latency/tokens | Tighten query-conditioned relevance admission and bounded candidate sets | `engine/retrieval/*`, `tests/unit/test_retrieval_engine.py` | Path A or B efficiency pass; fanout p95 <= baseline +5% | Closed (2026-03-05): corpus-aligned P0 closeout completed under mock-provider non-regression lane (`docs/evals/MNO_RUNTIME_EFFICIENCY_P0_CLOSEOUT_20260305.md`). Fanout bound held (`retrieval_fanout_p95=20.0` baseline/candidate median), dual verdict PASS across all repeated runs. |
| MREB-002 | P0 | Early-stop behavior may cut needed evidence if not guarded | Add required coverage checks before early-stop trigger | `engine/retrieval/*`, `engine/retrieval/verifier.py`, tests | Quality/integrity metrics no-regression tolerance satisfied | Closed (2026-03-05): guarded early-stop coverage (`_guarded_candidate_ids`) plus corpus-aligned 3-run protocol now pass strict quality/integrity gates (`relevance_aligned_hit_rate=1.0`, `abstain_precision=1.0`, `false_memory_rate=0.0`) with dual-verdict PASS in baseline and candidate lanes. |
| MREB-003 | P0 | Duplicate/low-value context drives token waste | Exact-dedupe + bounded context packing with deterministic rules | `engine/retrieval/*`, tests | `tokens_total_avg` improvement path and dual-verdict pass | Closed (2026-03-05): dedupe/packing regression suite remains green and corpus-aligned closeout confirms no quality regressions, no defect cases, and bounded fanout (`avg/p95=20.0`) under repeated dual-verdict PASS runs. |
| MREB-004 | P0 | Cache reuse can be stale/wrong without strict scoping | Enforce strict invalidation key dimensions + uncertainty bypass | `engine/retrieval/*`, `engine/memory/*`, `engine/continuity/*`, tests | Cache parity + invalidation tests green; no stale cross-scope reuse | Closed (2026-03-05): strict cache-token scoping kept intact and first-turn cache-rebuild latency spike was removed by continuity-aware prewarm (runtime/session + retriever). Corpus-aligned candidate median stayed within mock-lane non-regression guard (`latency_p95 +2.24%`, `latency_p50 +0.78%`). |
| MREB-005 | P0 | P0 gate reporting can be misread without explicit stop-ship semantics | Enforce fail-closed reporting language for breaches/waivers | `docs/*` | Every P0 run summary includes breach/waiver declarations | Closed (2026-03-05): added `docs/MNO_RUNTIME_EFFICIENCY_P0_REPORTING_CONTRACT.md`, wired spec/reporting references, and codified `breach_declaration` + `waiver_declaration` + `final_status` as mandatory run-summary fields. |

## P1 (Runtime/Eval Efficiency, Minimal Unfreeze)

| ID | Priority | Blocker | Lean Fix Scope | Touchpoints | Exit Gate | Status |
|---|---|---|---|---|---|---|
| MREB-101 | P1 | Efficiency metric emission may be incomplete on runtime/eval path | Ensure all required metrics emit from live-eval summary and are finite-validated | `engine/runtime/live_eval.py`, `tests/unit/test_live_eval.py` | Missing/non-finite metrics fail run; required metrics present | Closed (2026-03-05): added explicit required metric fields (`latency_p50_ms`, `latency_p95_ms`, token averages, retrieval fanout averages) in live-eval summaries plus finite-contract validation (`validate_live_eval_required_metrics`) and gate-side enforcement in responder/oneclick. |
| MREB-102 | P1 | Oneclick/responder gates may allow asymmetric regressions | Enforce median-of-3 and non-led metric regression bound (+3% max) | `tools/run_responder_eval.py`, `tools/run_oneclick_eval.py`, tests | P1 gate blocks large non-led regressions | Closed (2026-03-05): oneclick now enforces median-of-3 regression checks when `--efficiency-led-surface` is enabled and blocks non-led regressions beyond `--max-non-led-regression-pct` (default `3.0`). Unit coverage added for median-of-3 and non-led failure cases. |
| MREB-103 | P1 | Human readout contract can be incomplete | Enforce required readout sections and top-failure emission | `tools/build_responder_eval_readout.py`, `tools/run_oneclick_eval.py`, tests | Required sections always present before PASS | Closed (2026-03-05): contract enforcement already active; verified by unit tests and oneclick smoke run (`runtime/evals/mreb101_102_104_smoke_20260305_075956`) with required sections present. |
| MREB-104 | P1 | Frozen-surface exceptions may bypass traceability | Standardize `FROZEN DUE TO` waiver output in summaries/artifacts | `tools/run_oneclick_eval.py`, docs/tests | Waiver notes always include blocker link and scope | Closed (2026-03-05): added standardized `--frozen-waiver reason\|blocker_ref\|scope` parsing and artifact emission (`waivers.frozen_surface[]` with `classification=FROZEN DUE TO ...`, blocker ref, scope). Contract validated in gate payload + unit tests + oneclick smoke artifact. |

## P2 (Config-First Optimization Controls)

| ID | Priority | Blocker | Lean Fix Scope | Touchpoints | Exit Gate | Status |
|---|---|---|---|---|---|---|
| MREB-201 | P2 | No typed knobs for optimization policy control | Add additive typed config knobs with safe defaults | `engine/config.py`, tests | Config parse/default/bounds tests green | Closed (2026-03-05): added typed `efficiency` config policy (`enabled`, fanout caps, token budget, early-stop/caching flags) with fail-closed bounds validation and parse/default/bounds unit tests. |
| MREB-202 | P2 | Contract surfaces may need additive efficiency fields | Add backward-compatible contract fields only | `engine/contracts.py`, tests | Compatibility tests green; no schema break | Closed (2026-03-05): added additive `EfficiencyMetricsContract` and optional `MemoryPack.efficiency` contract field with backward-compatible defaults and contract roundtrip tests. |
| MREB-203 | P2 | Rollback confidence is weak without knob-off verification | Prove rollback by disabling knobs and re-running baseline gate | config/contracts + eval tools/tests | Baseline behavior restored and documented | Closed (2026-03-05): wired `run_responder_eval --config` as a runtime/eval consumer of `active_efficiency_policy` (fanout cap application) and verified rollback parity via paired baseline/disabled runs on identical truthset (`runtime/evals/mreb203_baseline_20260305_084856` vs `runtime/evals/mreb203_disabled_20260305_084856`). Unit tests cover cap-on and cap-off behavior. |

## Gate Matrix (Applied at Every Blocker Close)

- targeted tests for touched surfaces.
- 3-run baseline/candidate comparison using identical protocol inputs.
- dual-verdict evaluation run.
- required readout sections present.
- full-suite status reported.
- any full-suite failure in the standalone repo is a blocker.
- CodeRabbit workflow complete with gate result `actionable=0`.

## Baseline Artifact Link

- P0 baseline declaration (3-run median): `docs/evals/MNO_RUNTIME_EFFICIENCY_P0_BASELINE_20260305.md`
- P0 corpus-aligned closeout (3-run baseline/candidate): `docs/evals/MNO_RUNTIME_EFFICIENCY_P0_CLOSEOUT_20260305.md`

## Pragmatic Execution Sequence

1. Close P0 blockers first in small slices.
2. For each slice: targeted tests -> eval runs -> full-suite status -> PR + CR loop.
3. Do not start P1 edits without explicit unfreeze file approval logged in board.
4. Do not start P2 until P0/P1 gates are stable and repeatable.

## Linkage Verification

- This blockerboard references the source spec: `docs/MNO_RUNTIME_EFFICIENCY_SPEC.md`.
- The source spec references this blockerboard as its execution companion.
- Both docs must be updated together for material requirement or status changes.
