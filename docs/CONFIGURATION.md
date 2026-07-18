# Configuration

## Installed state root

Source checkout uses `runtime/` by default. Installed packages use a platform user-state directory, never `site-packages`. Set `MNO_RUNTIME_STATE_ROOT` to an explicit writable location when code is read-only or state ownership must be controlled. Canonical imports live under `runtime/imports`; legacy `.runtime/imports` is fallback-only and emits a warning when both locations exist.

## Runtime inputs

The main runtime inputs are:
- `--memories <atoms.sqlite3>`
- `--episodes <episode_cards.reviewed.json>`
- `--from-live-manifest <live_manifest.json>`
- `--config <mno-runtime-policy.v1.json>`

`tools/run_live_runtime.py --config <json>` validates one policy object before constructing the runtime. Without an explicit file it uses `runtime/state/mno-runtime-policy.v1.json` when setup has created it; otherwise it uses the fresh standard defaults. `--plan-only` reports the resolved effective policy source.

## v0.2 provisional-memory policy

Fresh standard policy enables low-risk provisional capture, retrieval, bounded maintenance, and deterministic consolidation. An existing policy file that omits the v0.2 fields preserves the older disabled posture; its reported policy source is `upgrade_preserved`. An explicit provisional block is reported as `custom`.

```json
{
  "provisional_memory": {
    "enabled": true,
    "retrieval_enabled": true,
    "stm_sweep_enabled": true,
    "consolidation_enabled": true,
    "maintenance_enabled": true,
    "dormant_days": 90,
    "archive_days": 365,
    "plan_currentness_days": 30,
    "source_registration_ttl_seconds": 604800,
    "maintenance_max_records": 25,
    "policy_version": "v0.2"
  }
}
```

`maintenance_max_records` is validated at 1–100. Source-registration TTL is 60–2,592,000 seconds. Archive days must exceed dormant days. This policy controls provisional helper-memory behavior only; it never enables autonomous canonical publication or review/publish/activation mutation.

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

## Work-session scratchpad

The work-session scratchpad is a built-in runtime helper for agent continuity. It stores one project-local sqlite sidecar under the runtime state root and can attach deterministic summaries to strict active project/thread/workstream scoped v2 context-package requests as `scratchpad_ephemeral` helper state when policy allows injection and the request has not explicitly disabled `include_work_session_context`.

It does not:
- mutate MemoryPack, reviewed truth, review decisions, publish state, or verifier behavior
- support memory claims
- change prompt history
- attach when strict active scope identity is missing or degraded

Key config block:

```json
{
  "work_session_scratchpad": {
    "enabled": true,
    "inject_enabled": true,
    "resume_injection_enabled": true,
    "diagnostics_enabled": false,
    "max_entries_per_scope": 200,
    "max_injected_items": 8,
    "max_injected_chars": 2400,
    "max_raw_ref_bytes": 2000000,
    "retention_days": 14,
    "min_replaceability_score": 0.7
  }
}
```

Strict active scope identity is the safety gate. Callers provide `work_session_scope`; degraded, inactive, or missing scope identity fails closed, and scratchpad rows remain non-authoritative helper state. Operational config can disable WSS, and callers can explicitly suppress WSS for a package, but the product behavior is live-on for strict active-scope context packages.

Canonical behavior notes live in [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md).

## Integration auth

Useful env vars for the HTTP integration contract:
- `NO_INTEGRATION_RUNTIME_MODE`
- `NO_INTEGRATION_VIEWER_TOKEN`
- `NO_INTEGRATION_OPERATOR_TOKEN`
- `NO_INTEGRATION_ADMIN_TOKEN`
- `NO_INTEGRATION_REVIEW_APPLY_TOKEN`
- `NO_INTEGRATION_TOKENS_FILE`
- `NO_INTEGRATION_SECRET_MANAGER_PROVIDER`
- `NO_INTEGRATION_SECRET_MANAGER_COMMAND`

Practical rule:
- local/dev can use simple local tokens
- production should load tokens from a real file or secret manager path
- `NO_INTEGRATION_REVIEW_APPLY_TOKEN` is a human-held secret channel; the MCP launchers intentionally do not accept it through command-line arguments and generated model bundles must not contain it

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
- work-session scratchpad

These are runtime helper layers, not reviewed truth.

## SQLite backup and downgrade

Atom, provisional, and high-risk proposal stores expose a SQLite backup operation (`backup_to`) that captures a transactionally consistent live database, including committed WAL state. Do not prove a backup by copying a live `.sqlite3`, `-wal`, and `-shm` family. For a v0.1-to-v0.2 upgrade, keep the verified pre-migration backup: v0.1 is not expected to open a migrated provisional v3 sidecar, so downgrade means restoring that backup.

## Desktop shell

The desktop shell bundles the runtime according to:
- `app/desktop/runtime-bundle.manifest.json`
- `app/desktop/package.json`

## Temporal policy

Temporal settings live under `provisional_memory`. The default compact temporal addition is 192 estimated tokens (hard cap 256), with three due items (hard cap eight), 160 UTF-8 bytes per compact due summary (hard cap 240), two dormant fallback items (hard cap four), 256 active temporal records, a 10-year future/snooze horizon, 30 days of past-due creation, seven days of decay grace, and a 24-hour delivery redelivery interval.

Relevant keys are `temporal_enabled`, `temporal_timezone`, `temporal_context_token_budget`, `temporal_due_max_items`, `temporal_due_summary_max_bytes`, `temporal_active_record_limit`, `temporal_future_horizon_years`, `temporal_snooze_horizon_years`, `temporal_past_due_days`, `temporal_grace_days`, `temporal_redelivery_hours`, and `temporal_dormant_fallback_items`. All configured values are bounded by the hard caps validated by the runtime; no item is split to fit a budget.

The complete agent-context envelope uses `efficiency.context_token_budget` (2,800 by default, 4,096 hard at render time). Fresh/custom v0.2.2 configuration rejects a larger value. Upgrade loading preserves an existing larger legacy value verbatim for configuration compatibility, but the active renderer still clamps it to 4,096; preservation never expands the per-turn context.

`temporal_timezone` must be an IANA name. Resolution is configured IANA name, reliable system IANA name, then visible `UTC` fallback. Windows IDs and abbreviations such as `CST` are rejected. Disabling temporal features preserves stored v4 rows; it does not silently delete, canonize, or downgrade them.
