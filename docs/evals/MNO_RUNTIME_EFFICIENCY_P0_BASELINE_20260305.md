# MNO Runtime Efficiency P0 Baseline Declaration (2026-03-05)

Source spec: `docs/MNO_RUNTIME_EFFICIENCY_SPEC.md`  
Source blockerboard: `docs/MNO_RUNTIME_EFFICIENCY_BLOCKERBOARD.md`

## Baseline Declaration

- `baseline_commit`: `c99472a38950aeaf2b75f389b5f5637672336edc`
- `baseline_branch`: `origin/main`
- `dataset_id`: `blind_seed_192_20260213/truthset.generated.jsonl`
- `requested_cases`: `30`
- `effective_cases`: `30` per run
- `seed/control`: truthset file fixed (no regeneration)
- `cache_mode`: in-process runtime default (no explicit cache override)
- `environment`: local Linux/WSL, Python 3, mock responder provider
- `concurrency`: default single-process eval runner behavior

## Repeated Runs (3x)

Set variables for reproducible command usage:

```bash
export REPO_ROOT=/path/to/NumquamOblita
export MEMORIES_PATH="${REPO_ROOT}/runtime/stores/no_lyra.sqlite3"
export TRUTHSET_PATH="${REPO_ROOT}/runtime/evals/blind_seed_192_20260213/truthset.generated.jsonl"
```

All runs executed with:

```bash
python3 tools/run_responder_eval.py \
  --memories "${MEMORIES_PATH}" \
  --truthset "${TRUTHSET_PATH}" \
  --requested-cases 30 \
  --scan-budget 500000 \
  --provider mock \
  --out-dir runtime/evals/<run_id>
```

Run IDs:
- `mreb003_resp_truthset_hiScan_20260305_061158`
- `mreb003_resp_truthset_hiScan_r2_20260305_061221`
- `mreb003_resp_truthset_hiScan_r3_20260305_061229`

## Median Metrics (3-run)

- `cases`: `30`
- `decision_accuracy`: `1.0`
- `abstain_precision`: `0.0`
- `false_memory_rate`: `0.0`
- `citation_hit_rate`: `0.0`
- `retrieval_hit_rate`: `0.0`
- `evidence_precision_at_k`: `0.0`
- `junk_rate_at_k`: `1.0`
- `conflict_coverage`: `0.0`
- `retrieval_fanout_avg`: `16.6667`
- `retrieval_fanout_p95`: `20.0`
- `latency_memory_p95_ms`: `194.318`
- `latency_total_p95_ms`: `194.48645200463943`

Per-run metrics (raw):

| run_id | cases | abstain_precision | false_memory_rate | citation_hit_rate | retrieval_hit_rate | evidence_precision_at_k | junk_rate_at_k | conflict_coverage | retrieval_fanout_avg | retrieval_fanout_p95 | latency_p95_ms (total) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mreb003_resp_truthset_hiScan_20260305_061158` | 30 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 0.0 | 16.6667 | 20.0 | 194.4865 |
| `mreb003_resp_truthset_hiScan_r2_20260305_061221` | 30 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 0.0 | 16.6667 | 20.0 | 189.0700 |
| `mreb003_resp_truthset_hiScan_r3_20260305_061229` | 30 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 0.0 | 16.6667 | 20.0 | 200.8768 |

Metric mapping note:
- `latency_p95_ms (total)` corresponds to `summary.json -> latency_ms.total_p95`.
- `retrieval_fanout_avg` and `retrieval_fanout_p95` correspond to `summary.json -> retrieval.avg_retrieved_atoms` and `summary.json -> retrieval.p95_retrieved_atoms`.

## Verdict Summary

- `safety_verdict`: `FAIL`
- `human_quality_verdict`: `FAIL`
- `decision`: `FAIL`
- primary gate failure drivers:
  - `abstain_precision_below_floor`
  - alignment/precision failures on this baseline corpus/provider pairing

## Breach and Waiver Declaration (MREB-005 Contract)

```text
breach_declaration:
  has_breach: true
  breach_types:
    - abstain_precision_below_floor
    - relevance_aligned_hit_rate_below_floor
  stop_ship_required: true
  reason: "Baseline run does not meet strict dual-verdict efficiency quality floors."

waiver_declaration:
  has_waiver: false
  waiver_type: none
  blocker_id: none
  blocker_link: none
  scope: "none"
  expires_at: none
  approver: none
  reason: "none"

final_status: NOT_DONE
```

## Interpretation

- This baseline declaration is complete and usable for comparison.
- Baseline quality is below strict dual-verdict thresholds in this local mock-provider setup.
- Efficiency-only claims are blocked until candidate runs can pass strict gate requirements or a separately approved baseline/provider policy is documented.
