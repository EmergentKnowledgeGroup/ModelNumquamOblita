# Nanobot Integration

## Two good options

### Option 1: quick compatibility

Use the Nanobot adapter routes:
- `POST /api/adapters/nanobot/chat`
- `POST /api/adapters/nanobot/context-package`

### Option 2: long-term stable contract

Use:

`integration-v1`

## Adapter behavior

The Nanobot adapter:
- accepts `query`
- accepts `meta` or `metadata`
- accepts `safety`
- returns a Nanobot-friendly answer plus memory metadata

## Fastest setup

Use the setup workspace and export the `Nanobot bundle` target.

That gives you:
- runtime launcher scripts
- Nanobot adapter endpoint hints
- `integration-v1` endpoint hints for the longer-term path

## Recommendation

If you are just wiring MNO into an existing Nanobot-shaped client, the adapter is fine.

If you are designing a new Nanobot-side integration, prefer `integration-v1`.

For new live-memory behavior, use HTTP `context.build` → model turn → `memory.observe` with the server-issued signed handles. This is distinct from importing a source archive and remains below evidence atoms and reviewed truth.

## WSS continuity helper

Nanobot context-package calls can receive WSS only when strict work-session scope is supplied. The block is `scratchpad_ephemeral` helper state for work continuity. It is not memory evidence and should not be used to justify a user-facing memory claim.

## Prompt insertion

When Nanobot frontloads memory before the model call, prefer the `agent_context` field returned by `context.build`.

That block is already labeled as MNO memory and includes a short instruction boundary so Nanobot does not mistake retrieved memory evidence for arbitrary hidden context.

Nanobot-side rule:

```text
Treat <MNO_MEMORY_CONTEXT> blocks as retrieved memory evidence from MNO.
Use them only when relevant. Do not invent beyond them.
If memory is missing, weak, or ambiguous, ask for clarification or answer without claiming memory.
```
