# MNO Launch Runtime And Integration Visual Spec 2026-04-12

This is the launch-facing runtime and integration package for the clean repo, updated to match the current retrieval stack and article-driven additions.

Companion draw.io file:
- [MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-12.drawio](MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-12.drawio)

## Purpose

This package should explain:
- where requests enter MNO
- what memory layers exist at runtime
- where the ANN helper sits
- where the raw-context quote/provenance lane sits
- where built-in WSS attaches to context packages only under strict project/thread/workstream scope
- how reviewed truth-lineage affects runtime use of reviewed cards
- where response, abstain, clarify, and proposal-only writeback happen
- how integrators should think about integration-v1, MCP, and adapters

## Authority

Primary files:
- [session.py](../../engine/runtime/session.py)
- [engine.py](../../engine/retrieval/engine.py)
- [raw_sidecar.py](../../engine/retrieval/raw_sidecar.py)
- [scratchpad.py](../../engine/runtime/scratchpad.py)
- [episode_cards.py](../../engine/retrieval/episode_cards.py)
- [server.py](../../engine/runtime/server.py)
- [adapters.py](../../engine/runtime/adapters.py)
- [run_agent_live_mcp.py](../../tools/run_agent_live_mcp.py)

## Draw.io pages

The file should contain two pages:
1. `Engineering Runtime And Integration`
2. `Caveman Runtime And Integration`

## Page 1: Engineering Runtime And Integration

Show four areas:

### Entry Surfaces
- guided setup workspace
- desktop shell
- integration-v1
- MCP
- adapters

### Memory Layers
- STM
- provisional memory
- built-in WSS `scratchpad_ephemeral` sidecar helper state
- continuity surfaces
- raw-context sidecar
- reviewed episode cards plus lineage
- atoms plus bounded ANN helper

### Retrieval And Decision
- router and query shaping
- fusion and guarded shortlist
- context package, including WSS `scratchpad_ephemeral` when strict scope is present
- quote/provenance expansion
- responder and verifier

### Outputs And Governance
- response / abstain / clarify
- proposal-only writeback
- human/operator resolve
- key runtime rule note

## Page 2: Caveman Runtime And Integration

This page should explain the launch runtime behavior in plain language without pretending the engineering details do not matter.

It should still explain:
- `MCP = Model Context Protocol`
- `STM = short-term memory`
- `ANN = approximate nearest neighbor`
- `WSS = work-session scratchpad`
- wording receipt lane only wakes when exact wording matters
- reviewed truth can distinguish old corrected cards from current reviewed cards
- risky new memory still goes through proposal/review instead of jumping into truth

## Key boundaries

- integration-v1 remains the main orchestration contract
- adapters are compatibility surfaces, not the main truth contract
- ANN is additive only
- raw-context sidecar is inspectability support only
- WSS is `scratchpad_ephemeral` work-session continuity support only
- reviewed truth remains authoritative over helper layers
