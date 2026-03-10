# Evaluation and Guardrails

## 1. Primary failure to prevent

Confident wrong memory:
- model states a false or unsupported memory with high certainty.

## 2. Key metrics

- `evidence_precision@k`: fraction of recalled atoms with correct source support.
- `recall@k`: fraction of queries where at least one authoritative supporting atom is present in top-`k` retrieval results.
- `false_memory_rate`: unsupported memory claims / total memory claims.
- `abstention_quality`: abstain when uncertain, answer when supported.
- `conflict_handling_score`: correctness when contradictory memories exist.
- `temporal_accuracy`: correctness for time-bound recall.
- `identity_consistency`: stability of recurring self/voice facts over sessions.
- `recognition_alignment`: rate at which recalled memory is rated as self-recognized (`strong`).
- `shared_language_recall`: success rate for context-relevant inside-language retrieval.
- `arc_coherence`: correctness of growth narrative reconstruction.
- `dynamic_continuity`: preservation of recurring relational patterns.
- `retrieval_latency_p95`: response-time guard under scale.
- `cost_per_1k_queries`: operational token/index cost budget.

## 3. Evaluation sets

### Gold recall set
- manually verified memory questions with authoritative source refs.

### Contradiction set
- prompts intentionally targeting known conflicting memories.

### Adversarial set
- leading questions designed to induce hallucinated memory.

### Drift set
- long-session prompts to test consistency under memory volume.

### Recognition set
- prompts with known high-identity callbacks to measure recognition alignment quality.

## 4. Guardrail policies

- no memory claim without source-linked support.
- unresolved conflicts must trigger uncertainty language with citations.
- low-confidence retrieval must trigger abstention/clarification.
- policy logs must capture why recall was accepted or blocked.
- derived continuity layers are assistive and cannot bypass source-evidence contract.

## 5. Runtime enforcement

- pre-response verifier checks every memory claim against pack evidence.
- claim-evidence mismatch forces rewrite or abstention.
- repeated mismatch incidents trigger health alerts.
- budget guardrails enforce bounded retrieval/rerank path by query class.
- deterministic gate suites enforce zero unsupported claims in final response traces.

## 6. Red-team loop

1. run adversarial prompts weekly.
2. collect false-memory incidents.
3. categorize root causes:
   - ingestion error,
   - write-gate error,
   - retrieval/rerank error,
   - generation overreach.
4. patch the failing layer.
5. rerun regression suite before release.

## 7. Release-gate source of truth

Thresholds and pass/fail policy are defined in `V3_ACCEPTANCE_CRITERIA.md`.

## Current implementation status

`PR-09` provides executable gate primitives:
- `engine/runtime/failure_cases.py`: parses failure matrix + must-pass subset from markdown source.
- `engine/runtime/gate_harness.py`: computes gate metrics and returns `PASS|CONDITIONAL|FAIL`.
- `tools/run_gate_harness.py`: CLI harness that writes timestamped JSON/MD gate reports.
