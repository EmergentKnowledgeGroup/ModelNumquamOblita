# Forward Path: Memory Orchestration (Post-v4.1)

## Purpose
This document defines the next practical build path for `NumquamOblita` so runtime memory feels natural in normal chat while staying strict on evidence and cost.

Primary outcome: memory that is useful, fast, and trusted.

## Fixed constraints (non-negotiable)
- No confident memory claim without evidence.
- Provenance remains immutable source-of-truth.
- Unsupported recall must abstain.
- PII remains preserved in source atoms.
- Forgetting is salience decay (not silent deletion).

## Current baseline
`NumquamOblita` already has:
- deterministic import from raw exports to atom store,
- STM/LTM routing policy,
- retrieval + verifier path,
- eval/load/signoff gates,
- one-click wrappers for pilot and runtime launch.

## Gaps to close next
1. **Memory intent overfire risk**
   - Low-stakes turns can still trigger unnecessary memory retrieval.
2. **Single-pass retrieval limits**
   - Some prompts need one follow-up search pass before answering.
3. **Long chat continuity quality**
   - STM must stay coherent across 20-100 turn sessions without context bloat.
4. **Operator explainability**
   - Need clearer reason codes for why memory was or was not used.
5. **Cost/latency budgeting under load**
   - Runtime needs hard, observable per-turn budgets.

## OpenClaw memory findings (public docs/research review)
As of this review, OpenClaw documents a memory stack with:
- a source-of-truth memory corpus plus derived index,
- retrieval via multiple channels (keyword + semantic style retrieval),
- score fusion/reranking,
- memory lifecycle tooling (`status`, `search`, diagnostics) and health checks.

Useful takeaways for `NumquamOblita`:
- Keep raw memory source separate from derived retrieval structures.
- Use hybrid retrieval scoring instead of single-signal ranking.
- Treat memory diagnostics as first-class runtime operations.

What we intentionally keep different:
- stricter claim verifier and abstain contract,
- explicit provenance lock behavior,
- policy-level gating before memory enters answer context.

## Proposed build order (modular, low rework)

## Implementation status snapshot (2026-02-11)
- **Phase A**: Implemented and regression-covered.
  - Routing logic: `engine/runtime/session.py` (`_front_desk_route`, `_predict_memory_mode`)
  - Tests: `tests/unit/test_runtime_session.py` (smalltalk/social/chat-first no-recall routing)
- **Phase B**: Implemented with working-set compaction + long-session guards.
  - Runtime: `engine/runtime/session.py` (short-term capacity, rolling summary, working-set token budget)
  - Tests: `tests/unit/test_runtime_session.py` (`test_runtime_session_enforces_working_set_token_budget`, `test_runtime_session_long_chat_keeps_stm_budget_and_recall_viable`)
- **Phase C**: Implemented with citation-preserving memory cards and contradiction metadata.
  - Runtime: `engine/runtime/session.py` (`_assemble_memory_cards`, `_item_to_card`)
  - Tests: `tests/unit/test_runtime_session.py` (card shape, citation density, contradiction visibility)
- **Phase D**: Implemented with bounded multi-pass retrieval.
  - Runtime: `engine/runtime/session.py` (`_run_ltm_retrieval`, follow-up query/time/token caps)
  - Tests: `tests/unit/test_runtime_session.py` (second pass trigger, early stop, time budget, repeat query stop)
- **Phase E**: Implemented with per-turn budget + explainability telemetry.
  - Runtime/API: `engine/runtime/session.py`, `engine/runtime/server.py`, `engine/runtime/ui/app.js`
  - Tests: `tests/integration/test_runtime_server.py`, `tests/unit/test_runtime_session.py`
- **Phase F**: Implemented with trust-v3 eval families and regression release gate.
  - Tooling: `tools/run_truthset_eval.py`, `tools/build_known_truth_eval_pack.py`, `tools/run_pilot_acceptance.py`, `tools/run_release_gate.py`
  - Tests: `tests/unit/test_live_eval.py`, `tests/integration/test_run_full_export_pilot_script.py`

### Phase A: Memory Intent Gate v2
Goal: skip memory retrieval on routine turns.

Deliverables:
- New intent decision classes: `none`, `stm_only`, `ltm_light`, `ltm_deep`.
- Deterministic first-pass gate with optional bounded escalation policy.
- Reason codes logged per turn.

Acceptance:
- Routine greeting/small-talk fixtures resolve to `none`.
- Memory-requiring fixtures retain >= current recall quality.
- **Status:** complete.

### Phase B: STM Working Set Layer
Goal: stable short-horizon continuity at low cost.

Deliverables:
- Session working set store (recent turns + compressed rolling summary).
- STM priority retrieval before LTM on `stm_only` and `ltm_light` modes.
- Bounded STM compaction policy (token and size limits).

Acceptance:
- 50-turn chat simulation remains under target token ceiling.
- Continuity references from recent chat improve vs baseline.
- **Status:** complete.

### Phase C: LTM Card Assembler
Goal: convert atom hits into coherent memory cards for model consumption.

Deliverables:
- Episode-level assembly from atom clusters with citation bundles.
- Card shapes: `fact_card`, `event_card`, `relationship_card`.
- Redundancy suppression and contradiction flags in card metadata.

Acceptance:
- Same recall quality with fewer raw atom tokens sent downstream.
- Every card preserves source citation path.
- **Status:** complete.

### Phase D: Bounded Follow-up Retrieval Loop
Goal: allow one additional retrieval pass when first pass is ambiguous.

Deliverables:
- Runtime loop budget (`max_passes=2`, strict time/token caps).
- Follow-up query strategy from first-pass uncertainty signals.
- Abort and abstain path when loop does not improve confidence.

Acceptance:
- Ambiguous fixture recall precision increases without latency blowout.
- No unbounded loops; hard timeout enforced.
- **Status:** complete.

### Phase E: Cost, Latency, and Explainability Controls
Goal: make runtime behavior predictable and operator-visible.

Deliverables:
- Turn-level budget ledger (retrieval ms, verification ms, token cost estimate).
- User-facing reason string: why memory was skipped/used/abstained.
- Ops endpoint additions for memory decision telemetry.

Acceptance:
- Budget guardrails trip deterministically in stress tests.
- Operators can explain each turn decision from logs alone.
- **Status:** complete.

### Phase F: End-to-End Trust Eval Upgrade
Goal: verify behavior under real chat patterns.

Deliverables:
- Expanded fixture families: routine chat, narrative recall, contradiction pressure.
- Known-truth eval pack with supported and unsupported probes.
- Regression gate that blocks releases on trust regressions.

Implementation notes:
- `run_truthset_eval.py` now defaults to `--fixture-mode trust-v3` and emits `truthset.case_counts.json`.
- `tools/build_known_truth_eval_pack.py` builds portable known-truth packs with family/decision summaries.
- `run_pilot_acceptance.py` adds `--trust-baseline-summary` + `--require-trust-regression-gate` and blocks on drift regressions.

Acceptance:
- No increase in confident-unsupported memory rate.
- Improved pass rate on multi-turn continuity fixtures.
- **Status:** complete.

## Testing strategy per phase
- Add unit tests for new decision logic first.
- Add integration tests for runtime/session endpoints.
- Add end-to-end fixture tests with deterministic seeds.
- Maintain phase-by-phase PR workflow with review feedback ingestion.

## Practical runtime model (simple)
Per turn:
1. classify intent,
2. read STM if needed,
3. read LTM only when justified,
4. verify claims,
5. answer or abstain,
6. write minimal updates back to memory queues.

This keeps default chat cheap while preserving deep recall paths when needed.

## Risks and mitigations
- **Risk:** over-gating hides useful memory.
  - **Mitigation:** fixture coverage for subtle recall prompts.
- **Risk:** follow-up loop raises latency.
  - **Mitigation:** hard pass/time budgets and fast-fail abstain.
- **Risk:** card assembly drops nuance.
  - **Mitigation:** card-level citation density thresholds.

## Definition of done for this forward path
- All six phases implemented in modular PR sequence.
- Full regression suite green.
- Pilot run on large real export passes signoff gates.
- Runtime logs make turn-level memory decisions auditable.
