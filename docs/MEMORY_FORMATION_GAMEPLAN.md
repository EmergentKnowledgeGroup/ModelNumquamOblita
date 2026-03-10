# Memory Formation Gameplan

Status: Canonical execution plan (referenced by pipeline spec)  
Last Updated: 2026-02-15  

This document describes how we reliably turn raw conversation exports into **event-grade episode memory** without drifting into snippet-based “random prompt” behavior.

## 1) Problem statement

When memory formation over-indexes on single turns (“atoms”) instead of coherent events (“episodes”), downstream surfaces degrade:

- truthset questions read like fragments instead of memories,
- retrieval hits feel random (“why did it bring up *that*?”),
- users see unnatural recall phrasing and weak anchors,
- verification can pass on technically-cited but semantically irrelevant evidence.

Root cause: treating turn-level evidence as if it were event-level memory.

## 2) Goal contract

Formation is “working” only if:

- **episodes are the default recall unit** for event prompts,
- every promoted episode is multi-turn and has concrete anchors,
- “supported” eval prompts are seeded from promoted episodes (not random atoms),
- evidence payloads remain bounded and citation-correct,
- routine chat stays lightweight (no over-recall).

North star: `docs/NEAR_PERFECT_GOAL.md`.

## 3) Canonical layers (do not drift)

See: `docs/EVIDENCE_MEMORY_EPISODE_GLOSSARY.md`

- Evidence atoms: immutable provenance-backed units in sqlite.
- Episode cards: curated event-grade artifacts built from multiple atoms.
- Context package v2: bounded evidence + deterministic service verdict.

## 4) Formation pipeline (steady-state)

```mermaid
flowchart TD
  A[Archive export] --> B[Import\n(evidence atoms)]
  B --> C[atoms.sqlite3]
  C --> D[Episode build\n(policy + heuristics)]
  D --> E[Draft episodes\n+ rejects + readout]
  E --> F[Review/compile]
  F --> G[Published reviewed episodes]
  G --> H[Episode-first retrieval\n(runtime + evals)]
```

## 5) Required formation behaviors

### 5.1 Episode quality gates (promotion)
Promoted episodes must:
- be multi-turn (not single-line),
- contain concrete anchors (people, projects, places, named events, stable preferences),
- include citations in canonical token format `source_id#message_id`,
- expose a plausible time window (`timestamp_start`, `timestamp_end`).

### 5.2 Reject handling is not optional
Rejections are a first-class artifact:
- keep rejects as structured JSON,
- produce a human-readable readout for audit,
- use reject reasons to tune the build policy.

### 5.3 Seed supported prompts from promoted episodes
For supported non-routine eval families:
- expected alignment must be explicit (anchors cannot be empty-by-default),
- prompt generation should sample from promoted episodes first,
- atom-only prompts are reserved for “exact quote / what did we say” families.

## 6) Staged workplan (implementation sequencing)

This aligns with `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md` phases:

1. Lock schema + diagnostics (Phase 1)
2. Improve episode quality + segmentation (Phase 2)
3. Enforce episode-first retrieval and strict alignment (Phase 3)
4. Separate evidence vs episodic tier behavior (Phase 4)
5. Ship operator UX to build/review/verify (Phases 5–7)

## 7) Risks and mitigations

- **Risk:** episode build becomes too strict and yields too few episodes  
  **Mitigation:** policy presets, reject audit loop, builder curation profile.

- **Risk:** broad retrieval passes “technically” while being irrelevant  
  **Mitigation:** strict alignment metrics and bounded fanout (treat broad retrieval as quality failure).

- **Risk:** operators can’t correct behavior quickly  
  **Mitigation:** memory management UI with disable/edit/undo and “Why this answer?”.

