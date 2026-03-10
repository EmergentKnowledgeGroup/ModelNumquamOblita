# Phase 7 Eval Workflow

This workflow adds reproducible quality and performance gates for runtime releases.

## Inputs
- Memory source: sqlite (`.sqlite3`, `.db`) or `memories.json`
- Optional: manually curated `truthset.jsonl`

## Build reviewed truthset (recommended for pilot)
Commands:
- generate review pack:
  - `python3 tools/build_truthset_review_pack.py --memories <store_or_json> --total-cases 120`
- review in spreadsheet and mark `status=ACCEPT|REJECT`
- compile accepted rows:
  - `python3 tools/build_truthset_review_pack.py --compile-reviewed <truthset.review.tsv>`

Artifacts:
- `truthset.candidates.jsonl`
- `truthset.review.tsv`
- `truthset.review.md`
- `truthset.reviewed.jsonl`

## Build known-truth pack (phase F)
Command:
- `python3 tools/build_known_truth_eval_pack.py --memories <store_or_json> --cases 120 --fixture-mode trust-v3`

Artifacts:
- `truthset.known_truth.jsonl`
- `known_truth_summary.json`
- `known_truth_summary.md`

## Track A: Truthset eval
Command:
- `python3 tools/run_truthset_eval.py --memories <store_or_json> --requested-cases 120 --scan-budget 600000`
- optional episodic retrieval path:
  - `--episode-cards runtime/episodes/episode_cards_*.json`
  - disable for baseline compare: `--disable-episodes`
- default fixture mode is `trust-v3` (`supported_recall`, `narrative_recall`, `contradiction_pressure`, `routine_chat`, `timeline_recall`, `confidence_guardrail`, `unsupported_probe`, `unsupported_pressure`)
- set `--fixture-mode basic` for legacy fixture behavior
- default behavior fails closed when zero cases are available (`exit 2`)
- use `--allow-empty` to explicitly permit zero-case exits (`exit 0`)
- for constrained hosts, enable chunking:
  - `--batch-size 2 --batch-pause-ms 100 --write-partial-artifacts`
- for large stores, auto-chunking is enabled when no `--batch-size` is provided (`>=25k` atoms by default)
- diagnostic override for auto-chunk threshold:
  - `NO_AUTO_CHUNK_ATOM_THRESHOLD=<atoms>`

Plan-only preflight:
- `python3 tools/run_truthset_eval.py --memories <store_or_json> --plan-only`

Artifacts:
- `summary.json`
- `summary.md`
- `records.json`
- `truthset.generated.jsonl`
- `truthset.case_counts.json`
- optional partials during chunked runs:
  - `records.partial.json`
  - `progress.partial.json`

Key metrics:
- `decision_accuracy`
- `citation_hit_rate`
- `retrieval_hit_rate`
- `abstain_precision`
- `false_memory_rate`
- `routine_over_recall_rate`
- `episode_hit_rate`
- `episode_false_recall_rate`
- `p95_latency_ms`
- memory-mode latency breakdown:
  - `memory_mode_case_counts`
  - `memory_mode_avg_latency_ms`
  - `memory_mode_p95_latency_ms`

## Track B: Load/perf harness
Command:
- `python3 tools/run_runtime_load.py --memories <store_or_json> --requested-turns 40 --scan-budget 600000`

CI-safe mode:
- add `--ci-safe` (caps turns to 12)

Artifacts:
- `load_summary.json`
- `load_summary.md`
- `load_samples.json`

## Track C: Drift report
Command:
- `python3 tools/run_eval_drift.py --baseline <old_summary.json> --candidate <new_summary.json> --fail-on-regression`

Artifacts:
- `drift_report.json`
- `drift_report.md`

## One-command signoff
Command:
- `python3 tools/run_phase7_signoff.py --memories <store_or_json> --eval-cases 120 --load-turns 40 --profile safe --fail-on-gate`
- optional fixture mode override: `--fixture-mode basic|trust-v2|trust-v3`
- continuity harness runs by default (long-thread recall probes with citation checks)
- skip continuity for fast local checks: `--skip-continuity-harness`

Artifacts:
- `signoff_manifest.json`
- `signoff_manifest.md`
- `signoff_brief.md`
- `signoff_brief.txt`
- nested `eval/`, `load/`, and optional `drift/` artifacts
- nested `continuity/` artifacts (`continuity_summary.json`, `continuity_checks.json`)

## Pilot acceptance pack
Command:
- `python3 tools/run_pilot_acceptance.py --memories <store_or_json> --requested-cases 12 --load-turns 12 --batch-size 2 --batch-pause-ms 100`
- Optional reviewed truthset:
  - `--truthset runtime/truthset/<pack>/truthset.reviewed.jsonl`
  - `--require-reviewed-truthset` to fail fast when none is provided/auto-detected
  - quality gate defaults: `--truthset-min-cases 6 --truthset-min-supported 3 --truthset-min-unsupported 2`
  - bypass gate: `--skip-truthset-quality-gate`
- Optional trust regression gate:
  - `--trust-baseline-summary <baseline_summary.json>`
  - `--require-trust-regression-gate` to fail fast when baseline is missing

Artifacts:
- `pilot_manifest.json`
- `pilot_manifest.md`
- `pilot_brief.txt`
- `pilot_report.json`
- `pilot_report.md`
- `pilot_report.txt`
- `support_bundle_*.zip` (logs + eval/load/signoff artifacts)

## Release trust gate (required before release merge)
Command:
- `python3 tools/run_release_gate.py --pilot-manifest <pilot_manifest.json> --require-trust-regression`

Artifacts:
- `release_gate/release_gate_report.json`
- `release_gate/release_gate_report.md`

Gate rule:
- release is blocked unless pilot decision is `PASS`, signoff decision is `PASS`, and trust regression is enabled+passing.

One-command path:
- `tools/run_full_export_pilot.py` now runs this release gate automatically after pilot acceptance and records outputs in `live_manifest.json` (`release_gate.*`).

## Release thresholds
Profile `safe` (default):
- `false_memory_rate <= 0.02`
- `episode_false_recall_rate <= 0.00`
- `routine_over_recall_rate <= 0.05`
- `episode_hit_rate >= 0.00` (enforced only when `episode_supported_cases > 0`)
- `citation_hit_rate >= 0.98`
- `decision_accuracy >= 0.80`
- `retrieval_hit_rate >= 0.80`
- `abstain_precision >= 0.60` (skipped when `unsupported_cases == 0`)
- `eval cases >= 6` (`supported >= 3`, `unsupported >= 2`)
- `load turns >= 4` with `failed_turn_rate <= 0.20`
- `eval p95 latency <= 6000 ms`
- `load p95 latency <= 6500 ms`
- `continuity recall_rate >= 0.75`
- `continuity citation_rate >= 0.60`

Profile `strict`:
- `false_memory_rate <= 0.02`
- `episode_false_recall_rate <= 0.00`
- `routine_over_recall_rate <= 0.02`
- `episode_hit_rate >= 0.00` (enforced only when `episode_supported_cases > 0`)
- `citation_hit_rate >= 0.98`
- `decision_accuracy >= 0.90`
- `retrieval_hit_rate >= 0.90`
- `abstain_precision >= 0.80`
- `eval cases >= 20` (`supported >= 10`, `unsupported >= 5`)
- `load turns >= 20` with `failed_turn_rate <= 0.10`
- tighter latency (`eval <= 2500 ms`, `load <= 3000 ms`)
- tighter continuity (`recall_rate >= 0.90`, `citation_rate >= 0.85`)

Optional gate overrides are available on `tools/run_phase7_signoff.py`:
- `--min-eval-cases`
- `--min-supported-cases`
- `--min-unsupported-cases`
- `--min-load-turns`
- `--max-failed-turn-rate`
- `--min-decision-accuracy`
- `--min-retrieval-hit-rate`
- `--min-abstain-precision`
- `--min-episode-hit-rate`
- `--max-episode-false-recall-rate`
- `--max-routine-over-recall-rate`
- `--max-eval-p95-latency-ms`
- `--max-load-p95-latency-ms`

## PR workflow reliability gate
Use these when shipping phase changes tied to eval behavior:

- direct gate:
  - `python3 tools/pr_feedback_gate.py --repo ProfessahX/NumquamOblita --pr <number> --repo-root . --timeout-sec 900 --poll-sec 30`
- one-command helper:
  - `python3 tools/run_pr_workflow.py --repo ProfessahX/NumquamOblita --pr <number> --repo-root . --request-review-comment --merge`
  - fallback is enabled by default; disable only if needed:
    - `--no-fallback-on-timeout`

Operational notes:
- gate requires unresolved actionable count to be zero.
- wait for one full submitted CodeRabbit review on the initial PR head.
- after applying CodeRabbit fixes, use post-fix no-resubmit flow:
  - push fixes,
  - run one-pass gate (`--allow-no-review --once --disable-auto-nudge`),
  - do not require a fresh submitted CodeRabbit review on the new fix head before merge.
- actionable threads already marked by CodeRabbit as “addressed in commit” are ignored by the gate to avoid stale thread deadlocks.
- gate resolves actionable status from live thread state, so outdated threads do not block merges.
- gate accepts either a fresh CodeRabbit review or a successful CodeRabbit check on current PR head.
- check-only signals are held for a short settle window (`--check-signal-settle-sec`, default `180`) before pass.
- if fresh CR signal stalls, gate can auto-nudge once per head SHA (`--auto-nudge-after-sec`, default `600`).
- in no-resubmit mode, merge is allowed when unresolved actionable count is zero and local validations are green.
- gate polling is single-instance per PR (lock file) to prevent duplicate pollers.
- helper emits a per-run workflow report at `runtime/reports/pr_workflow_pr<PR>_*.json`.

## Execution checkpoints
- write checkpoint:
  - `python3 tools/context_checkpoint.py --repo-root . snapshot --step "<step>" --note "<note>" --next-cmd "<cmd>" --label "<label>"`
- restore latest:
  - `python3 tools/context_checkpoint.py --repo-root . resume --live`

## WSL stability notes
- Eval and load commands are scan-budget bounded.
- `--plan-only` is zero-risk and does not construct runtime threads.
- `run_live_eval_safe.ps1` now runs evals in small batches by default (`batch-size=2`).
- `run_truthset_eval.py` now auto-enables chunking on large stores unless explicitly overridden.
- Chunked eval writes partial artifacts so failures still preserve diagnostic evidence.
- `run_truthset_eval.py` can run with episode-card retrieval enabled for direct episodic latency verification.
- `run_episode_latency_compare.py` runs off/on episodic eval against the same truthset and writes a delta report.
- Runtime server tests now use explicit server-thread join on shutdown.

## Adapter context-package hardening checks
- Covered by integration tests:
  - `tests/integration/test_runtime_adapter_endpoints.py`
  - `tests/integration/test_runtime_server.py`
- Guardrail expectation:
  - context-package failures return generic API errors only (`context package failed`, `adapter context package failed`).
  - internal exception text is not returned to clients.
