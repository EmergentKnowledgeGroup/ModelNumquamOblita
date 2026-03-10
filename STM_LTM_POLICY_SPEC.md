# STM/LTM Policy Spec

## Goal
Add a two-tier memory runtime that behaves like fast recent recall plus deeper archived recall:
- **STM (short-term memory):** recent, fully formed conversational memories, low latency.
- **LTM (long-term memory):** atomized evidence with citations, high precision and continuity safety.

The runtime must remain fail-closed: when evidence is weak, it should abstain or clarify.

## Retrieval Modes
Per turn, the runtime chooses one mode:
1. **`stm_primary`**: strong STM match; skip LTM retrieval for speed.
2. **`hybrid`**: medium STM match; run LTM and merge STM+LTM packs.
3. **`ltm_only`**: no useful STM match; use LTM only.

## STM Data Model
Each turn appends two STM notes (user + assistant):
- `note_id`
- `turn_id`
- `role`
- `text`
- `created_at`

STM is bounded by capacity (ring buffer), defaulting to a small recent window.

## Scoring and Routing
For query vs STM note:
- token-overlap score (informative token intersection)
- character n-gram similarity (paraphrase tolerance)
- recency boost
- fused score

Routing thresholds:
- below floor: `ltm_only`
- above floor but below strong threshold: `hybrid`
- above strong threshold: `stm_primary`

## Merge Policy (Hybrid)
- STM items are placed first in `core` because they represent immediate context.
- LTM `core/context/conflict/continuity` items are appended without duplicate atom IDs.
- Pack confidence is weighted toward STM when STM confidence is high.

## LTM Multi-Pass Retrieval
- LTM retrieval may run deterministic query variants per turn:
  - original retrieval query
  - compact informative-token query (and signal-token query when available)
- The runtime picks the strongest pass by evidence score before verifier gating.
- Safety is unchanged: weak evidence still fails closed to `ABSTAIN`.

## Observability
Expose per-turn and aggregate mode telemetry:
- turn: `memory_mode`, `short_term_hits`
- runtime state: counts for `stm_primary`, `hybrid`, `ltm_only`

## Safety and Correctness
- Keep citation-bearing LTM path intact.
- Do not mutate LTM atoms from STM notes.
- Skip continuity writeback for synthetic STM IDs.
- Preserve abstain behavior when no evidence claims exist.

## Regression Test Plan
1. `stm_primary`: second turn repeats recent phrasing and routes to STM.
2. `hybrid`: partial STM overlap routes to hybrid and still returns evidence-backed output.
3. paraphrase safety: low token overlap still routes to STM when n-gram similarity is strong.
4. `ltm_only`: no STM overlap falls back to LTM.
5. state endpoint includes new mode counters.
6. all existing unit/integration tests remain green.
