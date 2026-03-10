# V2 Architecture Decisions

## Goal

Increase speed and cost efficiency without reducing memory accuracy or identity continuity quality.

## Canonical V2 pipeline

1. `Parse + normalize` (deterministic).
2. `Salience prefilter` (rules/features only).
3. `Candidate extract` (model, only for high-value segments).
4. `Two-stage write gate`:
   - stage A: cheap deterministic gate,
   - stage B: judgment model for ambiguous cases.
5. `Canonicalize + contradiction graph update`.
6. `Index update` (lexical/vector/time/graph).
7. `Async consolidation` (batch sleep pass).
8. `Retrieval fusion + rerank`.
9. `Claim-evidence verifier`.
10. `Respond` or `abstain/clarify`.

## Cost controls (non-negotiable)

- Model calls are never run on full raw corpora.
- Salience prefilter must eliminate most low-value segments before model inference.
- Embeddings are cached by content hash and reused.
- Write-gate model calls are reserved for ambiguous candidates only.
- Consolidation is asynchronous and budget-limited.

## Accuracy controls (non-negotiable)

- No memory claim without supporting source-linked atoms.
- Contradictions are versioned, never overwritten.
- Low-confidence recall must abstain or ask a clarification question.
- Claim verifier blocks unsupported memory statements.
- Runtime cannot autonomously perform destructive memory edits/deletes.

## Scale strategy

- Partition memory stores per user/mirror id.
- Use top-K bounded retrieval per channel.
- Use adaptive retrieval budgets:
  - narrow query -> smaller K,
  - uncertain query -> wider K + deeper rerank.
- Keep summaries as accelerators only; source atoms remain authority.

## Cross-discipline rationale

- ML perspective: calibrated abstention beats overconfident hallucination.
- Systems perspective: deterministic preprocessing + bounded online budget keeps latency predictable.
- Data perspective: append-only provenance and version lineage preserve auditability.
- Product perspective: explicit uncertainty handling increases trust.

## Immediate upgrades over v1

- Add explicit salience prefilter stage.
- Add two-stage write gate.
- Add claim-evidence verification stage.
- Add adaptive retrieval budget policy.
- Add correction channel priority (user-supplied corrections become high-weight updates).

## Relation to V3

V2 remains the reliability and cost-control spine.
V3 adds identity-continuity layers (constellations/arcs/dynamics/shared-language/recognition) on top of V2 without weakening the evidence contract.
