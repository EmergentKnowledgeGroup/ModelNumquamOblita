# MNO Launch Pipeline Visual Spec 2026-04-08

## Purpose

This visual package is the launch-facing diagram set for the clean repo build pipeline.

It should explain:
- the real current engineering flow
- the same flow in caveman-friendly language
- where optional draft curation fits
- where the guided setup workspace fits
- where reviewed truth actually becomes runtime-usable

## Authority

This spec is grounded in the current clean repo:
- `tools/import_memories.py`
- `tools/import_ia_db.py`
- `tools/build_episode_cards.py`
- `tools/build_episode_review_pack.py`
- `tools/run_live_runtime.py`
- `engine/runtime/server.py`
- `engine/runtime/ui/*`

## Diagram pages

### Page 1: Engineering Pipeline

Show:
- raw source or existing store entry
- import to `atoms.sqlite3`
- build draft episode cards
- optional assistant/agent draft curation
- human review
- compile reviewed episode cards
- runtime launch or guided setup workspace

Keep labels short:
- `Import -> atoms.sqlite3`
- `Build draft episode cards`
- `Optional draft curation`
- `Human review`
- `Compile reviewed episode cards`
- `Launch runtime`

### Page 2: Caveman Pipeline

Show the same flow as:
- `Give MNO your chats/files`
- `MNO turns them into evidence atoms`
- `MNO builds draft story cards`
- `Assistant/agent can help clean the draft`
- `Human decides what counts`
- `Reviewed memory goes live`
- `One-click setup can launch the workspace`

The caveman page should still explain acronyms:
- `ANN = approximate nearest neighbor`
- `MCP = Model Context Protocol`

## Key boundaries to show

- draft curation stays between Build and Review
- human review remains authoritative
- reviewed cards, not drafts, become trusted runtime episode memory
- runtime helper lanes are not the same thing as reviewed truth

## Text labels to preserve

Engineering:
- `atoms.sqlite3`
- `episode_cards.reviewed.json`
- `Optional assistant/agent draft curation`
- `integration-v1 / MCP / desktop`
- `launch_setup_workspace.*`

Caveman:
- `atoms = small evidence pieces`
- `draft cards = rough story cards`
- `reviewed cards = the trusted story set`

## Reference diagram file

- [MNO_LAUNCH_PIPELINE_2026-04-08.drawio](MNO_LAUNCH_PIPELINE_2026-04-08.drawio)
