# MNO Runtime Efficiency Program (Latency + Token Efficiency)

Version: 2026-03-04 (specswarm fully integrated)
Status: Draft (execution-ready)
Standalone note: imported into the standalone MNO repo on 2026-03-10. Historical mixed-repo freeze language is superseded by the standalone boundary rules below.
Execution companion: `docs/MNO_RUNTIME_EFFICIENCY_BLOCKERBOARD.md` (generated from this spec)
Related quality spec: `docs/MNO_LEAN_RETRIEVAL_UPGRADES_SPEC.md`
Related quality tracker: `docs/MNO_LEAN_RETRIEVAL_BLOCKERBOARD.md`

## 0. What This Is

This spec defines a dedicated MNO runtime-efficiency program to:
- reduce end-to-end latency,
- reduce token usage,
- preserve safety and human-quality guarantees.

This is separate from retrieval-quality hardening. Efficiency never overrides trust-contract behavior.

## 0.1 Goals (Hard)

- Improve p50 and p95 latency for memory-backed turns.
- Reduce prompt/completion/tool token usage per evaluated turn.
- Preserve strict dual verdicts:
  - `safety_verdict=PASS`
  - `human_quality_verdict=PASS`
- Preserve trust guards:
  - `false_memory_rate == 0.0`
  - `abstain_precision == 1.0`

## 0.2 Non-Goals

- No weakening of verifier/evidence requirements for speed.
- No reintroduction of removed document-research/add-on lane surfaces in this program.
- No dependency-heavy retrieval channels in this program.

## 0.3 Definitions (Normative)

- efficiency run: eval run with latency, token, and quality outputs.
- token budget breach: any required token metric violates active phase gate thresholds in section 3; this is automatic FAIL/stop-ship.
- latency breach: `latency_p50_ms` or `latency_p95_ms` violates active phase gate thresholds in section 3.
- quality regression: dual-verdict failure or guardrail breach (`false_memory_rate`, `abstain_precision`, `evidence_precision_at_k`, `junk_rate_at_k`, `conflict_coverage`).
- hard blocker: progress requires forbidden file edits without approval, or any safety/human-quality gate fails.
- strict invalidation: cache keys must include all scope/revision dimensions listed in section 3.1 and must bypass cache on uncertainty.

## 0.4 Program Linkage Rules

- Requirements live in this spec.
- Execution/status/blockers live in `docs/MNO_RUNTIME_EFFICIENCY_BLOCKERBOARD.md`.
- Every phase update must reference both docs.
- Material spec changes require same-PR blockerboard sync.

## 0.5 Standalone Boundary Rule (Required)

This standalone repo excludes the removed document-research/add-on lane by construction.

If a future change would reintroduce any removed surface:
1. propose the exact file list,
2. explain why standalone MNO still needs it,
3. provide the regression plan,
4. record the scope explicitly in the blockerboard before implementation.

## 1. Constraints and Primary Surfaces

The standalone repo no longer ships the removed document-research lane. The active surfaces for this program are:

Primary implementation zones:
- `engine/retrieval/*`
- `engine/memory/*`
- `engine/continuity/*`
- `tests/unit/*`
- `docs/*`

Conditionally approved runtime/eval zones (P1/P2 only):
- `engine/runtime/live_eval.py`
- `tools/run_responder_eval.py`
- `tools/run_oneclick_eval.py`
- `tools/build_responder_eval_readout.py`
- matching unit tests only

### 1.1 Safety-First Contract

- Never claim PASS/green unless both verdicts pass.
- Never relax evidence alignment checks for performance.
- If optimization creates correctness uncertainty, fail closed and log blocker.

## 2. Baseline and Measurement Contract

### 2.1 Baseline Declaration (Required)

Every phase/slice must declare baseline in blockerboard and run summary:
- `baseline_commit`
- `baseline_run_ids` (3 run IDs in protocol order)
- dataset/case-set ID
- run date/time
- cache mode (`cold`, `warm`, `disabled`)
- hardware/concurrency notes

### 2.2 Measurement Protocol (Required)

Baseline and candidate comparisons must use identical:
- dataset slice,
- case count,
- seed/randomization controls,
- concurrency configuration,
- cache mode,
- environment/runtime profile.

Run stability requirement:
- execute at least 3 repeated runs,
- use median comparison for pass/fail,
- report per-run values in artifacts.
- if per-run variance exceeds 10% on latency or total tokens, treat as unstable and FAIL until rerun is stable.

Case coverage requirement:
- include at least 30 memory-backed non-routine cases,
- include routine-chat control cases,
- if corpus smaller, use full corpus and annotate count.

### 2.3 Token Accounting Scope

`tokens_total_avg` is computed from:
- `tokens_prompt_avg`
- `tokens_completion_avg`
- tool/eval-call token usage attributable to the turn path

Reporting must state whether retry tokens are included. Default: include retry tokens.

### 2.4 Metric Semantics and Undefined Handling

- `evidence_precision_at_k` and `junk_rate_at_k` must define `k` in run output.
- If retrieval set is empty for a case:
  - supported-case expectation: count as miss for precision/coverage accounting,
  - unsupported-case expectation: handled as abstain/clarify without false support.
- Undefined/NaN/Inf metrics are automatic FAIL.
- `k <= 0` is invalid configuration and must fail before run execution.

### 2.5 Required Metrics

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

Metric ownership mapping:
- eval summary source of truth: `engine/runtime/live_eval.py` (`LiveEvalSummary` path)
- oneclick/responder gate enforcement: `tools/run_oneclick_eval.py`, `tools/run_responder_eval.py`
- human-readout required sections: `tools/build_responder_eval_readout.py`

If any required metric is not emitted by current tooling, open blockerboard item before declaring phase active.

### 2.6 P0 Reporting Contract (Required)

All P0 runtime-efficiency run summaries must follow:
- `docs/MNO_RUNTIME_EFFICIENCY_P0_REPORTING_CONTRACT.md`

Required declaration fields:
- `breach_declaration`
- `waiver_declaration`
- `final_status`

Language rule:
- never use PASS/green/ready language unless:
  - `safety_verdict=PASS`
  - `human_quality_verdict=PASS`
  - no breaches
  - no waivers
  - `final_status=DONE`

## 3. Phase Plan

### 3.1 P0: Low-Risk Internal Efficiency (Allowlist-Only)

Objective:
- reduce retrieval/context waste without external runtime contract changes.

Candidate work:
- query-conditioned relevance admission tightening,
- early-stop retrieval only after minimum support/conflict checks pass,
- exact-duplicate pruning before pack assembly,
- bounded context packing,
- cache-safe reuse in retrieval/memory surfaces.

P0 constraints:
- no `engine/config.py` or `engine/contracts.py` edits,
- no reintroduction of removed document-research/add-on surfaces,
- no unfreeze overrides outside section 1.2 primary allowlist,
- no external output shape changes,
- no verdict semantic changes,
- internal ordering/dedupe/caching changes must preserve trust-contract behavior.

Cache strict-invalidation minimum key dimensions:
- user/store scope,
- store revision token,
- continuity revision token,
- retrieval profile,
- enabled channels,
- critical budgets/thresholds.

P0 acceptance gates (choose one efficiency path, plus all quality gates):
- Path A (latency-led):
  - `latency_p50_ms` improves >= 10% vs baseline,
  - `latency_p95_ms` improves >= 10% vs baseline,
  - `tokens_total_avg` not worse than +3%.
- Path B (token-led):
  - `tokens_total_avg` improves >= 12% vs baseline,
  - `latency_p50_ms` and `latency_p95_ms` not worse than +3%.

P0 local mock-provider closeout lane (allowed only for local corpus validation):
- Preconditions:
  - provider is `mock`,
  - baseline and candidate both produce `tokens_total_avg == 0.0`,
  - dual verdicts are PASS on all repeated runs.
- Gate:
  - treat P0 as non-regression closeout instead of improvement claim,
  - `latency_p50_ms` and `latency_p95_ms` must remain within +3% of baseline median,
  - `retrieval_fanout_p95 <= baseline + 5%`,
  - all P0 quality/integrity gates below still pass.
- Reporting requirement:
  - mark this as "mock-provider non-regression closeout" in the phase artifact,
  - do not claim production efficiency gains from this lane alone.

P0 mandatory quality/integrity gates:
- `false_memory_rate == 0.0`
- `abstain_precision == 1.0`
- `safety_verdict=PASS`
- `human_quality_verdict=PASS`
- no regression vs baseline median with tolerance in:
  - `evidence_precision_at_k >= baseline - 0.01`
  - `junk_rate_at_k <= baseline + 0.01`
  - `conflict_coverage >= baseline`
- retrieval fanout must remain bounded:
  - `retrieval_fanout_p95 <= baseline + 5%`

### 3.2 P1: Runtime/Eval Path Efficiency (Approved Minimal Unfreeze)

Objective:
- reduce eval/runtime overhead and standardize strict efficiency reporting.

Candidate work:
- reduce oneclick/responder orchestration overhead,
- reduce readout generation overhead while preserving required quality sections,
- hard-fail runs with missing/non-finite efficiency metrics,
- stabilize metric fields for cross-run comparability.

P1 constraints:
- touch only explicitly approved files,
- no retrieval-loop/session behavior changes unless explicitly approved,
- no reintroduction of removed document-research/add-on surfaces,
- unfreeze approval must be logged in blockerboard with file-level constraints.

Required readout sections for PASS eligibility:
- `## Verdict Summary`
- `## Q/A Audit Table`
- `## Top Failure Examples`

P1 acceptance gates:
- additional >= 8% latency gain or >= 8% token gain vs post-P0 baseline (median of 3),
- non-led metric bound: the non-target metric cannot regress by more than +3%,
- dual-verdict contract remains strict,
- required readout sections always present,
- any missing/non-finite required metric fails run.

### 3.3 P2: Config-First Optimization Controls

Objective:
- expose additive typed optimization knobs and tune policy safely.

Candidate work:
- typed additive knobs in `engine/config.py`,
- backward-compatible contract additions in `engine/contracts.py`,
- policy controls for fanout, packing, and cache behavior.

P2 constraints:
- additive/backward-compatible only,
- defaults preserve prior behavior,
- config/contracts changes require explicit owner approval,
- each knob must have parse/default/bounds tests.

P2 acceptance gates:
- minimum >= 5% gain in latency or total tokens over P1 baseline (median of 3),
- non-led metric bound: the non-target metric cannot regress by more than +3%,
- no quality regressions,
- rollback verified by disabling knobs.

## 4. Regression Gates and Test Policy

Every phase/slice must run:
- targeted unit tests for touched files,
- responder/oneclick eval with dual-verdict output,
- human readout generation (must include required sections),
- full suite status report.

Mandatory gate validity checks for all phases:
- all required metrics present,
- all required metrics finite,
- gate fails closed on missing data.
- all phase-gate decisions are based on median-of-3 runs from section 2.2.

Full-suite policy:
- any full-suite failure in the standalone repo is a blocker,
- report failures explicitly in run artifacts,
- do not use mixed-repo frozen-surface waiver language in this standalone lane.

## 5. Implementation Touchpoints Map (By Spec Section)

Section 2 metric instrumentation/summary:
- `engine/runtime/live_eval.py`
- `tests/unit/test_live_eval.py`

Section 3.1 retrieval-path efficiency:
- `engine/retrieval/engine.py`
- `engine/retrieval/verifier.py`
- `engine/memory/store.py`
- `engine/memory/sqlite_store.py`
- `engine/continuity/store.py`
- `tests/unit/test_retrieval_engine.py`
- `tests/unit/test_claim_verifier.py`
- `tests/unit/test_memory_store.py`
- `tests/unit/test_sqlite_atom_store.py`

Section 3.2 eval/readout efficiency:
- `tools/run_responder_eval.py`
- `tools/run_oneclick_eval.py`
- `tools/build_responder_eval_readout.py`
- `engine/runtime/live_eval.py`
- `tests/unit/test_run_responder_eval.py`
- `tests/unit/test_run_oneclick_eval.py`
- `tests/unit/test_build_responder_eval_readout.py`
- `tests/unit/test_live_eval.py`

Section 3.3 config-first controls:
- `engine/config.py`
- `engine/contracts.py`
- `tests/unit/test_config.py`
- `tests/unit/test_contracts.py`

Any touchpoint outside this map requires spec + blockerboard update.

## 6. Rollout and Backout

Rollout order:
1. run baseline (record declaration fields in 2.1),
2. run candidate (same protocol),
3. compare against phase gates,
4. generate/attach required readout sections,
5. ship only when tests are green and CodeRabbit `actionable=0`.

Backout order:
1. revert optimization slice,
2. clear/bump cache revision token if cache touched,
3. ensure no stale cache reuse across baselines,
4. rerun baseline gate,
5. update blockerboard with root cause + next action.

Cache isolation requirement for rollout/backout:
- baseline and candidate runs must use isolated cache namespaces or explicit cache reset between runs.
- any cross-run cache contamination invalidates comparison and requires a rerun to remain valid.

Artifact retention (required):
- keep baseline/candidate run IDs,
- keep per-case Q/A audit output,
- keep top failure examples,
- keep explicit boundary-waiver notes only if a future change intentionally broadens standalone scope.
- keep CodeRabbit gate artifacts and `tools/pr_feedback_gate.py` result showing `actionable=0`.

## 7. Open Risks and Mitigations

Risk: speed gains hide alignment regressions.
- Mitigation: hard integrity gates (`evidence_precision_at_k`, `junk_rate_at_k`, `conflict_coverage`).

Risk: cache misuse causes stale/wrong reuse.
- Mitigation: strict invalidation key dimensions + bypass on uncertainty.
- cache uncertainty includes missing key dimensions, revision mismatch, cache decode errors, or unknown version.

Risk: token cuts reduce answer quality.
- Mitigation: dual-verdict + per-case audit required before any success claim.

Risk: ambiguous ownership of standalone-boundary/config changes.
- Mitigation: explicit approval protocol in section 0.5 and blockerboard logging.

## 8. Current Pre-Execution Gaps (Must Be Tracked as Blockers)

- keep spec/blockerboard linkage verified on every material update.
- required metric emission gaps (if any) must be resolved or explicitly deferred with blocker IDs.
- unfreeze approvals must be recorded before any P1/P2 edit.

## 9. SpecSwarm Integration Notes

Round-1 findings incorporated:
- added measurement protocol, repeated-run stability, and baseline declaration contract,
- fixed P0 gate contradiction by defining Path A vs Path B,
- clarified additive behavior scope and strict invalidation requirements,
- added explicit standalone-boundary waiver protocol,
- added required readout sections and missing/non-finite metric fail rules,
- added clear touchpoint ownership map and pre-execution blocker requirements.

Final-QA findings incorporated:
- clarified P0 allowlist-only rule and unfreeze scope,
- defined variance stability requirement and median-of-3 gate semantics,
- added explicit no-regression tolerances and fanout non-regression bound,
- added non-led metric regression bounds for P1/P2,
- converted token budget breach into explicit automatic stop-ship,
- added cache isolation/reset requirement between baseline and candidate runs.
