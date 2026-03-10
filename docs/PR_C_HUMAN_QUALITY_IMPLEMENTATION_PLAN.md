# PR C Implementation Plan: Human-Quality Contract Hardening

## Objective
Close the metric/readout disconnect by making human-quality failures block signoff the same way safety failures do.

## References (Required Read)
- `docs/PR_C_HUMAN_QUALITY_FAILURE_REPORT_20260212.md` — concrete failure modes and regression rules that must be enforced by code + tests.
- `docs/CONTEXT_PACKAGE_V2_EXTERNAL_RESPONDER_EVAL_SPEC.md` — locked memory-service contract (context-package v2 + external responder eval).
- `docs/MEMORY_FORMATION_GAMEPLAN.md` — the “why questions look random” root cause (turn-level evidence being treated as episodic memory) and the staged fix plan.

## Non-Negotiable Outcomes
- No final PASS language unless:
  - `safety_verdict=PASS`
  - `human_quality_verdict=PASS`
- Supported non-routine eval cases must use strict expected alignment.
- Acceptance evals must grade the correct surface:
  - `context_package v2` quality + downstream model reply quality (not the internal standalone runtime reply).
- Rendered Q/A must be natural memory behavior, not question-echo templates.

## Phase 0 (Before Code Changes)
- Lock and publish explicit quality rubric for:
  - grammatical well-formedness,
  - anchor relevance,
  - contextual cohesion,
  - correction clarity,
  - routine naturalness.
- No implementation work starts until this rubric is written into the active run notes/checkpoint.

## Required Code Changes

### 1) Eval Integrity (`engine/runtime/live_eval.py`)
- Enforce explicit expected anchors for supported non-routine cases.
- Remove fallback success logic for supported families where retrieval hit is "any retrieval".
- Add strict alignment metrics for supported non-routine cases.

### 2) Question Quality (`tools/validate_truthset_questions.py`)
- Add hard-fail checks for:
  - malformed `when` clause grammar,
  - clipped correction options,
  - stacked temporal phrasing,
  - meta-jargon lexical replay,
  - instruction-like routine probes.
- Emit machine-readable defect tags per case.

### 3) Context Package v2 (`engine/runtime/session.py`, `engine/runtime/server.py`)
- Implement `context_package v2` that includes:
  - bounded LTM evidence (`ltm_evidence`) with citations and role hints,
  - deterministic service verdict (`PASS|ABSTAIN|CLARIFY|NO_MEMORY`),
  - explicit responder guidance (citations on/off toggle, no verbatim dumping),
  - timing breakdown (`memory_ms` subcomponents).
- Keep v1 available for backwards compatibility.

### 4) External Responder Harness (new, provider-agnostic)
- Add a responder client layer that can call:
  - local LM Studio for regression runs,
  - OpenAI Chat Completions (FT endpoint) for final signoff.
- Prompt-builder must consume `context_package v2` and produce a stable messages format.
- Add a post-LLM verifier that enforces "no unsupported memory claims" via citation checks.

### 5) Responder Eval + Readout + Gate (tools)
- Add a new eval path: truthset -> context_package(v2) -> model -> verifier.
- `human_readout.md` must show:
  - question
  - top evidence (with citations + role hints)
  - model answer (the real judged output)
  - defect tags and dual verdict
- Gate must include latency thresholds for:
  - `memory_ms_p95`
  - `model_ms_p95`
  - `total_ms_p95`

### 6) Episode Card Signal Quality (`tools/build_episode_cards.py`, retrieval wiring)
- De-genericize entity handling so promotion is not dominated by generic role entities.
- Improve anchor specificity for episode cards used by retrieval.
- Ensure episode retrieval can contribute useful context even when short-circuit primary criteria are not met.

### 7) (Dependency) “Episode-Seeded” Supported Questions
- Supported non-routine truthset prompts must prefer **promoted episode cards** as seeds, not random single-turn atoms.
- This is the minimal “human memory” alignment required for PR C question quality to be stable across corpora.
- Full memory-formation refactor is tracked in `docs/MEMORY_FORMATION_GAMEPLAN.md`; PR C should land the eval-facing part:
  - sampling and template selection that yields event-grade questions from episode cards.

## Required Tests

### Unit
- `tests/unit/test_live_eval.py`
  - supported non-routine case without expected anchors fails generation/eval integrity checks.
- `tests/unit/test_runtime_session.py`
  - `context_package v2` includes bounded LTM evidence and role hints when route triggers LTM.
  - v2 includes timing fields.
- `tests/unit/test_responder_prompt_builder.py`
  - evidence formatting is stable and cites `source_id#message_id`.
- `tests/unit/test_responder_verifier.py`
  - missing/unknown citations fail verification in supported cases.

### Integration
- `tests/integration/test_oneclick_human_readout_tools.py`
  - readout includes full Q/A audit table, defect tags, and dual verdict fields.
- `tests/integration/test_episode_latency_and_question_quality_tools.py`
  - malformed/clipped question samples are flagged as weak/fail.
  - meta-jargon replay samples are flagged as weak/fail.
- `tests/integration/test_runtime_adapter_endpoints.py`
  - adapter `context-package` surfaces v2 fields without leaking internal exceptions.

### E2E
- Oneclick against:
  - refined corpus,
  - noisy corpus.
- Manual audit of all rendered Q/A pairs.
- Completion blocked if either verdict fails.

## Suggested Initial Thresholds
- `false_memory_rate == 0.0`
- `abstain_precision >= 1.0`
- `routine_over_recall_rate <= 0.0`
- `event_grade_question_rate >= 0.95`
- `fragment_question_rate <= 0.05`
- `relevance_aligned_hit_rate >= 0.95` (supported non-routine)
- `malformed_question_rate == 0.0`
- `response_parrot_rate == 0.0`
- `irrelevant_related_context_rate <= 0.02`
- `p95_retrieved_atoms <= 24` (initial cap; tune only with evidence)

## Review Checklist Before Claiming Success
1. Run targeted tests.
2. Run full `pytest -q`.
3. Run oneclick on both corpora.
4. Inspect every rendered case in `human_readout.md`.
5. Report both verdicts and defects with a full Q/A audit table.
6. Only then mark run as "near-perfect pass candidate".
