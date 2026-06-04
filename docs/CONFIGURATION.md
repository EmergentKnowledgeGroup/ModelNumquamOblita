# Configuration

## Runtime inputs

The main runtime inputs are:
- `--memories <atoms.sqlite3>`
- `--episodes <episode_cards.reviewed.json>`
- `--from-live-manifest <live_manifest.json>`

## Guided setup entrypoints

If you want the guided desktop setup flow instead of launching pieces by hand:
- `./launch_setup_workspace.sh`
- `./launch_setup_workspace.ps1`
- `launch_setup_workspace.bat`

These wrappers call:

```bash
python3 tools/run_setup_workspace.py
```

## Runtime state root

Set `MNO_RUNTIME_STATE_ROOT` to move generated runtime state away from the repo-local `runtime/` directory.

This is useful when you want:
- stores and logs outside the repo
- multiple runtime workspaces
- cleaner packaging or external drive layouts

## Retrieval ANN sidecar

The clean repo ships with the bounded local ANN sidecar enabled by default.

`ANN` means `approximate nearest neighbor`.

What it does:
- adds extra retrieval candidates before the normal fusion/ranking path
- stores a local sqlite sidecar next to the main atom store unless you override the path
- falls back cleanly if the sidecar is missing, stale, mismatched, or slow

What it does not do:
- replace the normal retriever
- mutate memory truth
- bypass review, publish, or verifier behavior

Key config block:

```json
{
  "retrieval": {
    "ann_sidecar": {
      "enabled": true,
      "top_k_ann": 16,
      "candidate_cap_ratio": 0.25,
      "candidate_cap_floor": 4,
      "max_latency_ms": 35.0,
      "embedding_backend": "hashed-simhash-sqlite",
      "embedding_store_path": "",
      "rebuild_mode": "lazy"
    }
  }
}
```

Kill switch:

```json
{
  "retrieval": {
    "ann_sidecar": {
      "enabled": false
    }
  }
}
```

## Raw-context sidecar

This sidecar preserves bounded original wording from normalized source turns. It is written during import and only read back for explicit provenance or quote-style requests.

Key config block:

```json
{
  "retrieval": {
    "raw_context_sidecar": {
      "write_enabled": true,
      "read_enabled": true,
      "neighbor_turns": 1,
      "max_turns": 3,
      "max_chars": 1200
    }
  }
}
```

Kill switches:

```json
{
  "retrieval": {
    "raw_context_sidecar": {
      "write_enabled": false,
      "read_enabled": false
    }
  }
}
```

Truth-family lineage for reviewed cards does not require a separate toggle. It is carried as reviewed metadata during human review and compile.

## Integration auth

Useful env vars for the HTTP integration contract:
- `NO_INTEGRATION_RUNTIME_MODE`
- `NO_INTEGRATION_VIEWER_TOKEN`
- `NO_INTEGRATION_OPERATOR_TOKEN`
- `NO_INTEGRATION_ADMIN_TOKEN`
- `NO_INTEGRATION_TOKENS_FILE`
- `NO_INTEGRATION_SECRET_MANAGER_PROVIDER`
- `NO_INTEGRATION_SECRET_MANAGER_COMMAND`

Practical rule:
- local/dev can use simple local tokens
- production should load tokens from a real file or secret manager path

## MCP settings

Useful MCP launch settings:
- `--runtime-base-url`
- `--transport stdio|http`
- `--http-host`
- `--http-port`

Useful MCP env vars:
- `NO_MCP_AUTH_TOKEN`
- `NO_MCP_OPERATOR_TOKEN`
- `NO_MCP_ADMIN_TOKEN`
- `NO_MCP_STDIO_TRACE`

## Runtime helper surfaces

The clean repo also has configurable runtime helper features such as:
- provisional memory
- retrieval feedback capture
- pins and action log
- wake-up pack
- resume pack

These are runtime helper layers, not reviewed truth.

## Desktop shell

The desktop shell bundles the runtime according to:
- `app/desktop/runtime-bundle.manifest.json`
- `app/desktop/package.json`
