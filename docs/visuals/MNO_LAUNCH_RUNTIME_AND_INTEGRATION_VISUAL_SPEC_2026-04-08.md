# MNO Launch Runtime And Integration Visual Spec 2026-04-08

## Purpose

This visual package is the launch-facing diagram set for the runtime, memory layers, and integration surfaces.

It should explain:
- where requests enter MNO
- what memory layers exist
- how retrieval and evidence packaging work
- what the verifier and writeback boundaries do
- how integrators should think about `integration-v1`, MCP, and adapters

## Authority

This spec is grounded in the current clean repo:
- `engine/runtime/session.py`
- `engine/retrieval/engine.py`
- `engine/runtime/server.py`
- `engine/runtime/adapters.py`
- `engine/mcp/server.py`
- `tools/run_live_runtime.py`
- `tools/run_mcp_server.py`
- `tools/run_agent_live_mcp.py`
- `tools/run_setup_workspace.py`

## Diagram pages

### Page 1: Engineering Runtime And Integration

Show:
- incoming surfaces:
  - guided setup workspace
  - desktop
  - `integration-v1`
  - MCP
  - adapters
- router and query shaping
- memory layers:
  - STM
  - provisional
  - continuity surfaces
  - reviewed episode cards
  - atoms
  - bounded ANN helper
- fusion and guarded shortlist
- evidence package
- responder + verifier
- response / abstain / clarify
- proposal-only writeback to review queue

### Page 2: Caveman Runtime And Integration

Show:
- `agent asks MNO for memory help`
- `MNO checks short-term stuff`
- `MNO checks trusted memory and evidence`
- `ANN helper finds nearby candidates`
- `MNO builds a bounded evidence bundle`
- `model answers or says it cannot find it`
- `new memory goes to proposal lane, not straight to truth`

The caveman page should still explain acronyms:
- `STM = short-term memory`
- `ANN = approximate nearest neighbor`
- `MCP = Model Context Protocol`

## Key boundaries to show

- reviewed truth outranks runtime helper layers
- ANN is additive only
- verifier stays in the answer path
- writeback is propose/resolve gated
- adapters are compatibility shims, not the main contract

## Text labels to preserve

Engineering:
- `integration-v1`
- `bounded ANN helper`
- `evidence pack`
- `verifier`
- `proposal-only writeback`

Caveman:
- `trusted memory`
- `helper memory`
- `bounded evidence bundle`
- `human still decides what becomes truth`

## Reference diagram file

- [MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-08.drawio](MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-08.drawio)
