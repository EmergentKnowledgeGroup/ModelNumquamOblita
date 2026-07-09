# MNO Current Runtime Memory And Decision Visual Spec 2026-04-12

This package is the runtime-only companion to the broader system map. It reflects the clean repo after the raw-context sidecar and reviewed truth-lineage work.

Companion draw.io file:
- [MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_2026-04-12.drawio](MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_2026-04-12.drawio)

## Purpose

Use this package when you want to understand:
- what memory layers exist during a live turn
- which layers are authoritative and which are helper-only
- where exact wording / provenance expansion now fits
- where built-in work-session scratchpad context fits when strict project/thread/workstream scope is present
- how reviewed truth-lineage affects runtime ranking and interpretation
- where verifier, abstain, and proposal-only writeback sit in the live path

## Live-code authority

Primary files:
- [session.py](../../engine/runtime/session.py)
- [engine.py](../../engine/retrieval/engine.py)
- [raw_sidecar.py](../../engine/retrieval/raw_sidecar.py)
- [scratchpad.py](../../engine/runtime/scratchpad.py)
- [episode_cards.py](../../engine/retrieval/episode_cards.py)
- [store.py](../../engine/memory/store.py)
- [sqlite_store.py](../../engine/memory/sqlite_store.py)
- [server.py](../../engine/runtime/server.py)

## Draw.io pages

The file should contain three pages:
1. `Engineering Runtime Memory Layers`
2. `Engineering Runtime Decision And Evidence Flow`
3. `Caveman Runtime Memory And Decision`

## Page 1: Engineering Runtime Memory Layers

This page should make the layer stack obvious.

### Request-Local And Short-Term
- immediate context
- STM / session state

### Runtime Helper Layers
- provisional memory
- proposal-only store
- continuity surfaces
- raw-context sidecar
- work-session scratchpad, built-in `scratchpad_ephemeral` package helper state

### Durable Reviewed / Canonical
- canonical atom store
- reviewed episode cards
- reviewed truth-lineage metadata

### Governed Control Surfaces
- mutation review queue
- explicit trust rules note
- read-time effect note describing quote inspection and current-vs-superseded reviewed truth

## Page 2: Engineering Runtime Decision And Evidence Flow

This page should show the live path:
- incoming turn
- router and query shaping
- STM retrieval
- LTM retrieval
- ANN candidate helper
- lineage-aware reviewed resolution
- fusion and guarded shortlist
- context package assembly
- raw-context quote/provenance expansion
- work-session scratchpad context-package attachment through strict project/thread/workstream scope
- verifier and answer path
- final output
- post-turn capture
- proposal-only writeback
- human review / resolve

## Key rules that must remain explicit

- reviewed truth outranks helper memory
- raw-context expansion is query-gated and additive only
- work-session scratchpad is built-in `scratchpad_ephemeral` helper state, not evidence or truth
- retrieval success does not equal truth authority
- verifier remains in the answer path
- proposal-only writeback prevents silent truth mutation

## Page 3: Caveman Runtime Memory And Decision

This page should explain the same runtime behavior without flattening the engineering path into marketing language.

It should still explain:
- `STM = short-term memory`
- `ANN = approximate nearest neighbor`
- `MCP = Model Context Protocol`
- wording receipt lane only wakes when exact wording matters
- work-session scratchpad can remind an agent what it was doing, but cannot prove a memory
- corrected reviewed cards stay linked so MNO can tell old reviewed truth from current reviewed truth
- MNO still answers, abstains, or asks for clarification instead of bluffing

## Current-iteration caveats

- the raw-context lane is not a transcript-dump mode; it is a bounded provenance helper
- the work-session scratchpad is project-local and only enters strict project/thread/workstream scoped context packages
- truth-lineage is explicit reviewed metadata, not autonomous reconsolidation
- provisional memory remains revisable and lower-trust than reviewed memory
