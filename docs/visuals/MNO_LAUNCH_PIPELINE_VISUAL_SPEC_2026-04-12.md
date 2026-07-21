# MNO Launch Pipeline Visual Spec 2026-04-12

This is the launch-facing pipeline package for the clean repo, but it must still describe the real system rather than a hollow launch cartoon.

Companion draw.io file:
- [MNO_LAUNCH_PIPELINE_2026-04-12.drawio](MNO_LAUNCH_PIPELINE_2026-04-12.drawio)

## Purpose

This package should explain:
- how someone starts from raw files, folders, or an existing store
- how guided setup and source staging work
- where sanitization and atom import happen
- where the raw-context wording receipt is written
- where optional draft curation sits
- where human review and truth-lineage annotation happen
- when reviewed cards become runtime-usable
- where built-in WSS appears as strict active project/thread/workstream scoped `scratchpad_ephemeral` runtime helper state

## Authority

Primary files:
- [run_setup_workspace.py](../../tools/run_setup_workspace.py)
- [server.py](../../engine/runtime/server.py)
- [index.html](../../engine/runtime/ui/index.html)
- [app.js](../../engine/runtime/ui/app.js)
- [parser.py](../../engine/ingest/parser.py)
- [orchestrator.py](../../engine/ingest/orchestrator.py)
- [sqlite_store.py](../../engine/memory/sqlite_store.py)

## Draw.io pages

The file should contain two pages:
1. `Engineering Pipeline`
2. `Caveman Pipeline`

## Page 1: Engineering Pipeline

Show the launch flow in three areas:

### Input And Build
- raw sources
- existing store
- guided source staging
- import / normalization / sanitization
- raw-context sidecar write
- draft episode card build

### Review And Truth
- Headless Curation Room or desktop Review; agent proposals stay draft-only and human decisions remain authoritative
- human review
- compile reviewed cards
- truth-lineage finalize
- reviewed cards go live

### Runtime Launch And Operate
- launch_setup_workspace entrypoint
- runtime launch surfaces
- runtime memory sources summary, including strict active-scope WSS
- launch rule that reviewed cards become trusted runtime memory while WSS stays work continuity, not proof

## Page 2: Caveman Pipeline

This page should explain the same flow in plain language while still teaching the core terms:
- `atoms = small evidence pieces`
- `wording receipt = original cleaned wording kept for quote checks`
- `draft = rough, not trusted yet`
- `reviewed cards = trusted runtime memory`
- `truth lineage = corrected reviewed cards stay linked`
- `WSS = work-session scratchpad`

## Important launch boundaries

- picker-first UX should be visible in the engineering page
- append-to-existing-store behavior should be visible
- raw-context sidecar should be visible but clearly non-authoritative
- WSS should be visible as `scratchpad_ephemeral` work-session continuity support, not reviewed truth
- human review remains the truth gate

## v0.2 launch posture

The startup command must show the shared policy source: `tools/run_live_runtime.py --config <json>`. Fresh standard policy enables low-risk provisional capture/retrieval/maintenance/consolidation; upgraded configurations that omit v0.2 fields preserve the disabled posture. This does not enable autonomous canonical publication.

The page must distinguish import-created evidence atoms from live `memory.observe` provisional records and from explicit reviewer-controlled writeback. Authority remains `human_reviewed_canonical` → `evidence_atom` → `provisional_consolidated` → `provisional_observed`; STM/WSS are continuity helpers, not evidence.
