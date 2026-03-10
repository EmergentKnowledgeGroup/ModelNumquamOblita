# Algorithm Pipeline

## Overview

Pipeline stages:

1. Parse and segment source data.
2. Salience prefilter (deterministic triage).
3. Generate candidate memory atoms (model).
4. Two-stage write gate (`ADD`, `UPDATE`, `IGNORE`, proposal paths).
5. Dedupe + contradiction handling.
6. Consolidation, derived continuity synthesis, and decay.
7. Retrieval, verification, and response gating.

## Stage 1: Parse and segment

Inputs:
- conversation exports (`json`)
- auxiliary docs (`md`, `txt`)

Outputs:
- normalized turns with:
  - `source_id`
  - `message_id`
  - `timestamp`
  - `role`
  - clean text
  - conversation metadata

## Stage 2: Salience prefilter

Purpose:
- reduce model cost by filtering low-value segments before extraction.

Signals:
- novelty,
- emotional intensity,
- identity relevance,
- recurrence cues,
- explicit user preference/fact markers.

Output:
- `high_value_segments` for model extraction,
- `ignored_segments` with reason codes.

## Stage 3: Candidate atom generation

Extractor model proposes typed candidates with strict schema:
- memory type
- canonical text
- entities/topics/time cues
- affective tags
- evidence pointers

No free-form writes accepted.

## Stage 4: Two-stage write gate

Stage A (deterministic):
- fast threshold/rule checks reject obvious low-trust noise.

Stage B (judgment model):
- runs only for ambiguous candidates.
- returns `ADD`, `UPDATE`, `IGNORE`, `PROPOSE_EDIT`, or `PROPOSE_DELETE`.

For each candidate:
- score salience, recurrence, identity relevance, specificity, and contradiction risk.
- output:
  - action: `ADD` | `UPDATE` | `IGNORE` | `PROPOSE_EDIT` | `PROPOSE_DELETE`
  - confidence
  - rationale code

Proposal actions are not applied directly:
- they enter a mutation review queue,
- destructive changes require explicit user approval.

## Stage 5: Canonicalization and conflict handling

- merge near-duplicates into canonical atoms.
- if contradiction detected:
  - preserve both atoms,
  - mark status (`conflicted`, `superseded`, `active`),
  - update contradiction graph.

## Stage 6: Consolidation job ("sleep pass")

Scheduled batch process:
- promote repeated episodic patterns into semantic facts.
- derive `dynamic_pattern` structures from repeated interaction sequences.
- derive `constellation` clusters from temporal + topical + affective linkage.
- derive `narrative_arc` structures from ordered state transitions.
- refresh `shared_language_key` registry from high-identity callbacks.
- ingest `recognition_event` telemetry into retrieval weighting.
- down-rank stale or weakly supported atoms.
- refresh support counts and confidence calibration.

## Stage 7: Retrieval

Given a query/context:

1. interpret cues (entities, intent, temporal window, emotion).
2. fetch candidates from:
   - lexical index,
   - vector index,
   - time index,
   - relation graph.
3. fuse and rerank with context profile (`factual|emotional|creative|mixed`).
4. expand candidates via constellations and active narrative arcs (budget-bounded).
5. inject matched shared-language keys and relevant dynamic patterns.
6. build a compact evidence pack.
7. run claim-evidence verifier.
8. apply confidence gate:
   - respond normally if high confidence,
   - otherwise abstain or ask clarifying question with citations to the nearest supporting evidence.

## Deterministic guarantees

- all claims trace to source refs.
- memory pack is serializable and inspectable.
- thresholds are config-driven and auditable.
- retrieval and reranking remain budget-bounded per request.
