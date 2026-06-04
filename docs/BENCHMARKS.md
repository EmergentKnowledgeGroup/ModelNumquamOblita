# Benchmarks

MNO is built around a simple promise: memory claims should come with evidence.

The benchmark numbers here focus on that promise. They measure whether MNO can retrieve the source material needed to support a memory answer. They are retrieval and source-support scores, not final natural-language answer scores.

That distinction matters. A system can retrieve the right source and still write a bad answer. It can also write a smooth answer without enough evidence. MNO is trying to make the evidence side visible and inspectable first.

## Snapshot

| Benchmark | Scope | Cases | Key result |
| --- | --- | ---: | --- |
| LongMemEval-S | retrieval/source support | 500 | R@5 `0.9660`, R@10 `0.9760`, source in store `1.0000` |
| LoCoMo | retrieval/source support | 1,986 questions, 1,982 retrieval-eligible | eligible R@1 `0.6075`, R@5 `0.8491`, R@10 `0.9258`, MRR `0.7157` |

These runs were produced on April 8, 2026 from the dev evaluation harness, then reduced into public-safe aggregate summaries. Raw benchmark datasets, per-case outputs, local paths, questions, and source identifiers are intentionally not committed.

## LongMemEval-S

Run: `longmemeval_retrieval_full_auto_core_ranksprint_restore_20260408`

Public aggregate: [longmemeval-retrieval-summary-20260408.json](benchmarks/results/longmemeval-retrieval-summary-20260408.json)

| Metric | Value |
| --- | ---: |
| Cases | `500` |
| Source recall at 5 | `0.9660` |
| Source recall at 10 | `0.9760` |
| Source nDCG at 5 | `0.9067` |
| Source nDCG at 10 | `0.9038` |
| Gold source present in store | `1.0000` |
| Gold source shortlisted | `0.9800` |
| Misses at 5 | `17` |
| Misses with no gold source in store | `0` |

## LoCoMo

Run: `locomo_retrieval_full_auto_ann_source_support_20260408`

Public aggregate: [locomo-retrieval-summary-20260408.json](benchmarks/results/locomo-retrieval-summary-20260408.json)

The LoCoMo run includes 1,986 completed questions. Four had no gold source identifier, so the clearest comparison line is the retrieval-eligible subset.

| Metric | All questions | Retrieval-eligible |
| --- | ---: | ---: |
| Cases | `1,986` | `1,982` |
| Source recall at 1 | `0.6062` | `0.6075` |
| Source recall at 5 | `0.8474` | `0.8491` |
| Source recall at 10 | `0.9240` | `0.9258` |
| MRR | `0.7143` | `0.7157` |
| Gold source present in store | `0.9980` | `1.0000` |
| Gold source shortlisted | `0.9527` | `0.9546` |

## How To Read This

These numbers say: when a memory benchmark asks about something from prior context, MNO is usually able to recover the right source evidence into the retrieval window.

They do not say: MNO has solved all long-term memory, all reasoning, or all answer generation.

That is why the repo separates source-support benchmarks from final answer scoring. The source-support layer is the foundation MNO needs before it can responsibly ask an answer model to speak.

## Reproducing

The public repo does not redistribute LongMemEval or LoCoMo data. The aggregate files above are public-safe reductions of local dev harness outputs; they are meant to prove the reported run without publishing raw benchmark content.

A polished public harness and dataset setup guide should be added separately once the benchmark-data instructions and answer-level scoring path are ready for outside contributors.

Answer-level benchmark scoring is tracked separately from these retrieval/source-support scores. Until that is published, do not describe these numbers as final answer F1 or final judge scores.
