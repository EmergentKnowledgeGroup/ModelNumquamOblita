# PR C Failure Report (Human-Quality Contract) — 2026-02-12

This document is the handoff anchor for **PR C human-quality hardening**.

It answers:
- What is currently broken (with concrete evidence).
- Why the system can still “PASS” while the rendered questions/answers are bad.
- What must be changed (methodology, integration points, and regression strategy).

## Scope and Contracts

Primary contracts:
- `docs/NEAR_PERFECT_GOAL.md`
- `docs/PR_C_HUMAN_QUALITY_IMPLEMENTATION_PLAN.md`
- `docs/NEAR_PERFECT_EVENT_PROMPT_GAP_FIX_SPEC.md`
- `AGENTS.md` (dual verdict + blocking checks + reporting contract)

Near-perfect is **not** “safety metrics pass.” It is “safety + human-quality pass in the same run.”

## Evidence (Ground Truth Artifacts)

Primary run used for diagnosis:
- `runtime/evals/live_dbjson_20260212_192840/human_readout.md`
- `runtime/evals/live_dbjson_20260212_192840/eval/truthset.generated.jsonl`
- `runtime/evals/live_dbjson_20260212_192840/eval/summary.json`
- `runtime/evals/live_dbjson_20260212_192840/acceptance_gate.json`
- `runtime/evals/live_dbjson_20260212_192840/episodes/episode_cards.json`
- `runtime/evals/live_dbjson_20260212_192840/episodes/episode_cards.readout.md`

## Executive Summary (Why It “Passes” While Looking Wrong)

The current system can pass the acceptance gate while producing obviously bad prompts and odd responses because:

1. **Eval integrity is loose for many supported non-routine families**
   - In `engine/runtime/live_eval.py`, if `expected_atom_ids` / `expected_citations` are empty, a supported PASS case can be credited as a “hit” based on **any non-empty retrieval/citation**, not direct anchor alignment.

2. **Question-quality validation misses human-blocking defects**
   - The current validator and gate mostly track aggregate `event_grade_question_rate` and `fragment_question_rate`.
   - It does not hard-fail on the defects the near-perfect contract cares about:
     - malformed recall grammar (`when <bare phrase>`),
     - clipped correction options,
     - instruction-like routine probes,
     - meta-jargon replay as “event cues.”

3. **Response composition is template-driven and can inject unrelated context**
   - `engine/runtime/session.py` emits wrappers:
     - `Acknowledged: <prompt>`
     - `Memory-backed response for: <prompt>`
   - It also appends `Related context: <second card>` without relevance gating.
   - This creates the “semantic echo” + “dump adjacent memory” behavior.

4. **Retrieval fanout is broad and routinely hits the cap**
   - Default retrieval budget includes `rerank_limit=48` (`engine/config.py`).
   - In the run, many cases retrieve exactly 48 atoms, increasing context bleed and allowing unrelated “support” to sneak in.

5. **Episode cards exist but do not reliably participate in answers**
   - The run reports `episode_hit_rate=0.0` (`eval/summary.json`).
   - The runtime currently only uses episode retrieval to replace LTM when a “short-circuit” threshold is met; otherwise episodes do not contribute.

## Concrete Failures (From Rendered Output)

### 1) Malformed “when” clause grammar shipped as “event-grade”

Example (case `tc_0001`, `human_readout.md`):

Question:
> What do you remember about Xander when leans closer claws resting lightly against your palm voice soft?

This violates `AGENTS.md` and `docs/NEAR_PERFECT_GOAL.md` (“malformed recall question grammar” is a hard block),
yet the run reports:
- `event_grade_question_rate: 1.0000`
- `weak_cases: 0`
- `decision: PASS` in `acceptance_gate.json`

Root cause:
- The question quality logic (`engine/runtime/live_eval.py:assess_truthset_question_quality`) has no explicit check for malformed `when` clauses (the “when <bare phrase>” pattern).

### 2) Routine probe is instruction text and the response is pure parrot

Truthset routine prompt:
> No recall required here, just a normal reply.

Response becomes:
> Acknowledged: No recall required here, just a normal reply.

Root cause:
- `_compose_response()` in `engine/runtime/session.py` returns `Acknowledged: {user_text}` for `NO_MEMORY`/route=none.

Why this is a hard failure:
- `docs/NEAR_PERFECT_GOAL.md` bans routine echo responses.
- `docs/NEAR_PERFECT_EVENT_PROMPT_GAP_FIX_SPEC.md` explicitly calls out instruction-like routine prompts as a hard reject case.

### 3) Correction questions are snippet-clipped and enable “semantic matching”

Examples in `truthset.generated.jsonl` show short quoted options and weak event framing.
They can “pass” if the response picks whichever option scores higher against a shallow evidence blob,
even when the overall memory reconstruction is poor.

Root cause:
- Generator templates quote short spans and do not enforce event-window reconstruction.
- For many supported PASS families, expected anchors are empty, so “any retrieval/citation” can pass.

### 4) “Related context” is not relevance checked

In `_compose_response()`:
- “support” defaults to the second memory card / second pack core item.
- It is printed as `Related context: ...` regardless of relevance to the asked memory.

This directly explains unrelated context being injected into memory-backed answers.

### 5) Retrieval breadth is large and is not treated as quality debt

Observed in readout:
- Many cases have `retrieved_atom_ids: 48` (cap).

Root cause:
- Retrieval budget defaults and the engine “keep retrieval live” failsafe.
- No acceptance gate metric enforces a breadth ceiling for non-routine cases.

### 6) Episode cards: many are weakly shaped and generic-entity dominated

The episode readout includes many `candidate`/`questionable` cards with:
- `weak_event_shape`
- `single_atom_low_support`
- generic entities like `user` / `assistant`

Even when built, runtime rarely uses them unless it can short-circuit.

## Spec-to-Implementation Gap Map

### Dual Verdict (required)

Spec requires:
- `safety_verdict`
- `human_quality_verdict`
- No PASS language unless both are PASS

Current:
- `tools/run_oneclick_eval.py` writes only a single `decision` based on safety metrics + coarse question quality rates.
- No `human_quality_verdict` exists in artifacts.

### Eval Integrity (required)

Spec requires:
- Supported non-routine PASS cases have explicit expected anchors.
- Supported PASS “hits” require direct anchor alignment (not “any retrieval”).

Current:
- `generate_truthset()` only sets `expected_atom_ids` for direct-alignment `supported_recall`.
- `evaluate_truthset()` treats many supported PASS families as “hit” if any citation/retrieval exists.

### Human-quality blocking checks (required)

Spec requires:
- malformed `when`, clipped correction options, instruction-like routine probes, parrot wrappers, unrelated related-context => FAIL

Current:
- None of these defects are emitted as machine-readable tags or gate failures.

### Episode-first recall (expected direction)

Spec expects:
- episode cards to be a first-tier retrieval source for event recall.
- episode retrieval to contribute even when it cannot short-circuit.

Current:
- episode retrieval is all-or-nothing: short-circuit or ignored.

## Fix Methodology (Decision-Complete, Implementation-Facing)

The goal is not “tune prompts.” The goal is to make it **impossible** for bad questions/answers to pass.

### A) Eval Integrity: supported PASS must be anchor-aligned PASS

Method:
1. Ensure every supported non-routine PASS family carries explicit expected anchors:
   - either `expected_atom_ids` and/or strict acceptable `expected_citations`.
2. Score “hits” by intersection:
   - `retrieval_hit` requires overlap with expected anchors.
   - `citation_hit` requires overlap with expected citations (or citations derived from expected atom provenance).
3. Add `relevance_aligned_hit_rate` metric for supported non-routine families and make it a human-quality gate threshold.

### B) Question Quality: add defect tags + hard blocks

Method:
1. Detect and tag:
   - malformed `when <bare phrase>`,
   - clipped quote options in correction prompts,
   - stacked temporal phrasing collisions (including `what happened next` + `right before/after ...` and
     `right before/after <interrogative>` injections like `right before How ...`),
   - meta-jargon replay as event cue,
   - instruction-like routine probes.
2. Emit machine-readable `defect_tags` per case and summarize counts.
3. Gate must FAIL if any blocking defect exists.
4. Truthset generation must regenerate candidates until quality passes (bounded attempts), else hard-fail with reasons.

### C) Response Composition: remove parroting + suppress unrelated context

Method:
1. Eliminate:
   - `Memory-backed response for: ...`
   - `Acknowledged: ...`
2. Only include “Related context” when it passes explicit relevance criteria:
   - overlap with accepted anchors / citations used by the verifier,
   - or a minimum similarity threshold computed from evidence text.
3. Disallow user-authored atoms as *primary* evidence for memory-backed claims (they may appear as clearly attributed secondary context).

### D) Retrieval breadth: measure, cap, and treat over-breadth as human-quality failure

Method:
1. Add metrics:
   - `avg_retrieved_atoms`
   - `p95_retrieved_atoms` (supported non-routine)
2. Fail `human_quality_verdict` if retrieval breadth exceeds ceilings.
3. Reduce breadth via configuration + routing and track fanout so it’s tuned with evidence.

### E) Episode cards: enable by default + allow contribution without short-circuit

Method:
1. Auto-load latest episode cards by default (when a path is not explicitly configured).
2. When episode hits exist but do not meet short-circuit thresholds:
   - merge episode pack into retrieval pack as bounded context,
   - tag retrieved IDs with `episode_card:` so metrics/readout can see contribution.
3. Tighten promotion/quality to avoid generic-entity dominance.

## Regression Strategy (“set in stone”)

1. Add unit/integration tests for every blocked defect:
   - malformed `when` clause detected => FAIL
   - instruction-like routine prompt => FAIL
   - stacked temporal interrogative injection (`right before How ...`) => FAIL
   - response parroting wrapper => FAIL
   - unrelated related-context insertion => FAIL
   - supported PASS family without anchors => FAIL
2. Acceptance gate writes:
   - `safety_verdict`
   - `human_quality_verdict`
   - final `decision` PASS only if both pass
3. `human_readout.md` becomes truly skimmable:
   - top summary table (verdicts + defect counts)
   - per-case Q/A with short evidence snippets
   - debug JSON moved under collapsible sections or optional verbose mode

## Status

This report marks Phase 0 completion (“we know exactly why it fails”).
Next: implement PR C per `docs/PR_C_HUMAN_QUALITY_IMPLEMENTATION_PLAN.md` using this document as the source-of-truth for failure modes and regression rules.
