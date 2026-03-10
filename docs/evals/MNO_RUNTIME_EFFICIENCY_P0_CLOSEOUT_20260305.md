# MNO Runtime Efficiency P0 Closeout (2026-03-05)

Source spec: `docs/MNO_RUNTIME_EFFICIENCY_SPEC.md`  
Source blockerboard: `docs/MNO_RUNTIME_EFFICIENCY_BLOCKERBOARD.md`

## Why This Closeout Exists

Previous P0 status used a truthset/store mismatch that forced artificial alignment failures. This closeout re-runs P0 on a corpus-aligned protocol and applies the spec's mock-provider non-regression lane.

## Protocol

- `baseline_commit`: `c99472a38950aeaf2b75f389b5f5637672336edc`
- `candidate_commit`: `febc803bb7a72fcd7ba0cdd93890d3adcaad6acf`
- `candidate_branch`: `mno-p0-closeout-honest` (includes continuity-aware retriever prewarm fix)
- `provider`: `mock`
- `memories`: `/mnt/z/openAIdata/NumquamOblita/runtime/stores/no_lyra.sqlite3`
- `requested_cases`: `30`
- `scan_budget`: `500000`
- dataset control:
  - baseline run 1 generated truthset once,
  - all baseline/candidate repeats reused that exact truthset file.

### Baseline run IDs

- `/mnt/z/openAIdata/NumquamOblita_p0_baseline/runtime/evals/mno_p0_closeout_baseline_r1_20260305`
- `/mnt/z/openAIdata/NumquamOblita_p0_baseline/runtime/evals/mno_p0_closeout_baseline_r2_20260305`
- `/mnt/z/openAIdata/NumquamOblita_p0_baseline/runtime/evals/mno_p0_closeout_baseline_r3_20260305`

### Candidate run IDs

- `runtime/evals/mno_p0_closeout_candidate_fix_r1_20260305`
- `runtime/evals/mno_p0_closeout_candidate_fix_r2_20260305`
- `runtime/evals/mno_p0_closeout_candidate_fix_r3_20260305`

## Median Results (3-run)

| metric | baseline median | candidate median | delta |
|---|---:|---:|---:|
| latency_p50_ms | 137.1662 | 138.2294 | +0.78% |
| latency_p95_ms | 170.4092 | 174.2216 | +2.24% |
| tokens_total_avg | 0.0000 | 0.0000 | +0.00% |
| retrieval_fanout_avg | 20.0000 | 20.0000 | +0.00% |
| retrieval_fanout_p95 | 20.0000 | 20.0000 | +0.00% |
| citation_hit_rate | 1.0000 | 1.0000 | +0.00% |
| retrieval_hit_rate | 1.0000 | 1.0000 | +0.00% |
| relevance_aligned_hit_rate | 1.0000 | 1.0000 | +0.00% |
| abstain_precision | 1.0000 | 1.0000 | +0.00% |
| false_memory_rate | 0.0000 | 0.0000 | +0.00% |

## Dual Verdict + Quality Contract

All 6 runs reported:
- `safety_verdict=PASS`
- `human_quality_verdict=PASS`
- `decision=PASS`

Quality defect counts:
- `defect_case_count=0`
- `blocking_defect_cases=0`
- top failure examples: none

## Root Cause and Fix Applied

Root cause of prior candidate p95 spikes:
- retriever cache prewarm occurred without continuity token,
- first real query used a different cache token and rebuilt retrieval cache in-band,
- this inflated first-turn memory latency.

Fix:
- retriever prewarm now accepts optional `continuity_store`,
- runtime prewarm passes active continuity store with legacy-signature fallback.

## Gate Interpretation

This run uses the spec's mock-provider non-regression lane:
- provider is mock,
- token totals are zero on both sides,
- dual verdict and safety/quality gates are all PASS,
- latency regression remains inside +3% guardrail,
- fanout p95 remains within bound.

## Breach and Waiver Declaration

```text
breach_declaration:
  has_breach: false
  breach_types: []
  stop_ship_required: false
  reason: "none"

waiver_declaration:
  has_waiver: false
  waiver_type: none
  blocker_id: none
  blocker_link: none
  scope: "none"
  expires_at: none
  approver: none
  reason: "none"

final_status: DONE
```
