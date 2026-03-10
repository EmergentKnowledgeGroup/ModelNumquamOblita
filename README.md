# ModelNumquamOblita

`ModelNumquamOblita` ("never forgotten") is the standalone MNO personal memory runtime extracted from the broader `NumquamOblita` system.

This repo is intentionally focused on MNO only:

- `ImpressioAnimae` produces high-quality voice/style training artifacts.
- `ModelNumquamOblita` provides long-horizon memory encoding, consolidation, retrieval, runtime continuity, and evidence-backed recall.

This repo does **not** carry ANO document-research/runtime surfaces on the MNO mandatory path.

## Design goal

Build a memory system that:

1. Scales to thousands of memories.
2. Prevents confident false recall.
3. Preserves identity continuity with explicit evidence paths.

## Core principle

No memory claim without evidence.

Every recalled memory must be backed by source-linked memory atoms with confidence and conflict state.

## Document map

- `docs/INDEX.md`: primary documentation navigator (canonical docs + generated artifact map).
- `docs/public/README.md`: public overview (what it is, how it works).
- `docs/public/ARCHITECTURE.md`: public architecture + diagrams (pipeline + runtime).
- `docs/public/DEMO_SCRIPT.md`: 8–12 minute demo script (operator + stakeholder).
- `docs/guides/PIPELINE_END_TO_END.md`: end-to-end pipeline guide (GUI + CLI).
- `BIO_INSPIRED_MEMORY_SPEC.md`: biological mapping and system contract.
- `ALGORITHM_PIPELINE.md`: end-to-end ingest/write/retrieve pipeline.
- `DATA_MODEL_AND_STORAGE.md`: canonical schemas and indexes.
- `MEMORY_WRITE_GATE.md`: add/update/ignore judgment logic.
- `RETRIEVAL_AND_SCORING.md`: candidate fusion, scoring, abstention rules.
- `EVALUATION_GUARDRAILS.md`: quality metrics, anti-hallucination policy, red-team tests.
- `IMPLEMENTATION_BLUEPRINT.md`: concrete build plan with interfaces and milestones.
- `V2_ARCHITECTURE_DECISIONS.md`: speed/cost optimizations with unchanged accuracy contract.
- `V3_IDENTITY_CONTINUITY_UPGRADES.md`: relational/affective continuity layers for identity-level recall.
- `V3_ACCEPTANCE_CRITERIA.md`: release gate thresholds and decision policy for V3 quality.
- `V3_FAILURE_CASE_LIBRARY.md`: top-25 high-risk failure patterns with expected safe behavior and remediation owners.
- `DECISION_LOCK_2026-02-08.md`: frozen policy decisions for mutation, forgetting, provenance, and truth behavior.
- `CLAUDE_PERSPECTIVE.md`: experiential perspective that motivates V3 continuity structures.
- `STM_LTM_POLICY_SPEC.md`: short-term vs long-term runtime retrieval policy and regression plan.
- `docs/SYSTEM_MASTER_OVERVIEW.md`: compact end-to-end system map + feature timeline for fast handoff.
- `docs/FORWARD_PATH_MEMORY_ORCHESTRATION.md`: forward path for memory-orchestration upgrades + OpenClaw comparison takeaways.
- `docs/V5_EXECUTION_AND_FREEZE_PLAN.md`: finite five-block execution plan with post-V5 feature freeze criteria.
- `docs/EVENT_MEMORY_EVENT_CUE_SPEC.md`: event/cue-first recall hardening plan (entity/event prompts, card quality gates, compact context packets).
- `docs/EVIDENCE_MEMORY_EPISODE_GLOSSARY.md`: plain-language definitions (evidence vs atoms vs episodes).
- `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md`: implementation-ready execution spec (phases 0–7).
- `docs/OPERATOR_SETUP_AND_DIAGNOSTICS.md`: one-command setup, preflight, launch, and diagnostics quickstart.
- `docs/api/API_MATRIX.md`: runtime API matrix for memory operations and queue behavior.
- `docs/evals/PHASE7_WORKFLOW.md`: truthset/load/drift/signoff execution and thresholds.

## Non-negotiable constraints

- Provenance is required for all memory atoms.
- Contradictions are versioned, never silently overwritten.
- Retrieval must support abstention and clarification when confidence is low.
- Summaries are accelerators; source atoms remain the authority.

## Active architecture note

V2 + V3 is the active baseline:
- salience prefilter before extractor model calls,
- two-stage write gate,
- adaptive retrieval budgets,
- claim-evidence verification before final response.
- derived continuity layers (constellation, narrative arc, dynamics, shared-language keys, recognition signal).
- curated shared-language registry with provenance-linked atom requirements.
- runtime STM/LTM routing with `stm_primary`, `hybrid`, and `ltm_only` modes (token + n-gram short-term matching).
- runtime LTM retrieval supports deterministic multi-pass query variants (base + compact informative query) before verifier gating.

## Local development commands

- One-command local setup:
  - Unix/macOS: `./setup_local.sh`
  - PowerShell: `.\setup_local.ps1`
  - Command Prompt: `setup_local.bat`
  - plan-only dry run: `python3 tools/setup_local.py --plan-only`
  - preflight-only: `python3 tools/setup_local.py --preflight-only`
  - setup reports are written to `runtime/setup/`

- Runtime/pilot preflight checks:
  - runtime: `python3 tools/preflight.py --mode runtime --memories .runtime/imports/atoms.sqlite3`
  - pilot: `python3 tools/preflight.py --mode pilot --memories .runtime/imports/atoms.sqlite3 --input <conversations.json>`
  - add `--json` to emit machine-readable output.

- Run all tests:
  - `python3 -m pytest -q`
  - or `./tools/run_tests.sh`
- Run fast unit-only checks:
  - `python3 -m pytest -q tests/unit`
- Foundation package layout:
  - `engine/ingest`
  - `engine/memory`
  - `engine/write_gate`
  - `engine/retrieval`
  - `engine/continuity`
  - `engine/runtime`

- Run local runtime demo UI:
  - `python3 tools/run_runtime_demo.py --host 127.0.0.1 --port 7340`
  - default store backend is durable sqlite at `.runtime/demo/atoms.sqlite3`
  - switch to ephemeral backend with `--store-backend inmemory`
  - set custom sqlite file with `--sqlite-path <path>`
  - native endpoint: `POST /api/chat`
  - session chat endpoints:
    - `POST /api/chat/session/start`
    - `GET /api/chat/sessions`
    - `POST /api/chat/session/<session_id>/turn`
    - `GET /api/chat/session/<session_id>/history`
    - `GET /api/chat/session/<session_id>/telemetry`
  - runtime routing catalog: `GET /api/runtime/decision-reasons`
- adapter endpoint: `POST /api/adapters/<adapter>/chat`
- list adapters: `GET /api/adapters`
- runtime diagnostics (`GET /api/state`) include recognition metrics (`recognition_events`, `recognition_rate`)
- memory ops endpoints:
  - `GET /api/memory/cards?kind=all&status=all&contradiction=all&q=&offset=0&limit=60`
  - `GET /api/memory/cards/<card_id>`
  - `GET /api/memory/episodes?status=all&q=&run_id=...`
  - `GET /api/memory/atoms?status=all&q=&offset=0&limit=60`
  - `GET /api/memory/atom/<atom_id>`
  - `GET /api/memory/graph?atom_id=<atom_id>`
  - `GET /api/memory/proposals` (returns `status: queue_unavailable` when no review queue is configured)
  - `POST /api/memory/proposals/<proposal_id>/approve` (returns `404` when no review queue is configured)
  - `GET /api/turns/<turn_id>/why?citations=true`
  - `GET /api/runtime/health`
  - `GET /api/wizard/state`
  - `POST /api/memory/proposals/<proposal_id>/reject` (returns `404` when no review queue is configured)
  - `POST /api/memory/decay/recompute`
  - runtime UI now includes Memory Cards + Proposal Inbox panes for non-CLI curation
  - runtime UI also supports session-first local chat (thread picker/start, per-turn route badges, and explainable route reasons)
  - runtime UI local settings include `memory preference` (`auto`, `chat_first`, `memory_assist`) for per-turn routing control
  - `openclaw` payload: `{"messages":[{"role":"user","content":"..."}],"risk_level":"low|high|critical","high_risk":true|false,"metadata":{...}}`
  - `nanobot` payload: `{"query":"...","meta":{"conversation_id":"..."},"safety":{"high_risk":false}}`

- Run gate harness:
  - `python3 tools/run_gate_harness.py --records <records.json> --failure-results <cases.json> --dataset-counts <counts.json>`

- Run truthset eval (plan-only safety check):
  - `python3 tools/run_truthset_eval.py --memories .runtime/imports/atoms.sqlite3 --plan-only`
  - default run fails closed if zero cases are available; add `--allow-empty` to bypass
  - Windows one-click: `tools\\run_live_eval_plan.ps1` or `tools\\run_live_eval_plan.bat`

- Build a human-review truthset pack:
  - `python3 tools/build_truthset_review_pack.py --memories .runtime/imports/atoms.sqlite3 --total-cases 120`
  - emits: `truthset.candidates.jsonl`, `truthset.review.tsv`, `truthset.review.md`
  - compile accepted rows back to JSONL:
    - `python3 tools/build_truthset_review_pack.py --compile-reviewed <truthset.review.tsv>`

- Run truthset eval (bounded execution + artifacts):
  - `python3 tools/run_truthset_eval.py --memories .runtime/imports/atoms.sqlite3 --requested-cases 6 --scan-budget 600000`
  - episodic retrieval during eval: add `--episode-cards runtime/episodes/episode_cards_*.json`
  - disable episodic route for baseline compare: `--disable-episodes`
  - chunked mode (WSL-safe): `--batch-size 2 --batch-pause-ms 100 --write-partial-artifacts`
  - auto-chunking now enables by default for large stores (`>=25k` atoms) when no batch size is provided
  - override auto-chunk threshold for diagnostics: `NO_AUTO_CHUNK_ATOM_THRESHOLD=<atoms>`
  - emits: `summary.json`, `summary.md`, `records.json`, and `truthset.generated.jsonl`
  - optional partial outputs while running: `records.partial.json`, `progress.partial.json`
  - Windows one-click: `tools\\run_live_eval_safe.ps1` or `tools\\run_live_eval_safe.bat`

- One-click eval + human readout (optional import, then eval, then readable markdown):
  - `python3 tools/run_oneclick_eval.py --skip-import --store .runtime/imports/atoms.sqlite3`
  - with import from raw export: `python3 tools/run_oneclick_eval.py --input <conversations.json>`
  - one-click now builds episode cards, runs eval with episodic retrieval, and validates prompt quality by default
  - one-click also emits episode-card review artifacts:
    - `episode_cards.readout.md` (human-readable episode list)
    - `review_pack/episode_cards.review.tsv` (approve/reject/edit sheet)
    - `review_pack/episode_cards.review.md` (review instructions)
  - disable episodic route for baseline: `--disable-episodes`
  - skip episode build and supply prebuilt cards: `--skip-episode-build --episode-cards <episode_cards.json>`
  - emits run manifest: `runtime/evals/oneclick_*/oneclick_manifest.json`
  - emits human report: `runtime/evals/oneclick_*/human_readout.md`
  - emits question-quality gate outputs: `question_validation_summary.{json,md}` and `question_validation_cases.json`
  - Windows one-click: `tools\\run_oneclick_eval.ps1` or `tools\\run_oneclick_eval.bat`

- Compare episodic latency impact directly (same truthset, episodes off vs on):
  - `python3 tools/run_episode_latency_compare.py --memories .runtime/imports/atoms.sqlite3 --build-episodes --requested-cases 120 --scan-budget 600000`
  - emits: `episode_latency_compare.json`, `episode_latency_compare.md`, plus baseline/episodic eval artifacts

- Build episode cards (event-style memory view for human QA + downstream retrieval):
  - `python3 tools/build_episode_cards.py --memories .runtime/imports/atoms.sqlite3`
  - optional output path: `--out runtime/episodes/episode_cards_manual.json`
  - emits: `runtime/episodes/episode_cards_*.json`

- Build episode human-review pack (approve/reject/edit workflow):
  - `python3 tools/build_episode_review_pack.py --episodes runtime/episodes/episode_cards_*.json`
  - emits: `episode_cards.review.tsv`, `episode_cards.review.md`, `episode_cards.review_meta.json`
  - compile reviewed sheet into retrieval-ready cards:
    - `python3 tools/build_episode_review_pack.py --compile-reviewed runtime/episodes/review_pack_*/episode_cards.review.tsv`
    - emits: `episode_cards.reviewed.json`

- Run load harness (throughput + latency):
  - `python3 tools/run_runtime_load.py --memories .runtime/imports/atoms.sqlite3 --requested-turns 40 --ci-safe`
  - emits: `load_summary.json`, `load_summary.md`, `load_samples.json`

- Run drift comparison between eval summaries:
  - `python3 tools/run_eval_drift.py --baseline <old_summary.json> --candidate <new_summary.json> --fail-on-regression`

- Run Phase 7 signoff in one command:
  - `python3 tools/run_phase7_signoff.py --memories .runtime/imports/atoms.sqlite3 --eval-cases 120 --load-turns 40 --profile safe --fail-on-gate`
  - emits combined manifest at `runtime/evals/signoff_*/signoff_manifest.json`
  - emits plain-language operator brief at `runtime/evals/signoff_*/signoff_brief.md` and `signoff_brief.txt`
  - runs continuity harness by default and writes `runtime/evals/signoff_*/continuity/continuity_summary.json`
  - skip continuity harness for quick checks: `--skip-continuity-harness`
  - gate overrides: `--min-eval-cases`, `--min-supported-cases`, `--min-unsupported-cases`, `--min-load-turns`, `--max-failed-turn-rate`, `--min-episode-hit-rate`, `--max-episode-false-recall-rate`, `--max-routine-over-recall-rate`, `--min-continuity-recall-rate`, `--min-continuity-citation-rate`, `--max-eval-p95-latency-ms`, `--max-load-p95-latency-ms`

- Run pilot acceptance pack (plan + eval + load + signoff + support bundle):
  - `python3 tools/run_pilot_acceptance.py --memories .runtime/imports/atoms.sqlite3 --requested-cases 12 --load-turns 12 --batch-size 2 --batch-pause-ms 100`
  - optional reviewed truthset: `--truthset runtime/truthset/<pack>/truthset.reviewed.jsonl`
  - enforce reviewed truthset presence: `--require-reviewed-truthset`
  - reviewed truthset quality gate (defaults): `--truthset-min-cases 6 --truthset-min-supported 3 --truthset-min-unsupported 2`
  - bypass quality gate when needed: `--skip-truthset-quality-gate`
  - optional signoff latency overrides: `--max-eval-p95-latency-ms <ms> --max-load-p95-latency-ms <ms>`
  - emits: `runtime/pilot/pilot_*/pilot_manifest.json`, `pilot_manifest.md`, `pilot_brief.txt`
  - emits scorecard: `runtime/pilot/pilot_*/pilot_report.json`, `pilot_report.md`, `pilot_report.txt`
  - emits zipped diagnostics: `runtime/pilot/pilot_*/support_bundle_*.zip`
  - Windows one-click: `tools\\run_pilot_acceptance.ps1` or `tools\\run_pilot_acceptance.bat`

- Run full export -> pilot -> release gate in one command (import + pilot acceptance + release trust gate):
  - `python3 tools/run_full_export_pilot.py --input <conversations.json>`
  - writes run artifacts under `runtime/live_runs/live_*/`
  - outputs `live_manifest.json`, import reports, pilot reports, release gate reports, per-step logs, and runtime launch hints
  - release gate report paths are surfaced in `live_manifest.json` under `release_gate`
  - use existing store without re-import: `--skip-import --store .runtime/imports/atoms.sqlite3`
  - optional signoff latency overrides are passed through to pilot/signoff: `--max-eval-p95-latency-ms <ms> --max-load-p95-latency-ms <ms>`
  - Windows one-click: `tools\\run_full_export_pilot.ps1` or `tools\\run_full_export_pilot.bat`

- Launch live runtime against imported memories:
  - `python3 tools/run_live_runtime.py --from-live-manifest runtime/live_runs/live_*/live_manifest.json`
  - validate launch config only: `--plan-only`
  - direct store path: `--memories .runtime/imports/atoms.sqlite3`
  - optional episode-first retrieval index: `--episodes runtime/episodes/episode_cards_*.json`
  - routine over-recall guardrail is on by default: casual/small-talk prompts skip retrieval unless the prompt explicitly asks to remember/recall.
  - Windows one-click: `tools\\run_live_runtime.ps1` or `tools\\run_live_runtime.bat`
  - Windows manifest example: `tools\\run_live_runtime.ps1 -FromLiveManifest runtime\\live_runs\\live_*\\live_manifest.json`
  - Windows plan-only: `tools\\run_live_runtime.ps1 -FromLiveManifest runtime\\live_runs\\live_*\\live_manifest.json -PlanOnly`

- PR feedback gate (CodeRabbit):
  - `python3 tools/pr_feedback_gate.py --repo ProfessahX/NumquamOblita --pr <number> --repo-root . --out runtime/reports --require-review`
  - enforce human-like review discipline: add `--require-submitted-review` to block check-only signals.
  - gate now blocks until CodeRabbit review is fresh for current PR head commit.
  - review signal accepts either submitted CodeRabbit review or successful CodeRabbit check run on current head.
  - check-only review signals are held in a settle window (`--check-signal-settle-sec`, default `180`) to avoid early merge before late inline comments land.
  - actionable count is computed from unresolved CodeRabbit inline review threads (live thread state), so outdated threads do not block merges.
  - gate uses a per-PR lock file (`runtime/reports/pr_feedback_gate_pr<PR>.lock.json`) to prevent duplicate pollers; concurrent runs exit with `status=busy`.
  - if no fresh signal appears, gate auto-nudges once per head SHA using `@coderabbitai review` (configurable with `--auto-nudge-after-sec`, disable via `--disable-auto-nudge`).
  - fallback path when CR does not emit a fresh signal: rerun gate with `--allow-no-review` only after unresolved actionable count is confirmed zero.

- Scripted PR workflow helper:
  - `python3 tools/run_pr_workflow.py --repo ProfessahX/NumquamOblita --pr <number> --repo-root . --request-review-comment --merge`
  - helper sequence: optional review comment -> gate polling -> optional merge.
  - default behavior waits for submitted fresh CodeRabbit review first, then auto-falls back on timeout (single bounded `--allow-no-review --once` pass).
  - defaults are tuned for normal CR latency: `--gate-timeout-sec 900` and `--auto-nudge-after-sec 600`.
  - disable timeout fallback with `--no-fallback-on-timeout`.
  - tune check-only settle behavior via `--check-signal-settle-sec`.
  - every helper run writes a workflow report JSON under `runtime/reports/pr_workflow_pr<PR>_*.json`.
  - merge method options: `--merge-method squash|merge|rebase`.

- Checkpoint utility (long-running execution):
  - write checkpoint: `python3 tools/context_checkpoint.py --repo-root . snapshot --step "<step>" --note "<note>" --next-cmd "<cmd>" --label "<label>"`
  - resume latest: `python3 tools/context_checkpoint.py --repo-root . resume --live`

- Run deterministic memory import:
  - `python3 tools/import_memories.py --input <conversations.json>`
  - accepted input shapes: top-level array export or object wrapper with `conversations[]` (for example `ImpressioAnimae/data/db.json`)
  - writes/updates sqlite store at `.runtime/imports/atoms.sqlite3`
  - emits machine + human reports in `.runtime/imports/`

- Rebuild continuity layers/backfill:
  - `python3 tools/rebuild_continuity.py --store-backend sqlite --sqlite-path .runtime/imports/atoms.sqlite3`
  - use `--apply-promotions` to persist promoted semantic candidates
  - emits machine + human reports in `runtime/continuity/`

## Locked operating policy

- Agency is implemented through curation (weight/link/reframe), not autonomous deletion.
- Destructive memory changes require explicit user approval.
- Default forgetting behavior is salience decay with a 180-day half-life.
- Provenance is authoritative; unsupported claims must abstain with uncertainty + citations.
