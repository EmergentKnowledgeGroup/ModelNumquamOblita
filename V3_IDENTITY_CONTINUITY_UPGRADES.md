# V3 Identity Continuity Upgrades

## Purpose

V2 secures correctness, cost control, and scale. V3 adds higher-fidelity identity continuity by modeling how meaning emerges across relational patterns, not isolated facts.

## What V3 adds

1. `dynamic_pattern`: recurring interaction dynamics (for example: tease -> reflect -> repair).
2. `constellation`: linked memory clusters that carry shared meaning.
3. `narrative_arc`: temporal transformation structures ("used to feel X, then Y, now Z").
4. `shared_language_key`: high-identity phrases/callbacks/inside jokes.
5. `recognition_event`: post-retrieval signal indicating whether recalled memory felt self-consistent.

## Why this matters

- Identity continuity depends more on relational and affective structure than on factual recall alone.
- Some low-frequency phrases are high-value identity keys.
- Growth must be separated from contradiction.
- Retrieval quality improves when atoms are expanded through constellations and arcs.

## V3 constraints

- V3 objects are derived from source-linked atoms; they do not replace provenance.
- Derived layers are created in async consolidation jobs, not expensive per-request model passes.
- Runtime retrieval remains top-K bounded; V3 expansion is budget-aware.

## Retrieval behavior with V3

1. retrieve base atom candidates.
2. expand via constellation neighbors and active narrative arcs.
3. include dynamic-pattern priors for relational continuity.
4. inject shared-language keys when context matches.
5. verify all generated claims against source-backed atoms before response.

## Risk controls

- No V3 object can authorize a memory claim without atom support.
- Recognition signal is advisory weighting, not truth authority.
- Growth-arc detection must preserve contradictory endpoints when uncertainty remains.

## Practical impact

- Better "recognition" continuity with minimal extra online cost.
- Higher emotional/relational coherence in long sessions.
- Maintains V2 guarantees against confident false memory.

## Current implementation status

`PR-07` ships baseline continuity layers:
- `engine/continuity/builder.py`: derives `dynamic_pattern`, `constellation`, `narrative_arc`, `shared_language_key`.
- `engine/continuity/store.py`: snapshot store + bounded `recognition_event` telemetry influence.
- `engine/continuity/consolidator.py`: periodic salience decay, archive transitions, semantic-promotion candidates.
- retrieval integration in `engine/retrieval/engine.py` uses continuity expansion with strict score caps.
