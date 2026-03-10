# Evidence vs Memory vs Episode (Stakeholder Glossary)

Status: Locked reference (Phase 0)  
Last Updated: 2026-02-13  
Source-of-truth linkage: `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md`

## Why this exists

Teams were using the same words for different layers (raw evidence vs event memory), which caused design drift.
This glossary is the plain-language contract used across product, runtime, eval, and UI work.

## Core terms

### Evidence
- Raw, source-backed conversation content (messages/atoms).
- Best for exact lookup and citation provenance.
- Can be factual but still low-context (single-line fragments).
- Not the primary user-facing recall unit when episode memory is available.

### Memory atom
- Deterministic unit persisted in the SQLite store.
- Usually tied to one source turn or tightly scoped claim.
- Carries provenance (`source_id`, `message_id`, timestamp when available).
- Used as supporting detail and verifier anchor.

### Episode card
- Event-level memory artifact built from multiple atoms/turns.
- Represents a coherent scene/change (`before -> core -> after`) with anchors and citations.
- Primary recall unit for “remember when / what happened” prompts.
- Published episode cards are curated and safe to use by default.

### Context package v2
- The memory service output consumed by the external responder model.
- Includes bounded evidence, service verdict, guidance, citations, and timing.
- This is part of the judged product surface.

### Service verdict
- Deterministic decision from NumquamOblita:
  - `PASS`, `ABSTAIN`, `CLARIFY`, `NO_MEMORY`.
- Constrains downstream model behavior.
- Prevents unsupported memory claims from being treated as valid recall.

### Citation token
- Canonical format: `source_id#message_id`.
- Required for strict eval/audit rendering.
- Always required internally for provenance, even when user-visible citation rendering is off.

## Draft vs published artifacts

### Draft artifacts
- Intermediate outputs from import/build/review steps.
- Useful for iteration and diagnostics.
- Never treated as default runtime memory without publish/compile steps.

### Published artifacts
- Runtime-default artifacts the app consumes in normal operation.
- For episodic memory, the published reviewed set is:
  - `runtime/episodes/episode_cards.reviewed.json`
- Published pointers must be restart-stable and recoverable.

## Judged surface (acceptance)

Acceptance evaluates:
1. `context-package v2` quality and correctness.
2. External responder output constrained by that package.
3. Verifier outcomes against package evidence/provenance.

Non-gating/debug-only surface:
- Internal standalone runtime answer text.

## Behavioral summary

- “What did we say exactly?” -> evidence/atom-centric behavior.
- “What happened with X?” -> episode-card-centric behavior with evidence support.
- If support is insufficient -> abstain/clarify, do not guess.
