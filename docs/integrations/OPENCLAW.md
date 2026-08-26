# OpenClaw Integration

## Native automatic layer (recommended)

MNO now ships an optional native OpenClaw plugin, `mno-openclaw-memory`. It is
not an MCP tool and it is not the legacy chat adapter. OpenClaw invokes it as
part of its own turn lifecycle:

1. Before an eligible root human turn, the plugin asks MNO for one bounded
   `mno.agent_context.v2` retrieval packet and injects it into that model
   prompt as `<MNO_MEMORY_CONTEXT_V1>`.
2. After that same turn succeeds, it sends one background
   `memory.observe` request. That observation is provisional only; it cannot
   write reviewed truth, publish, verify, activate, or apply review decisions.

The plugin is fail-open. If MNO is unavailable, slow, unauthorized, or returns
an invalid packet, OpenClaw proceeds without MNO context. It only accepts an
HTTP loopback MNO runtime and never retries an observation whose outcome could
be ambiguous.

The packaged plugin declares an OpenClaw plugin-API floor of `2026.8.1`; an
older host should reject installation rather than appearing to accept an
unsupported lifecycle contract.

For the source-grounded contract, authority, and validation readout, see the
[automatic-layer audit](OPENCLAW_AUTOMATIC_LAYER_AUDIT_2026-08-25.md).

It runs only for OpenClaw `user` turns with a root session. Child/subagent,
cron, heartbeat, failed, empty, and unmatched turns are skipped. The plugin
uses opaque hashes for OpenClaw session/run/workstream identifiers; raw host
handles are not sent as MNO identifiers or written to plugin diagnostics.

## Install

Start MNO with a dedicated token, then make the same variable available to the
parent process that starts the OpenClaw Gateway. Do not put the token in
`openclaw.plugin.json`, OpenClaw config, an MCP definition, or a command line.

```powershell
$env:NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN = "generate-a-long-local-secret"
mno-runtime --memories Z:\path\to\atoms.sqlite3 --episodes Z:\path\to\episode_cards.reviewed.json
```

In the environment that launches the OpenClaw Gateway, set that same variable,
then install and enable the package through OpenClaw's own CLI:

```powershell
$env:NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN = "the-same-long-local-secret"
mno-openclaw install
```

Restart the Gateway using its normal host-managed restart procedure. The MNO
installer does not copy files into arbitrary directories. It delegates install,
enablement, and removal to `openclaw plugins`, and asks OpenClaw's own config
CLI to grant this one plugin the two permissions its lifecycle needs:

```text
plugins.entries.mno-openclaw-memory.hooks.allowConversationAccess=true
plugins.entries.mno-openclaw-memory.hooks.allowPromptInjection=true
```

Those are deliberate plugin-specific grants: OpenClaw otherwise blocks
non-bundled `before_prompt_build`/`agent_end` conversation hooks. If the host
uses a restrictive global `plugins.allow` list, add `mno-openclaw-memory` to
that trusted list as well, then restart the actual Gateway process.

For development only, `mno-openclaw install --link` asks OpenClaw to use its
link mode. Production-style installs should use the normal command.

## Verify the actual layer

Run the read-only setup checks:

```powershell
mno-openclaw doctor --json
openclaw plugins inspect mno-openclaw-memory --runtime --json
openclaw plugins doctor
openclaw status --all
```

`doctor` verifies two things: that OpenClaw reports both native lifecycle hooks
(`before_prompt_build`, `agent_end`) and that the dedicated MNO credential is
authorized for exactly `health.get`, `capabilities.get`, `context.build`, and
`memory.observe`. It does not claim that the currently running Gateway
inherited the variable or that a hook has fired.

The final proof is one real root human turn. In redacted MNO integration logs,
confirm the ordered pair `context.build` then `memory.observe`. If only the
first appears, the response can still use recalled context, but no provisional
observation was recorded. If neither appears, check that the Gateway itself
was restarted from a process with
`NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN` set. A successful static plugin listing
alone is not proof of a live hook.

## Context, WSS, and authority boundaries

The injected packet is compact, fact-shaped retrieval context—not a replacement
transcript and not behavioral instructions. It is capped before insertion;
MNO keeps the wider retrieval corpus behind its own retrieval and provenance
path instead of dumping archives into the prompt.

By default the plugin supplies an opaque, strict `work_session_scope` so MNO's
work-session scratchpad can help preserve the current lane. WSS remains
ephemeral continuity context only. It is never promoted to evidence or
canonical memory merely because OpenClaw used it.

The native layer coexists with OpenClaw's ordinary sessions and any other
memory features. Avoid configuring a second automatic MNO observer for the
same turns, or you can intentionally create duplicate provisional observations.

## Diagnostics and useful feedback

The shipped commands are:

```text
mno-openclaw install | status | doctor | uninstall
```

All diagnostics are metadata-only. They do not print the token, prompt text,
retrieved context, signed handles, or chat archives. For a reproducible issue,
collect:

- `mno-openclaw doctor --json` output;
- the names of hooks shown by `openclaw plugins inspect ... --runtime --json`;
- OpenClaw and MNO versions;
- a short expected-versus-actual description and whether the real-turn ordered
  pair appeared in MNO's redacted integration logs.

Then create a redacted local support bundle:

```powershell
mno-report --title "OpenClaw MNO layer: short symptom" --summary "What failed" --steps "Exact non-sensitive reproduction" --expected "Expected lifecycle result" --actual "Observed lifecycle result" --check quick
```

Review that local bundle before any explicit submission. Do not attach bearer
tokens, raw chat exports, model prompts, `agent_context` bodies, signed receipt
handles, or OpenClaw databases.

## Legacy adapter route (manual compatibility)

The following routes remain available when another orchestrator explicitly
wants an OpenClaw-shaped request/response envelope:

- `POST /api/adapters/openclaw/chat`
- `POST /api/adapters/openclaw/context-package`

They are compatibility sidecars, not automatic lifecycle integration. For a
manual external flow use `context.build` → OpenClaw turn → `memory.observe`.
The native plugin is the preferred route when the OpenClaw host controls the
normal human-turn lifecycle.
