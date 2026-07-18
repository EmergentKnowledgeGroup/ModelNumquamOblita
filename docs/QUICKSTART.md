# Quickstart

## Prerequisites

- Python `3.12+`
- Node `22+` for the desktop shell
- local disk access for the memory store and runtime state

Optional starting artifacts:
- `atoms.sqlite3`
- `episode_cards.reviewed.json`

If you do not have those yet, MNO can start from raw source files or folders.

For an installed Python package, the equivalent headless commands are:

```bash
mno-setup --plan-only
mno-import --help
mno-runtime --help
mno-mcp --help
mno-agent-mcp --help
```

Mutable stores and logs are placed in a platform user-state directory unless `MNO_RUNTIME_STATE_ROOT` is set. They are never written inside the installed package.

## Setup

- Unix/macOS: `./setup_local.sh`
- PowerShell: `./setup_local.ps1`
- Command Prompt: `setup_local.bat`

## One-click setup workspace

If you want the guided path, run one of these from the repo root:

- Unix/macOS: `./launch_setup_workspace.sh`
- PowerShell: `./launch_setup_workspace.ps1`
- Command Prompt: `launch_setup_workspace.bat`

That path will:
- run local setup unless you skip it
- install desktop shell dependencies unless you skip them
- open the desktop setup workspace
- let you choose a target and either install or export the right bundle

The Python entrypoint behind those wrappers is:

```bash
python3 tools/run_setup_workspace.py
```

In the desktop setup flow, Step 1 import is picker-first:
- `Add Files` lets you pick one or many files
- `Add Folder` lets you pick one or many folders
- you can mix folders and individual files in the same source list
- you can remove entries or clear the whole list before import
- you can choose `New Store` or `Add To Existing Store`

Advanced path entry still exists as a fallback, but the normal path is click-to-pick.

Useful setup checks:
- `python3 tools/setup_local.py --plan-only`
- `python3 tools/setup_local.py --preflight-only`

Default setup creates `.venv/`, installs the package editable, installs `pytest`, and runs a smoke test.

Public docs use `runtime/imports/` as the canonical local import store location. Older `.runtime/imports/` folders may still be detected as a compatibility fallback, but new setup/import flows should write to `runtime/imports/`.

## Fastest raw-source path

Sanitization is automatic during import:
- supported files are normalized into turns
- whitespace is cleaned
- roles are normalized
- timestamps are normalized when possible
- junk folders like `.git`, `.venv`, and `node_modules` are skipped
- unsupported tool/system noise is filtered before candidate extraction

1. Import your source file or folder:

```bash
python3 tools/import_memories.py \
  --input /absolute/path/to/source-or-folder \
  --store runtime/imports/atoms.sqlite3
```

2. Start the runtime:

```bash
python3 tools/run_live_runtime.py \
  --memories runtime/imports/atoms.sqlite3 \
  --config runtime/state/mno-runtime-policy.v1.json
```

3. Check health:

```bash
curl http://127.0.0.1:7340/api/runtime/health
```

4. Check the public integration contract:

```bash
curl "http://127.0.0.1:7340/api/integration/v1/capabilities?schema_version=integration.v1&request_id=req_quickstart_caps_001"
```

## Existing-store path

If you already have an MNO store and optional reviewed cards:

```bash
python3 tools/run_live_runtime.py \
  --memories /absolute/path/to/atoms.sqlite3 \
  --episodes /absolute/path/to/episode_cards.reviewed.json
```

Plan-only validation:

```bash
python3 tools/run_live_runtime.py \
  --memories /absolute/path/to/atoms.sqlite3 \
  --episodes /absolute/path/to/episode_cards.reviewed.json \
  --plan-only
```

Manifest-based launch:

```bash
python3 tools/run_live_runtime.py \
  --from-live-manifest runtime/live_runs/live_*/live_manifest.json
```

The `--config` file selects the validated v0.2 runtime policy for both retrieval and session behavior. Omit it to use the setup-managed policy when present, or fresh standard defaults otherwise.

### What live memory means

- Importing a file creates durable evidence atoms.
- Calling `memory.observe` after a live turn can create lower-authority provisional observations. User, tool, and external candidates require server-signed source registrations; assistant candidates require a server-signed retrieval receipt to contribute support.
- “Remember this” still needs `writeback.propose`, then a human holding `review_apply` to resolve/apply it. Apply creates an `evidence_atom` with `human_reviewed=false`, not canonical truth.
- STM and WSS help the current work/session but are not evidence.

## Desktop launch

- `npm run desktop:dev --prefix app/desktop`
- `npm run desktop:test --prefix app/desktop`
- `npm run desktop:pack:dir --prefix app/desktop`

The desktop app is the easiest local operator path if you want:
- import/build/review/publish workflow
- memory graphs
- draft curation lane
- continuity surfaces like pins, wake-up pack, and resume pack
- WSS `scratchpad_ephemeral` continuity for strict-scope agent context packages
- managed install or export for assistant/agent targets

## MCP launch

Against an existing runtime over stdio:

```bash
python3 tools/run_mcp_server.py \
  --transport stdio \
  --runtime-base-url http://127.0.0.1:7340
```

HTTP MCP sidecar:

```bash
python3 tools/run_mcp_server.py \
  --transport http \
  --runtime-base-url http://127.0.0.1:7340 \
  --http-host 127.0.0.1 \
  --http-port 8765
```

Combined runtime + MCP launcher:

```bash
python3 tools/run_agent_live_mcp.py \
  --memories /absolute/path/to/atoms.sqlite3 \
  --episodes /absolute/path/to/episode_cards.reviewed.json
```

This launcher starts:
- the runtime
- the MCP sidecar
- a local assistant/agent-friendly tool path in one step

Exported integration bundles use `mno-runtime` and `mno-agent-mcp`. Install the Python package first; exported launchers fail with an explicit `*_NOT_INSTALLED` result and make no setup changes when those commands are absent.

See [Compatibility and Support](COMPATIBILITY_AND_SUPPORT.md) for supported hosts and artifact boundaries.

## What to read next

- [Pipeline Guide](PIPELINE_GUIDE.md)
- [Agent Integration](AGENT_INTEGRATION.md)
- [MCP Integration](MCP_INTEGRATION.md)
- [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md)
