# Spec/Build Completeness Remediation Plan (2026-02-16)

Status: Completed  
Owner: NumquamOblita Core  
Reference audit checkpoint: `runtime/checkpoints/LATEST.md`

This checklist is the canonical execution reference for closing all confirmed spec/build gaps discovered in the full completeness audit.

## Scope

- Source specs/build docs:
  - `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md`
  - `docs/PR_C_HUMAN_QUALITY_IMPLEMENTATION_PLAN.md`
  - `docs/CONTEXT_PACKAGE_V2_EXTERNAL_RESPONDER_EVAL_SPEC.md`
  - `AGENTS.md`
- Goal:
  - eliminate known implementation mismatches,
  - preserve current behavior where correct,
  - add regression coverage for every remediation cluster.

## Remediation Checklist

### A) Wizard + Episode Build Contract

- [x] A1. Fix wizard/build argument mismatch.
  - Goal: `/api/wizard/build/run` must not pass unsupported CLI flags to `tools/build_episode_cards.py`.
  - Fix target:
    - align server CLI invocation to supported flags, or add supported flags in builder.
  - Validation:
    - integration test covering successful wizard build run.

- [x] A2. Emit rejects artifact (`episode_cards_<stamp>.rejects.json`) with machine-readable reasons.
  - Goal: builder always writes rejects artifact referenced by wizard/state/spec.
  - Fix target:
    - add `--rejects-out` support in `tools/build_episode_cards.py`,
    - write schema-tagged rejects payload.
  - Validation:
    - script integration test verifies rejects file exists and contains structured reasons.

- [x] A3. Emit canonical episode fields in artifacts.
  - Goal: cards include `actors`, `topic_tags`, `timestamp_start`, `timestamp_end` (while keeping aliases for compatibility).
  - Fix target:
    - update builder output payload fields and runtime normalization where needed.
  - Validation:
    - unit/integration assertions for canonical fields.

- [x] A4. Improve segmentation toward Phase-2 contract.
  - Goal: clustering includes speaker alternation and lexical/topic-shift signals in addition to time gap/domain overlap.
  - Fix target:
    - refine cluster split logic in builder with bounded heuristics.
  - Validation:
    - targeted unit coverage for split behavior.

### B) Eval Integrity + Dual Verdict Contract

- [x] B1. Move one-click judged surface to responder eval path.
  - Goal: one-click acceptance uses context-package v2 + external responder + verifier path, not legacy `handle_turn`-only eval.
  - Fix target:
    - swap `run_oneclick_eval.py` eval command to `tools/run_responder_eval.py` (or equivalent adapter).
  - Validation:
    - integration test confirms one-click artifacts come from responder eval run.

- [x] B2. Enforce dual verdict in acceptance gate output.
  - Goal: never report pass unless both `safety_verdict` and `human_quality_verdict` pass.
  - Fix target:
    - gate artifact includes both verdict fields,
    - CLI output avoids single-verdict pass language.
  - Validation:
    - integration test for pass/fail permutations and emitted fields.

- [x] B3. Tighten supported non-routine alignment rules.
  - Goal: supported non-routine cases cannot pass retrieval/citation success on empty-by-default or weak alignment.
  - Fix target:
    - enforce strict expected anchor/citation overlap in eval metrics path used by gate.
  - Validation:
    - targeted tests for strict-hit behavior.

- [x] B4. Add human-quality defect tagging and reporting contract outputs.
  - Goal: per-case defect tags + full Q/A audit + defect counts in run outputs/readout.
  - Fix target:
    - extend validator/readout/gate artifact schema with defect tags and counts.
  - Validation:
    - integration tests for defect-tag emission and readout content.

### C) UI/UX Parity (Phase 5-7 Contract)

- [x] C1. Add “Restore last published” rollback action.
  - Goal: operator can restore published pointers/artifacts from last published snapshot.
  - Fix target:
    - runtime endpoint + UI control + wizard state updates.
  - Validation:
    - integration/API test and UI action hook test.

- [x] C2. Add atom conflict-marking UI flow.
  - Goal: UI can call `/api/memory/atoms/<atom_id>/conflict` with reason/target atom.
  - Fix target:
    - add controls in memory detail pane + handler in app.js.
  - Validation:
    - UI integration test for endpoint call payload.

- [x] C3. Verify stage actionable links.
  - Goal: verify results include clickable links to exact cards/evidence entries.
  - Fix target:
    - server payload enrichments and UI rendering in verify panel.
  - Validation:
    - integration test asserting linkable fields and UI render snapshot.

- [x] C4. Go Live provider/model configuration visibility.
  - Goal: Go Live stage exposes current provider/model config and editing entrypoint.
  - Fix target:
    - enrich go-live payload and UI panel rendering.
  - Validation:
    - UI/API test for provider/model config fields.

### D) Documentation Integrity

- [x] D1. Add missing `docs/IA_NO_INTEGRATION_PLAN.md`.
  - Goal: file exists and accurately documents IA/NO integration state and constraints.
  - Validation:
    - docs lint/manual check for path validity.

- [x] D2. Resolve stale planned placeholders in `docs/INDEX.md`.
  - Goal: no unresolved dead-link placeholders in primary index.
  - Validation:
    - doc path audit via `rg --files docs`.

### E) Post-Audit Completeness Gaps

- [x] E1. Enforce latency thresholds in one-click dual-verdict gate.
  - Goal: acceptance gate includes and enforces `memory_ms_p95`, `model_ms_p95`, `total_ms_p95` budgets.
  - Validation:
    - unit/integration gate tests covering latency exceedance failures.

- [x] E2. Remove weak live-eval fallback for supported non-routine cases without anchors.
  - Goal: supported non-routine cases with missing expected anchors cannot score retrieval/citation hits.
  - Validation:
    - live-eval unit test asserting forced miss for missing-anchor supported case.

- [x] E3. Align builder profile persistence to canonical schema contract.
  - Goal: persisted profile includes `created_at`, `updated_at`, and canonical entry arrays (`entities`, `cue_phrases`, `domain_rules`) with status/kind metadata, and episode build consumes the selected profile.
  - Validation:
    - integration API test for save/load profile payload shape and compatibility fields.
    - wizard build test asserts selected profile path/id are applied in build output policy.

- [x] E4. Update canonical API/UI docs for newly implemented runtime surfaces.
  - Goal: API matrix and operator guides reflect restore rollback, provider config visibility, telemetry ledger endpoints, and verify actionable links.
  - Validation:
    - docs manual audit against runtime endpoint surface.

- [x] E5. Add Windows single-exe packaging workflow baseline.
  - Goal: phase-7 packaging contract has concrete tooling, wrappers, and diagnostics metadata.
  - Validation:
    - dry-run packaging integration test + runtime packaging-instructions API assertions.

- [x] E6. Emit responder-eval acceptance artifacts directly from responder path.
  - Goal: `tools/run_responder_eval.py` writes `acceptance_gate.json` (dual verdict + failures + thresholds + latency) and `human_readout.md`.
  - Validation:
    - integration test for responder-eval artifact emission and dual-verdict surface.

## Execution Rules

- Implement in small, reviewable commits by cluster (A -> B -> C -> D -> E).
- After each cluster:
  - run targeted tests first,
  - then run full regression suite (`PYTHONPATH=. pytest -q`),
  - update checkpoint (`runtime/checkpoints/LATEST.md` + `.json`).

## Completion Criteria

All checklist items are checked and regression tests are green with no documented hard blockers.
