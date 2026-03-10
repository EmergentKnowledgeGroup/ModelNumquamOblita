# Memory Write Gate

## Goal

Accept only high-value, well-supported memory writes.

## Input contract

Each candidate memory includes:
- typed candidate fields,
- extracted evidence snippets,
- source refs,
- context features (recurrence, novelty, identity relevance).

## Decision actions

- `ADD`: create new atom.
- `UPDATE`: attach evidence or revise existing atom version.
- `IGNORE`: reject low-value or low-trust candidate.
- `PROPOSE_EDIT`: suggest canonical/metadata correction for approval queue.
- `PROPOSE_DELETE`: suggest tombstone/delete for approval queue.

## V2 gate architecture

### Stage A: deterministic pre-gate
- very low latency.
- blocks obvious noise before model spend.
- checks:
  - missing/weak provenance,
  - boilerplate/fallback patterns,
  - low salience + low identity relevance,
  - duplicate-by-hash with no new evidence.

### Stage B: judgment model gate
- runs only when Stage A cannot confidently decide.
- outputs:
  - action (`ADD|UPDATE|IGNORE`),
  - calibrated confidence,
  - reason code.

## Scoring dimensions

- `salience`: emotional/goal significance.
- `specificity`: concrete and disambiguated.
- `recurrence`: repeated across sessions/time.
- `identity_relevance`: contributes to stable voice/self-model.
- `trust`: source quality and parser confidence.
- `conflict_risk`: contradiction with strong existing atoms.

## Example decision logic

```text
if trust < min_trust: IGNORE
else if conflict_risk high and evidence weak: IGNORE
else if matches existing canonical atom: UPDATE
else if salience + identity_relevance + specificity >= add_threshold: ADD
else IGNORE
```

## Update policy

- updates never mutate source evidence.
- updates create version links when semantic meaning changes.
- confidence is recalibrated after each update using support and contradiction counts.

## Mutation authority policy

- Runtime/model may autonomously:
  - `ADD`,
  - `UPDATE`,
  - reweight salience/confidence,
  - add links and reframing metadata with lineage.
- Runtime/model may not autonomously:
  - hard delete atoms,
  - edit provenance payload,
  - overwrite contradictory evidence.
- Destructive operations require explicit user approval:
  - approved delete defaults to tombstone first,
  - delayed purge runs after retention window,
  - immediate physical erase is a user-only override path.

## Forgetting policy (default)

- Salience decays with a `180-day` half-life when no reinforcement occurs.
- Decay changes retrieval priority, not source-truth authority.

## Anti-noise policy

Reject candidates that are:
- generic filler,
- single-use low-signal phrasing,
- tool/system boilerplate,
- policy fallback templates.

## Auditing

Every gate decision logs:
- candidate id,
- gate stage used (`A` or `B`),
- chosen action,
- score breakdown,
- reason code,
- timestamp.

## Current implementation status

`PR-04` implements Stage-A in code:
- `engine/write_gate/prefilter.py`: deterministic salience + provenance scoring.
- `engine/write_gate/stage_a.py`: Stage-A `ADD|UPDATE|IGNORE` decisions.
- `tests/unit/test_write_gate_stage_a.py`: FC-06/07/09 regression coverage.

`PR-05` implements Stage-B + review queue in code:
- `engine/write_gate/stage_b.py`: deterministic Stage-B adapter and review-proposal decisions.
- `engine/memory/mutation_queue.py`: proposal queue (`PROPOSE_EDIT|PROPOSE_DELETE`) with approval-required apply.
- `engine/memory/store.py`: `tombstone + delayed purge` execution with provenance events.
