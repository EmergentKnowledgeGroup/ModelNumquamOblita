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

## Stable parity tool names

The clean repo ships stable MCP parity tools for the public integration contract:
- `integration.context.build`
- `integration.context.why`
- `integration.memory.source.register`
- `integration.memory.observe`
- `integration.memory.maintain`
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
- read-heavy agent flows

## What MCP is not

Do not treat MCP as the only official contract if you are building a new orchestrator. The preferred hot-loop boundary is still:

`integration-v1`

## Related docs

- [Agent Integration](AGENT_INTEGRATION.md)
- [API](API.md)
- [Configuration](CONFIGURATION.md)
- [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md)
