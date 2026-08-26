# OpenClaw Automatic-Layer Audit — 2026-08-25

## Decision

The former OpenClaw integration surface was a compatibility sidecar. It could
answer an OpenClaw-shaped request or hand back a context package, but it did
not participate in an independently hosted OpenClaw turn. It therefore could
not automatically place MNO retrieval before that host's model call or observe
the completed host response afterward.

The shipped `mno-openclaw-memory` package closes that specific gap. It is a
native OpenClaw plugin that calls MNO's constrained `integration.v1` API from
two host lifecycle hooks. The old adapter routes remain for manual or
OpenClaw-shaped compatibility use.

It uses the same MNO-side automatic-turn surface as the Hermes adapter:
`context.build` returns a signed context/receipt pair, and a matching
post-success `memory.observe` can only create provisional material. The host
plugin mechanics differ; the MNO authority boundary does not.

## Contract audited

The native package is built against the OpenClaw `2026.8.1` plugin contract and
declares `openclaw.compat.pluginApi >=2026.8.1`. The relevant host facts are:

| Host surface | MNO use | Why it is necessary |
| --- | --- | --- |
| `before_prompt_build` | Builds one MNO context packet and returns `prependContext`. | Lets OpenClaw preserve ownership of the actual model call while receiving bounded retrieval before it. |
| `agent_end` | Sends one asynchronous provisional observation only after `success: true`. | Correlates the observation with a completed host turn without blocking the reply. |
| `plugins.entries.<id>.hooks.allowConversationAccess` | Set to `true` by the installer through OpenClaw's config CLI. | OpenClaw blocks non-bundled conversation hooks without this explicit per-plugin grant. |
| `plugins.entries.<id>.hooks.allowPromptInjection` | Set to `true` explicitly. | Permits the prompt-building hook to return its bounded memory context. |
| `openclaw plugins inspect <id> --runtime --json` | Used by the MNO doctor and operator flow. | Verifies registered hooks; a static plugin listing is not enough. |

If a deployment uses a restrictive global `plugins.allow` list, the operator
must trust `mno-openclaw-memory` there too. The installer deliberately does not
broaden global allow/deny policy.

## Runtime behavior

### Before the model call

For a root `user` turn with an agent id, session key, and run id, the plugin:

1. normalizes and bounds the user text to 4,096 characters;
2. hashes OpenClaw session/run/workstream identifiers before sending them to
   MNO;
3. checks MNO capabilities and calls `context.build` through loopback HTTP;
4. validates `mno.agent_context.v2`, a 4,096-token cap, and an 8,192-character
   wrapper cap;
5. injects the result as a tag-safe `<MNO_MEMORY_CONTEXT_V1>` prompt block.

Subagent session keys, cron/heartbeat triggers, malformed contexts, absent
credentials, non-loopback URLs, slow MNO responses, and bad contract responses
all result in a no-op. The OpenClaw reply path continues normally.

### After a successful turn

The plugin retains only an in-memory, bounded pending correlation record. On a
matching successful `agent_end`, it queues exactly one `memory.observe` request
with the context-build signed registration and retrieval receipt. A delivery
error is never retried because the server might have received it. MNO records
the result as provisional; MNO's review/publish/verify/activate flow remains
the sole path to reviewed truth.

The plugin excludes failed, interrupted, empty, duplicate, unmatched, and
subagent events. It never invokes writeback, review resolution, canonical
memory mutation, publish, verify, or activation operations.

## WSS and retrieval separation

The default `work_session_scope` contains only opaque thread/workstream keys.
It can retrieve MNO's work-session scratchpad as short-lived continuity
context, but WSS is not evidence and does not become canonical memory because
the plugin consumed it.

The host keeps its own session/transcript mechanisms. MNO adds a compact
retrieval packet backed by MNO's retrieval/provenance pipeline; it does not
dump an archive into OpenClaw's prompt or attempt to replace its native session
state. This is an integration architecture conclusion, not a benchmark or a
claim that one system's retrieval quality universally dominates another's.

## Authority and diagnostics

`NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN` is accepted by MNO only for:

```text
health.get
capabilities.get
context.build
memory.observe
```

The plugin's own diagnostics contain operation/reason metadata only. They do
not include text, bearer tokens, host identifiers, signed handles, or context
bodies. `mno-openclaw doctor --json` proves restricted authorization and hook
registration; it cannot prove that a long-running Gateway inherited the
credential. A real root human turn must show `context.build` followed by
`memory.observe` in MNO's redacted integration logs.

See [OpenClaw Integration](OPENCLAW.md) for installation, operator checks, and
the redacted `mno-report` feedback workflow.

## Evidence completed in this repository

- Node lifecycle contract test: bounded injection, opaque ids, WSS scoping,
  duplicate suppression, and a single post-success observation.
- Real local MNO HTTP test: the native runtime calls `capabilities.get`,
  `context.build`, then `memory.observe` under the new least-privilege token;
  the observation remains provisional and does not create an atom.
- Installer contract test: host CLI installation, narrow hook-policy writes,
  hook registration check, and exact MNO capability scope.
- Bundle test: an exported OpenClaw bundle now carries the native package,
  installer helpers, config example, quickstart, API endpoints, and legacy
  compatibility routes.
- Wheel/sdist proof: package data and `mno-openclaw` console entry point remain
  available after isolated installation.

## Explicit limits

- No live Sage/OpenClaw gateway was modified or restarted during this audit.
- Runtime inspection plus a real MNO test proves the package contract, not a
  particular remote host's final configuration or retrieval quality.
- A supported host rollout still needs the documented `doctor` output and one
  real-turn smoke check before it should be described as active.
