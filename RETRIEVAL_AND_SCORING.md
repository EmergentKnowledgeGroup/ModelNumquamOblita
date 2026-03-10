# Retrieval and Scoring

## Objective

Return the smallest evidence-backed memory set that answers the query with high confidence.

## Retrieval stack

### Phase 1: Query interpretation
- extract entities, time cues, intent, and affective tone.
- derive retrieval profile (e.g., episodic-heavy vs semantic-heavy).
- classify context preset:
  - `factual`,
  - `emotional`,
  - `creative`,
  - `mixed`.

### Phase 2: Multi-channel candidate fetch
- lexical candidates (exact/near-exact phrase matches).
- semantic vector candidates (embedding similarity).
- temporal candidates (recency window, historical window).
- relational candidates (graph expansion from key entities).
- continuity candidates:
  - constellation neighbors,
  - narrative arc segments,
  - dynamic pattern matches,
  - shared language key hits.

### Phase 3: Fusion and rerank
- unify candidates by `atom_id`.
- score each candidate by weighted components.
- enforce bounded rerank budget with early-exit when confidence is already sufficient.

## Scoring formula (baseline)

```text
score =
  0.30 * semantic_similarity +
  0.25 * lexical_similarity +
  0.20 * temporal_relevance +
  0.15 * relational_relevance +
  0.10 * salience -
  contradiction_penalty
```

Then apply:
- support bonus (for high corroboration),
- stale penalty (if outdated and weakly supported),
- conflict penalty (if unresolved contradiction).

Preset-specific weight adjustment:
- `factual`: boost semantic + temporal.
- `emotional`: boost affective + relational + dynamic pattern channels.
- `creative`: boost shared language + procedural_style + constellation.
- `mixed`: balanced baseline.

## Memory pack builder

From reranked list, build:
- `core_pack`: top high-confidence atoms.
- `context_pack`: supporting atoms and temporal context.
- `conflict_pack`: contradictory atoms if relevant.
- `continuity_pack`: constellation/arc/dynamic/shared-language support objects.

Each pack item must include source refs.

## Response gate

If `pack_confidence < threshold`:
- abstain, or
- ask clarification question with best-available citations.

If confidence is sufficient:
- respond using only selected memory pack.
- include optional evidence summary in system traces (not user-facing by default).
- run claim-level verifier:
  - each memory claim must map to at least one supported atom,
  - unsupported claims are removed or converted to uncertainty language.

Derived continuity objects can shape ranking and phrasing but cannot serve as sole evidence for factual memory claims.

If conflicting high-support atoms remain unresolved:
- do not synthesize a single claim,
- return uncertainty and cite conflicting evidence paths.

## Scaling constraints

- retrieval complexity must remain bounded with top-K per channel.
- reranking budget is fixed per request.
- caches for frequent entities and recent sessions reduce latency.
- adaptive budget policy:
  - narrow/simple query -> lower K, faster path,
  - ambiguous/high-stakes query -> higher K, deeper rerank.

## Current implementation status

`PR-06` implements retrieval + verifier primitives:
- `engine/retrieval/engine.py`: bounded multi-channel fusion (`lexical`, pseudo-semantic, temporal, graph).
- `engine/retrieval/verifier.py`: claim-evidence verifier with `PASS|CLARIFY|ABSTAIN`.
- conflict-aware uncertainty path for unresolved contradictory support.
- derived-only evidence guardrail for factual claims.
