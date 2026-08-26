# v0.2.5 Release Notes — OpenClaw Automatic Memory Layer

## What changed

MNO now ships `mno-openclaw-memory`, an optional native OpenClaw plugin for
plugin API `2026.8.1+`. It is an automatic lifecycle layer, not an MCP tool and
not a replacement for an agent's personality or host memory system.

For eligible root-user turns, the plugin asks MNO for one bounded
`mno.agent_context.v2` packet before the model call. A matching successful
`agent_end` then makes one nonblocking `memory.observe` attempt. MNO keeps that
observation provisional; existing review, publish, verify, and activate gates
remain the only route to reviewed canonical truth.

## Operator contract

- Install, inspect, and remove the layer through `mno-openclaw install`,
  `status`, `doctor`, and `uninstall`.
- The installer uses OpenClaw's own CLI to enable only this plugin's required
  conversation-access and prompt-injection hook policy. It does not broaden a
  host-global plugin allowlist.
- `NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN` is server-scoped to exactly
  `health.get`, `capabilities.get`, `context.build`, and `memory.observe`.
- The plugin is loopback-only, fail-open, has no canonical/review authority,
  and sends only opaque hashes for OpenClaw session/run/workstream identifiers.
- The legacy OpenClaw-shaped adapter routes remain available for deliberate
  manual compatibility use.

## Proof completed

- Node lifecycle coverage validates bounded tag-safe injection, opaque scope,
  subagent suppression, and one post-success observation.
- A real local MNO HTTP lifecycle test validates the constrained token,
  `capabilities.get -> context.build -> memory.observe`, and provisional-only
  result.
- Installer/doctor, bundle, packaging, and isolated wheel/sdist verification
  cover the shipped artifact surface.

## Activation boundary

No external OpenClaw Gateway was modified for this release. On a target host,
run `mno-openclaw doctor --json`, restart the Gateway with the scoped token in
its parent environment, and prove one real root-user turn emits the ordered
`context.build` then `memory.observe` events in MNO's redacted logs.

See [OpenClaw Integration](integrations/OPENCLAW.md) and the
[automatic-layer audit](integrations/OPENCLAW_AUTOMATIC_LAYER_AUDIT_2026-08-25.md).
