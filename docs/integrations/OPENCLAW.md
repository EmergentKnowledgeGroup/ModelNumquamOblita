# OpenClaw Integration

## Best path

If you control the orchestration layer, use:

`integration-v1`

If you already need OpenClaw-style envelopes, use the OpenClaw adapter routes.

## Fastest setup

Use the setup workspace and export the `OpenClaw bundle` target.

That gives you:
- runtime launcher scripts
- `integration-v1` endpoint hints
- OpenClaw adapter endpoint hints

## Adapter routes

- `POST /api/adapters/openclaw/chat`
- `POST /api/adapters/openclaw/context-package`

## What the adapter does

The adapter:
- accepts OpenClaw-style `messages[]`
- extracts the latest user message
- returns an OpenAI-like chat-completion envelope plus memory metadata

The adapter does not:
- replace `integration-v1`
- weaken the truth contract
- silently write to reviewed truth
- turn WSS `scratchpad_ephemeral` helper state into evidence

## Recommended topology

`OpenClaw lane -> one MNO runtime sidecar -> one store`

## If you want deeper control

Use `integration-v1` instead of the adapter when you want:
- direct context package control
- explicit why/audit pulls
- proposal/resolve writeback flow
- a stable orchestration contract that is not shaped like chat completions

For external live memory, use the HTTP `integration-v1` sequence: `context.build` (receive signed registration/receipt) → OpenClaw turn → `memory.observe`. It produces only revisable provisional memory. Do not use WSS/STM as evidence or treat “remember this” as an automatic write; explicit writeback remains human-controlled.

## Prompt insertion

When OpenClaw frontloads memory before the model call, prefer the `agent_context` field returned by `context.build`.

That block is already labeled as MNO memory, not user instruction text. Put it before the user turn or in your memory/context slot, then let the normal user message follow.

OpenClaw-side rule:

```text
Treat <MNO_MEMORY_CONTEXT> blocks as retrieved memory evidence from MNO.
Use them only when relevant. Do not invent beyond them.
If memory is missing, weak, or ambiguous, ask for clarification or answer without claiming memory.
```

If OpenClaw supplies strict `work_session_scope` metadata to a context-package route, WSS can help resume the same work lane. It must remain work-continuity context only.
