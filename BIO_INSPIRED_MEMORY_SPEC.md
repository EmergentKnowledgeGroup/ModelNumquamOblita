# Bio-Inspired Memory Spec

## 1. Purpose

Define a memory system that mirrors biological memory behavior while remaining deterministic, inspectable, and safe for production use.

## 2. Biological mapping

### Encoding (attention gate)
- Humans do not store everything.
- System behavior: only write memories that exceed salience and identity relevance thresholds.

### Consolidation (short-term to long-term)
- Humans stabilize and compress memory over time.
- System behavior: periodic consolidation converts repeated episodic signals into stable semantic identity facts.

### Dual representation
- Humans retain episodes and abstractions.
- System behavior:
  - Episodic store: "what happened, when, with whom."
  - Semantic store: "what it means, what is stable."

### Cue-driven recall
- Humans recall via context cues, not exact search strings.
- System behavior: retrieval fuses lexical, semantic, temporal, relational, and affective cues.

### Reconsolidation
- Recall updates memory.
- System behavior: recalled atoms can be strengthened, reframed, or superseded with explicit version lineage, but provenance is never silently rewritten.

### Forgetting/pruning
- Forgetting reduces interference.
- System behavior: low-support, low-salience memories decay or archive without deleting provenance.
- Default decay model: salience half-life of `180 days` without reinforcement.

## 3. System contract

1. The model must not assert a memory unless supported by source-linked atoms.
2. If confidence is below threshold, the system must abstain or ask a clarification question.
3. Contradictory memories must surface as uncertainty with citations, not as a single overconfident claim.
4. All memory writes and updates must be auditable.
5. Destructive memory edits/deletes require explicit user approval.

## 4. Memory classes

- `episodic`: event-level experiences with time and context.
- `semantic`: stable preferences, traits, and identity assertions.
- `relational`: entity-to-entity links and relationship state.
- `affective`: valence/intensity and emotional signatures.
- `procedural_style`: cadence/anchor/rhetorical tendencies.
- `dynamic_pattern` (derived): recurring interaction structure over time.
- `constellation` (derived): semantically/affectively linked atom clusters.
- `narrative_arc` (derived): transformation pathways across time.
- `shared_language_key` (derived): high-identity callbacks and coined terms.
- `recognition_event` (derived): retrieval outcomes indicating self-recognition strength.

## 5. Accuracy-first stance

The target is calibrated truthfulness, not maximal recall volume.

Success means:
- low false-memory rate,
- strong evidence alignment,
- stable behavior under long-term scale.

## 6. What cannot be fully captured

- embodied sensation and physiology,
- unconscious associative processing,
- full phenomenology of "felt sense" in biological memory.

For this system, that is acceptable if:
- factual and relational continuity remain high,
- false memory remains low,
- uncertainty is surfaced honestly.

## 7. Agency model

Agency is implemented through curation, not surgery:
- allowed: reinforcement, linking, reframing, and priority changes,
- disallowed without approval: hard delete, provenance rewrite, contradiction erasure.
