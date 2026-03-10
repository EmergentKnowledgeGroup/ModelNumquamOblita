# Documentation Index

This index is the primary navigation page for `ModelNumquamOblita` docs.
Last Updated: 2026-03-10

Tag legend:
- `[Core]` source-of-truth architecture/policy docs.
- `[Ops]` runbooks, API contracts, and execution workflows.
- `[Guide]` operator/developer how-to guides (actionable end-to-end).
- `[Public]` stakeholder-facing overview and pitch materials.
- `[History]` planning/review lineage and prior design context.

## Start here

- `[Public]` `docs/public/README.md` — public overview (what it is, how it works).
- `[Guide]` `docs/guides/PIPELINE_END_TO_END.md` — end-to-end pipeline guide (GUI + CLI).
- `[Core]` `docs/SYSTEM_MASTER_OVERVIEW.md` — compact handoff map (best first read).
- `[Core]` `docs/MNO_ANO_FULL_DISCONNECTION_SPEC.md` — standalone extraction contract and phased separation plan.
- `[Ops]` `docs/MNO_ANO_FULL_DISCONNECTION_EXECUTION_CHECKLIST.md` — implementation checklist for the standalone split.
- `[Ops]` `docs/MNO_ANO_FULL_DISCONNECTION_BLOCKERBOARD.md` — blocker tracker for disconnect execution.
- `[Core]` `docs/MNO_ANO_OWNERSHIP_INVENTORY.md` — canonical owner map for the standalone MNO lane vs external ANO work.
- `[Core]` `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md` — single execution spec (phases 0–7).
- `[Core]` `docs/EVIDENCE_MEMORY_EPISODE_GLOSSARY.md` — plain-language contract: evidence vs atoms vs episodes.
- `[Core]` `docs/IA_NO_INTEGRATION_PLAN.md` — IA archive → NumquamOblita integration contract and constraints.
- `[Core]` `docs/FORWARD_PATH_MEMORY_ORCHESTRATION.md` — next implementation path and OpenClaw-informed decisions.
- `[Core]` `docs/V5_EXECUTION_AND_FREEZE_PLAN.md` — finite five-block execution plan with hard freeze criteria.
- `[Core]` `docs/EPISODIC_MEMORY_CARD_BUILD_SPEC.md` — event-level memory-card extraction and episode-first retrieval build plan.
- `[Core]` `docs/EVENT_MEMORY_EVENT_CUE_SPEC.md` — event/cue-first recall quality plan (entity/event prompts, compact context, bounded latency).
- `[Ops]` `README.md` — command map, operational policy, and entrypoint links.
- `[Ops]` `docs/OPERATOR_SETUP_AND_DIAGNOSTICS.md` — one-command setup + preflight + first-launch runbook.

## Public / stakeholder docs

- `[Public]` `docs/public/ONE_PAGER.md` — one-page summary.
- `[Public]` `docs/public/CEO_ARCHITECTURE_BRIEF.md` — CEO architecture brief (1 page).
- `[Public]` `docs/public/TEASER.md` — short teaser copy.
- `[Public]` `docs/public/PITCH_OUTLINE.md` — pitch deck outline.
- `[Public]` `docs/public/ARCHITECTURE.md` — architecture + flowcharts (pipeline + runtime).
- `[Public]` `docs/public/DEMO_SCRIPT.md` — 8–12 minute demo runbook.

## Canonical architecture and policy

- `[Core]` `BIO_INSPIRED_MEMORY_SPEC.md` — biological grounding and system intent.
- `[Core]` `ALGORITHM_PIPELINE.md` — ingest/write/retrieve flow.
- `[Core]` `DATA_MODEL_AND_STORAGE.md` — memory object model and persistence contracts.
- `[Core]` `MEMORY_WRITE_GATE.md` — write/update/ignore decision policy.
- `[Core]` `RETRIEVAL_AND_SCORING.md` — retrieval fusion, ranking, abstention.
- `[Core]` `EVALUATION_GUARDRAILS.md` — quality/safety guardrails.
- `[Core]` `STM_LTM_POLICY_SPEC.md` — short-term vs long-term routing policy.
- `[Core]` `DECISION_LOCK_2026-02-08.md` — locked non-negotiable system decisions.

## API and runtime operations

- `[Guide]` `docs/guides/RUNTIME_UI_TOUR.md` — runtime web UI walkthrough (operator workflows).
- `[Ops]` `docs/api/API_MATRIX.md` — runtime endpoint contract and UI/API coupling.
- `[Ops]` `docs/evals/PHASE7_WORKFLOW.md` — truthset/load/drift/signoff + release trust-gate runbook.

## Integrations and UX specs

- `[Core]` `docs/MCP_SERVER_SPEC.md` — self-hosted MCP server spec (tools/resources, guards, packaging, testing).
- `[Core]` `docs/MEMORY_VISUALIZATION_SPEC.md` — Obsidian-style memory visualization spec (graph UX + boundedness + testing).
- `[Core]` `docs/MEMORY_EXPLORATION_MODE_SPEC.md` — zero-seed, low-token memory exploration mode spec (start-here map, guided hops, preference weighting).
- `[Core]` `docs/AUTO_ORGANIZER_WIZARD_SPEC.md` — assistant-led memory organizer wizard spec (typing, dedupe, contradiction queues, reversible proposals).
- `[Core]` `docs/MNO_CAVEMAN_APP_SPEC.md` — unified front-facing MNO app flow from IA import to live runtime.
- `[Ops]` `docs/MNO_CAVEMAN_APP_EXECUTION_CHECKLIST.md` — caveman-proof GUI execution checklist.
- `[Ops]` `docs/MNO_CAVEMAN_APP_BLOCKERBOARD.md` — caveman-proof GUI blocker tracking.
- `[Core]` `docs/MNO_METHOD_MEMORY_DRIFT_GUARDS_SPEC.md` — additive post-stabilization spec for methodology memory, canary/rollback, and drift-triggered maintenance safeguards.

## Queued execution

- `[Ops]` `docs/TODO_POST_MNO_QUEUE.md` — locked queue for work scheduled after MNO stabilization.

## Standalone boundary docs

- `[Core]` `docs/MNO_ANO_COMPATIBILITY_MATRIX.md` — compatibility/deprecation matrix during the staged split.
- `[Guide]` `docs/guides/MONOREPO_TO_STANDALONE_MIGRATION.md` — cutover guide for existing MNO operators moving off the mixed monorepo.
- `[Core]` `docs/MNO_MCP_DESKTOP_GUI_SPEC.md` — native GUI MCP connector spec for the standalone MNO distribution.

## Execution history and planning lineage

- `[History]` `IMPLEMENTATION_BLUEPRINT.md` — implementation scaffold baseline.
- `[History]` `V2_ARCHITECTURE_DECISIONS.md` — v2 decision set.
- `[History]` `V3_IDENTITY_CONTINUITY_UPGRADES.md` — v3 feature expansion.
- `[History]` `V3_ACCEPTANCE_CRITERIA.md` — v3 release/gate expectations.
- `[History]` `V3_FAILURE_CASE_LIBRARY.md` — failure matrix and mitigations.
- `[History]` `numquamoblita-execution-board-plan.md` — PR/phase board.
- `[History]` `CLAUDE_PERSPECTIVE.md` — external model perspective input.

## Generated artifacts (non-canonical docs)

Use these for operational trace/debugging, not as architecture source-of-truth.

- `[Ops]` `runtime/checkpoints/` — step snapshots for context recovery.
- `[Ops]` `runtime/reports/` — PR feedback exports and operational summaries.
- `[Ops]` `runtime/imports/`, `runtime/continuity/`, `runtime/evals/` — run outputs and reports.
- `[Ops]` `runtime/pilot/` — generated when pilot/eval workflows are executed.
