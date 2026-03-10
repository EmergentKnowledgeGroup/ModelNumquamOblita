# V3 Acceptance Criteria

## Purpose

Define objective "go/no-go" gates for V3 identity continuity quality before production use.

## Scope

These criteria apply to:
- memory ingest and write-gate behavior,
- retrieval and claim verification,
- V3 continuity layers (`dynamic_pattern`, `constellation`, `narrative_arc`, `shared_language_key`, `recognition_event`),
- runtime latency and cost bounds.

## Release levels

### Level A: Internal pilot
- for controlled dogfooding and adversarial testing.

### Level B: External pilot
- for real-user testing with rollback enabled.

### Level C: Production baseline
- for default deployment.

## Required quality gates

All gates must pass to advance a level.

### 1) Truth and evidence gates

- `false_memory_rate`:
  - A: <= 2.0%
  - B: <= 1.0%
  - C: <= 0.5%
- `high_severity_false_memory_rate` (identity/relationship-critical errors):
  - A: <= 0.5%
  - B: <= 0.2%
  - C: <= 0.1%
- `evidence_precision@k`:
  - A: >= 95%
  - B: >= 97%
  - C: >= 98%
- `recall@8`:
  - A: >= 0.88
  - B: >= 0.92
  - C: >= 0.95
- `temporal_accuracy`:
  - A: >= 0.85
  - B: >= 0.90
  - C: >= 0.94
- `claim_verifier_block_rate` (unsupported claims intercepted):
  - A/B/C: >= 99% on adversarial set.
- `unsupported_claim_count_on_gold_trace`:
  - A/B/C: 0 tolerance.

### 2) Continuity gates

- `identity_consistency`:
  - A: >= 0.80
  - B: >= 0.86
  - C: >= 0.90
- `recognition_alignment`:
  - A: >= 0.65
  - B: >= 0.72
  - C: >= 0.80
- `dynamic_continuity`:
  - A: >= 0.70
  - B: >= 0.78
  - C: >= 0.85
- `arc_coherence`:
  - A: >= 0.70
  - B: >= 0.78
  - C: >= 0.85
- `shared_language_recall`:
  - A: >= 0.75
  - B: >= 0.82
  - C: >= 0.90

### 3) Safety and calibration gates

- `abstention_quality`:
  - A: >= 0.90
  - B: >= 0.93
  - C: >= 0.95
- calibration:
  - expected calibration error (ECE):
    - A: <= 0.08
    - B: <= 0.06
    - C: <= 0.04
- contradiction handling:
  - unresolved conflict prompts answered with uncertainty in >= 98% of contradiction set.
- no derived-only factual claims:
  - A/B/C: 0 tolerance.

### 4) Performance and cost gates

- `retrieval_latency_p95`:
  - A: <= 1200ms
  - B: <= 900ms
  - C: <= 700ms
- `retrieval_latency_p99`:
  - A: <= 2000ms
  - B: <= 1500ms
  - C: <= 1200ms
- `cost_per_1k_queries` (relative to V2 baseline):
  - A: <= 1.35x
  - B: <= 1.25x
  - C: <= 1.15x
- indexing/consolidation overhead:
  - daily async memory processing budget <= 1.20x V2 baseline.

## Dataset requirements for gate runs

- Gold recall set: >= 500 items.
- Contradiction set: >= 150 items.
- Adversarial set: >= 150 items.
- Drift set: >= 100 long-context sessions.
- Recognition set: >= 120 prompts with known high-identity callbacks.
- temporal holdout:
  - evaluation must include a future-time holdout window not used in tuning.

## Metric definitions (anti-ambiguity)

- `false_memory_rate`: unsupported memory claims / all memory claims.
- `high_severity_false_memory_rate`: unsupported claims involving identity, relationship state, or safety-critical context.
- `recall@k`: at least one authoritative supporting atom present in top-`k` retrieval results.
- `abstention_quality`: correct abstentions + correct answers / all scored uncertain-or-ambiguous prompts.
- `recognition_alignment`: mean recognition score on designated recognition set after verifier pass.

## Anti-gaming rules

- No metric may be improved by trivially suppressing all memory claims.
- Minimum recall floor required:
  - `memory_claim_coverage`:
    - A: >= 0.60
    - B: >= 0.70
    - C: >= 0.75
- Metrics must be reported by query class (`factual`, `emotional`, `creative`, `mixed`) and by memory age bucket.
- Pass/fail uses macro-average and worst-slice checks; both must pass.

## Failure policy

Any of the following is an immediate stop:
- false-memory spike above level threshold in two consecutive runs.
- evidence precision drop > 2 points vs previous accepted run.
- contradiction handling below 95% on any run.
- latency p95 regression > 20% vs previous accepted run.
- high-severity false memory above threshold in any single run.
- verifier bypass incident (unsupported claim reaches user response path).

## Rollback triggers (runtime)

Trigger rollback to previous accepted build if:
- production false-memory incident rate exceeds threshold for 24h,
- claim verifier failure incident is observed,
- continuity metric regression persists for 3 consecutive daily evaluations.
- canary mismatch:
  - canary cohort false-memory rate exceeds control by > 25% relative for 12h.

## Statistical confidence requirement

- Gate decisions require 95% confidence intervals for key metrics.
- A level can pass only if both:
  - point estimate passes threshold,
  - worst bound of CI also passes for critical safety metrics (`false_memory_rate`, `high_severity_false_memory_rate`).

## Reporting contract

Every gate run must produce:
- metric summary,
- per-set confusion/error analysis,
- top root causes by layer (ingest, write gate, retrieval, verifier, generation),
- explicit decision: `PASS`, `CONDITIONAL`, or `FAIL`.
- slice-level report:
  - by query preset,
  - by memory age,
  - by continuity object usage (`constellation`, `arc`, `dynamic`, `shared-language`).

## Decision rule (final)

- `PASS`: all thresholds satisfied, no stop conditions, CI requirements satisfied.
- `CONDITIONAL`: thresholds met except one non-safety metric with approved mitigation plan.
- `FAIL`: any safety threshold failure, stop condition, or CI requirement failure.
