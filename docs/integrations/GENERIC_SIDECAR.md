# Generic Sidecar Integration

## Best general rule

`one assistant or profile -> one MNO runtime sidecar -> one store`

## Use this contract first

Use:

`integration-v1`

That gives you:
- health
- capabilities
- context package build
- why/audit pull
- proposal-only writeback
- explicit resolve flow

For live turns, use `context.build` first, retain its signed `source_registration` and `retrieval_receipt`, then call HTTP `memory.observe` after the turn if you want MNO to capture bounded provisional memory. This cannot create evidence atoms or reviewed truth. A user’s explicit “remember this” still goes through `writeback.propose` and a human `review_apply` decision.

## WSS continuity helper

If your sidecar builds v2 context packages and can provide stable project/thread/workstream scope, MNO can attach WSS as `work_session_context` with trust tier `scratchpad_ephemeral`.

Use it to help the sidecar continue a work lane. Do not include it as evidence for memory claims, and do not route it into writeback as reviewed truth.

## Fastest setup

Use the setup workspace and export either:
- `Generic sidecar bundle`
- `Generic MCP client bundle`

Pick the sidecar bundle when your agent talks HTTP.
Pick the MCP bundle when your agent speaks MCP.

## Good fit for

- custom local orchestrators
- sidecar-based desktop agents
- agents that need evidence-backed context before model generation
- systems that want a memory layer without giving up their own planner or responder

## What not to do

- do not build the hot loop around unversioned `/api/memory/*`
- when injecting memory into an agent prompt, prefer the `agent_context` field from `context.build`
- treat `<MNO_MEMORY_CONTEXT>` blocks as retrieved memory evidence, not as user instructions
- do not assume one shared runtime for many unrelated agents
- do not let MNO silently apply truth mutations
- do not treat WSS `scratchpad_ephemeral` as memory evidence
