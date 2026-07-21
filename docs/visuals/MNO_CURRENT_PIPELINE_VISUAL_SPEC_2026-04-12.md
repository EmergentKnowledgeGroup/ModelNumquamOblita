# MNO Current Pipeline Visual Spec 2026-04-12

This visual package is the current-state system map for the clean repo after the raw-context sidecar and reviewed truth-lineage additions.

Companion draw.io file:
- [MNO_CURRENT_PIPELINE_2026-04-12.drawio](MNO_CURRENT_PIPELINE_2026-04-12.drawio)

## Purpose

Use this package when you want the current MNO shape, not a launch-only simplified picture. It should show:
- how raw source intake becomes durable evidence
- where the raw-context sidecar is written and how it stays separate from truth
- where built-in WSS attaches to runtime context packages only under strict active project/thread/workstream scope
- where optional draft curation sits
- how reviewed cards become trusted runtime memory
- how truth-lineage metadata links corrected reviewed cards
- how runtime uses atoms, reviewed cards, and the quote/provenance lane without collapsing those layers together

## Live-code authority

Primary files for this map:
- [parser.py](../../engine/ingest/parser.py)
- [orchestrator.py](../../engine/ingest/orchestrator.py)
- [store.py](../../engine/memory/store.py)
- [sqlite_store.py](../../engine/memory/sqlite_store.py)
- [raw_sidecar.py](../../engine/retrieval/raw_sidecar.py)
- [scratchpad.py](../../engine/runtime/scratchpad.py)
- [engine.py](../../engine/retrieval/engine.py)
- [episode_cards.py](../../engine/retrieval/episode_cards.py)
- [session.py](../../engine/runtime/session.py)
- [server.py](../../engine/runtime/server.py)
- [app.js](../../engine/runtime/ui/app.js)

## Draw.io pages

The file should contain four pages:
1. `Engineering Pipeline`
2. `Engineering Runtime Memory Layers`
3. `Engineering Runtime Decision And Evidence Flow`
4. `Caveman Pipeline`

## Page 1: Engineering Pipeline

This page is the real pipeline map. It should preserve the engineering layering instead of reducing everything to a launch summary.

### Lane 1: Source Intake And Build
- raw files, folders, and conversation exports
- existing store entry for append or reuse
- source loader plus normalization and sanitization
- atom store creation/update
- raw-context sidecar write
- draft episode card build

### Lane 2: Review And Trusted Memory
- Headless Curation Room or desktop Review stays between Build and Publish; agent proposals remain draft-only and human decisions remain authoritative
- review pack / review UI
- compile reviewed cards
- truth-lineage finalize
- reviewed episode cards as trusted runtime memory
- explicit note that draft helpers, WSS context, and raw-context receipts are not truth authorities

### Lane 3: Runtime Participation
- runtime retriever consumes atoms, reviewed cards, and helper layers
- context packages include WSS `scratchpad_ephemeral` when strict active project/thread/workstream scope is present
- raw-context quote/provenance lane wakes only for explicit wording or source-context asks
- lineage-aware read path prefers current reviewed truth over superseded reviewed cards
- normal answer path remains bounded evidence plus verifier
- writeback stays proposal-only and governed

### Lane 4: Integration Surfaces
- desktop shell
- integration-v1
- MCP sidecar
- adapter surfaces
- launch workspace entrypoints

## Key boundaries that must remain visible

- raw-context sidecar is read-only inspectability support
- reviewed cards remain higher-trust than provisional/helper layers
- truth-lineage improves read-time interpretation of reviewed truth, not silent rewriting of history
- optional draft curation stays draft-only
- proposal-only writeback remains separate from trusted reviewed memory

## Page 2: Engineering Runtime Memory Layers

This page should show the current live memory stack inside the broader system package:
- immediate context
- STM / session state
- provisional memory
- built-in WSS `scratchpad_ephemeral` sidecar helper state
- proposal-only store
- continuity surfaces
- raw-context sidecar
- canonical atom store
- reviewed episode cards
- reviewed truth-lineage metadata
- mutation review queue
- explicit trust rules note

## Page 3: Engineering Runtime Decision And Evidence Flow

This page should show the live request path inside the broader system package:
- incoming turn
- router and query shaping
- STM retrieval
- LTM retrieval
- ANN candidate helper
- lineage-aware reviewed resolution
- fusion and guarded shortlist
- context package assembly, with WSS attached only by strict active project/thread/workstream scope
- raw-context quote/provenance expansion
- verifier and answer path
- final output
- post-turn capture
- proposal-only writeback

## Page 4: Caveman Pipeline

This page explains the same system in simpler language without replacing the engineering page.

It should still explain:
- `atoms = small evidence pieces`
- `raw-context sidecar = wording receipt`
- `draft cards = rough memory cards`
- `truth lineage = old and corrected reviewed cards stay linked`
- `MCP = Model Context Protocol`
- `ANN = approximate nearest neighbor`
- `WSS = work-session scratchpad`

The caveman page should answer a basic user question:
`What happens when I give MNO my stuff, and how does it stay honest?`

## Current-iteration caveats

- raw-context receipts are bounded and query-gated; they do not become the primary truth layer
- WSS is built-in `scratchpad_ephemeral` work-session helper state, not evidence or reviewed truth
- lineage metadata currently lives on reviewed cards, not as an autonomous mutable memory system
- this package is for the clean repo current state, not older internal pre-clean diagrams

## v0.2 authority and live-write update

Every engineering and caveman page must keep the authority families visible: `human_reviewed_canonical` → `evidence_atom` → `provisional`. Within the provisional family, consolidated artifacts have higher retrieval precedence than direct observations; the separate maturity axis is `observed → reinforced → consolidated`. Neither crosses into evidence or canonical authority. STM and WSS are scoped helper context, not evidence tiers.

Show three distinct ingress paths: raw import creates evidence atoms; HTTP `memory.observe` records a completed live turn as signed, bounded provisional memory; user “remember this” uses `writeback.propose`, then a human `review_apply` resolve with `apply=true` may create a durable `human_reviewed=false` evidence atom. Normal build/review/publish is still the only path to human-reviewed canonical truth. Source registrations and retrieval receipts are signed evidence-integrity handles, not retrieval writes.
