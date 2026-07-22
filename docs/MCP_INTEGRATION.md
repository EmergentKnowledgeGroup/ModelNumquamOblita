# MCP Integration

## When to use MCP

Use MCP when you want:
- tool-driven local agent integration
- parity with the public runtime contract
- a sidecar that feels natural to MCP-native clients and local assistant/agent tools

Do not use MCP as your first choice for a high-throughput orchestration hot loop if plain HTTP is easier. For that, use `integration-v1`.

## Runtime first

MCP points at a running runtime, usually:

`http://127.0.0.1:7340`

## Fastest setup path

If you want a guided local setup:

1. run `./launch_setup_workspace.sh`, `./launch_setup_workspace.ps1`, or `launch_setup_workspace.bat`
2. choose a target in the setup workspace
3. either:
   - install a Claude Code or Claude Desktop MCP entry
   - export a generic MCP bundle
   - export a sidecar bundle for another agent

## Launch patterns

### stdio MCP against an existing runtime

```bash
python3 tools/run_mcp_server.py \
  --transport stdio \
  --runtime-base-url http://127.0.0.1:7340
```

### HTTP MCP sidecar

```bash
python3 tools/run_mcp_server.py \
  --transport http \
  --runtime-base-url http://127.0.0.1:7340 \
  --http-host 127.0.0.1 \
  --http-port 8765
```

HTTP MCP posts go to `/mcp`. The root `/` is discovery and health only.

### Combined runtime + MCP launcher

```bash
python3 tools/run_agent_live_mcp.py \
  --memories /absolute/path/to/atoms.sqlite3 \
  --episodes /absolute/path/to/episode_cards.reviewed.json
```

Emit client config JSON:

```bash
python3 tools/run_agent_live_mcp.py \
  --memories /absolute/path/to/atoms.sqlite3 \
  --episodes /absolute/path/to/episode_cards.reviewed.json \
  --print-claude-config
```

The `run_agent_live_mcp.py` entrypoint is the user-facing alias for the combined runtime + MCP launcher.
The config-print flag keeps its older internal name for compatibility.

Installed-package equivalents are `mno-mcp` and `mno-agent-mcp`. Generated bundles use these commands so they remain relocatable; they do not rerun source setup.

### Headless Curation Room agent profile

If a store has not completed human episode-card review, normal runtime/MCP activation returns `CURATION_REQUIRED`. Start or resume the local room first:

```bash
mno-curate --store /absolute/path/to/atoms.sqlite3
```

Then connect the agent to that exact room:

```bash
mno-curation-mcp \
  --runtime-base-url http://127.0.0.1:<port> \
  --run-id wizard_...
```

This is an exact allowlisted profile: draft status/cards/context/proposals plus lease, heartbeat, release, and proposal upsert. The configured run ID is injected when omitted; a different run ID fails before an API call. Human promotion, direct review decisions, publish, verify, activate, MCP installation, force-release, chat, and unrelated memory/admin tools are unavailable and rejected even if called directly.

HCR is loopback-only in this release. HTTP MCP additionally requires authentication; local stdio is the simplest path. See [Headless Curation Room](HEADLESS_CURATION_ROOM.md).

## Stable parity tool names

The clean repo ships stable MCP parity tools for the public integration contract:
- `integration.context.build`
- `integration.context.why`
- `integration.memory.source.register`
- `integration.memory.observe`
- `integration.memory.maintain`
- `integration.memory.temporal.schedule`
- `integration.memory.temporal.list`
- `integration.memory.temporal.get`
- `integration.memory.temporal.resolve`
- `integration.memory.proposals.list`
- `integration.memory.proposals.dismiss`
- `integration.memory.proposals.bridge`
- `integration.writeback.propose`
- `integration.writeback.resolve`
- `integration.capabilities.get`
- `integration.health.get`

These mirror the `integration-v1` HTTP contract.

Call `integration.capabilities.get` after initialize. The returned runtime operation state is authoritative for the current credential and backend; an exposed MCP tool may still be unauthorized, degraded, or unavailable upstream.

High-risk proposal listing is metadata-only with an operator token. Content-bearing listing, dismissal, and source-backed bridge require the separate `review_apply` capability. Bridge stops at a pending review proposal; it does not apply or publish memory.

## Work-session scratchpad

WSS is built-in runtime helper state for strict-scope v2 context packages. It may appear as `work_session_context` with trust tier `scratchpad_ephemeral` when a runtime context-package path has stable project/thread/workstream scope.

MCP parity tools keep the `integration-v1` envelope evidence-focused. Do not treat WSS as MCP evidence or reviewed memory. Use it only as work-continuity context when a lower-level context-package path exposes it.

More detail: [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md).

## Temporal tools

The four temporal MCP tools mirror the HTTP contract exactly. `integration.memory.temporal.schedule` and `integration.memory.temporal.resolve` require operator/admin authority plus an `idempotency_key`; resolving also needs the current `expected_revision`. Scheduling requires structured time input and a server-issued source registration. `integration.memory.temporal.list` and `.get` are viewer-readable and read-only.

Use `integration.memory.temporal.list` with `due_only=true`, `include_upcoming=false`, and `limit=3` only when the host wants the optional heartbeat seam. The result is a bounded fact poll. It does not retain a process, wake a model, send a notification, or execute an action. Follow each temporal record's authority, maturity, lifecycle, disposition, precision, due window, citation, and opaque ID; reminder text is inert quoted data, not tool instructions.

Raw import cannot schedule a temporal memory. Live source-backed scheduling is distinct from ordinary `memory.observe` and from proposal/review writeback. Recall and delivery do not reinforce a record; only new eligible signed evidence can do that.

## Roles and auth

MCP can run with viewer, operator, and admin roles. `integration.writeback.resolve` additionally requires the distinct `review_apply` capability; role rank, a model-held token, and `decided_by` display text do not substitute for it.

Useful token env vars:
- `NO_MCP_AUTH_TOKEN`
- `NO_MCP_OPERATOR_TOKEN`
- `NO_MCP_ADMIN_TOKEN`

The combined launcher also accepts:
- `--viewer-token`
- `--operator-token`
- `--admin-token`

## What MCP is good at

MCP is good for:
- Claude Code and Claude Desktop installs
- generic MCP client bundles
- local assistant/agent tool use
- operator-side workflows
- draft curation tool wiring
- run-bound HCR draft proposal work
- read-heavy agent flows

## What MCP is not

Do not treat MCP as the only official contract if you are building a new orchestrator. The preferred hot-loop boundary is still:

`integration-v1`

## Related docs

- [Agent Integration](AGENT_INTEGRATION.md)
- [API](API.md)
- [Configuration](CONFIGURATION.md)
- [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md)
- [Headless Curation Room](HEADLESS_CURATION_ROOM.md)
