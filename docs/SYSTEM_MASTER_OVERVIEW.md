# System Master Overview

This document is the compact handoff map for `ModelNumquamOblita`: what it does, how it is wired, where key code lives, and when major capabilities were added.

## 1) What the system is

`ModelNumquamOblita` is a local-first memory engine for identity continuity.  
It converts raw conversation exports into evidence-backed memory atoms, retrieves relevant memory for runtime responses, and blocks unsupported recall with abstention behavior.

Core invariant: no confident memory claim without source-backed evidence.

Standalone scope note: this repo excludes ANO document-research/runtime surfaces. The public package/runtime path is personal-memory only.

## 2) End-to-end pipeline (broad flow)

1. Import archive exports (IA-style `db.json` / conversations export) into a durable evidence store (sqlite atoms + provenance).
2. Build **episode cards** (event-level memory artifacts) + rejects/readout.
3. Review and compile a **published reviewed set** (`episode_cards.reviewed.json`) used by runtime by default.
4. Runtime chat builds `context_package v2` (bounded evidence + service verdict) for each turn.
5. An **external model** produces the user-facing reply using that package.
6. A **verifier** checks the reply against delivered evidence/citations; if support is weak, abstain/clarify.
7. Operators manage memory via UI (episodes/atoms/proposals) and “Why this answer?” explainability.

## 3) Component map (where to look)

- Ingest + parsing: `engine/ingest/parser.py`, `engine/ingest/extractor.py`, `engine/ingest/orchestrator.py`
- Memory store + mutation queue: `engine/memory/sqlite_store.py`, `engine/memory/store.py`, `engine/memory/mutation_queue.py`
- Write gates: `engine/write_gate/stage_a.py`, `engine/write_gate/stage_b.py`, `engine/write_gate/prefilter.py`
- Retrieval + verifier: `engine/retrieval/engine.py`, `engine/retrieval/verifier.py`
- Continuity + shared language: `engine/continuity/builder.py`, `engine/continuity/consolidator.py`, `engine/continuity/shared_language.py`
- Runtime + API + adapters: `engine/runtime/session.py`, `engine/runtime/server.py`, `engine/runtime/adapters.py`
- Eval/load/signoff: `engine/runtime/live_eval.py`, `engine/runtime/load_harness.py`, `engine/runtime/gate_harness.py`, `engine/runtime/drift.py`
- CLI/operator tools: `tools/import_memories.py`, `tools/rebuild_continuity.py`, `tools/run_truthset_eval.py`, `tools/run_phase7_signoff.py`, `tools/run_pilot_acceptance.py`, `tools/run_release_gate.py`, `tools/run_full_export_pilot.py`, `tools/run_live_runtime.py`, `tools/preflight.py`, `tools/setup_local.py`

## 4) Feature timeline (changelog-style)

- `v1` (foundation): contracts, config, deterministic ingest normalization, baseline tests.
- `v2` (safety + performance): durable sqlite store, provenance/contradiction handling, write gates, retrieval verifier, eval guardrails.
- `v3` (identity continuity): shared-language registry, continuity builders/backfill, recognition-signal loop, STM/LTM policy model.
- `v4` (operator/runtime hardening): Memory Ops API/UI, phase-7 eval/load/drift/signoff workflow, pilot acceptance packs.
- `v4.1` (modular execution + launch UX): reviewed truthset workflow, quality gates, full-export pilot command, live runtime launch from pilot manifests, Windows wrappers.
- `v4.2` (standalone chat shell, phases 0-7): front-desk routing, STM session layer, context-package v2, bounded follow-up retrieval, runtime chat UI, memory management surfaces, wizard pipeline UI, and trust-v3 release gating.
- `v5` (finite quality cycle): routine-chat memory trigger tuning, visual memory map, simple chat mode, adapter reliability hardening, and one-command setup + preflight packaging path.
- `v5.1` (event/cue hardening): episode-card quality gates, cue-first retrieval ranking, entity/event truthset prompts, and compact model-context packet shaping.

## 5) Key contracts and operational docs

- Project entry: `README.md`
- Public overview: `docs/public/README.md`
- End-to-end guide: `docs/guides/PIPELINE_END_TO_END.md`
- Setup + diagnostics runbook: `docs/OPERATOR_SETUP_AND_DIAGNOSTICS.md`
- API surface: `docs/api/API_MATRIX.md`
- Eval and release gate workflow: `docs/evals/PHASE7_WORKFLOW.md`
- Execution spec: `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md`
- Architecture/spec lineage: `STM_LTM_POLICY_SPEC.md`, `DECISION_LOCK_2026-02-08.md`
- Planned lineage docs (not yet committed): `V4_1_MODULAR_EXECUTION_SPEC.md`, `V4_GAP_CLOSURE_SPEC.md`

## 6) New-dev handoff path

1. Read `README.md`, then this file.
2. Read `docs/api/API_MATRIX.md` and `docs/evals/PHASE7_WORKFLOW.md`.
3. Run `python3 -m pytest -q`.
4. Run one pilot path: `python3 tools/run_full_export_pilot.py --input <conversations.json>`.
5. Launch runtime from produced manifest: `python3 tools/run_live_runtime.py --from-live-manifest runtime/live_runs/live_*/live_manifest.json`.

## 7) Scope boundaries

- Source code + canonical docs are under `engine/`, `tools/`, `docs/`, and root spec files.
- Generated outputs under `runtime/` are operational artifacts (reports/checkpoints), not canonical architecture docs.

## 8) Next scoped cycle

- `v5` is defined as a finite block set in `docs/V5_EXECUTION_AND_FREEZE_PLAN.md`.
- Post-v5 operating mode is feature-freeze by default (bug-fix only) unless a new scoped version is explicitly approved.
