# Troubleshooting

## Setup fails

Run:

```bash
python3 tools/setup_local.py --preflight-only
```

Then inspect:
- Python version
- Node version for desktop work
- missing local memory artifacts

## Runtime will not launch

Validate the launch plan first:

```bash
python3 tools/run_live_runtime.py --memories <atoms.sqlite3> --episodes <episode_cards.reviewed.json> --plan-only
```

## macOS packaging on external or network-mounted volumes

If `npm run desktop:pack:dir --prefix app/desktop` fails during `codesign` with `resource fork, Finder information, or similar detritus not allowed`, the checkout is likely on a filesystem that preserves macOS metadata in a way signing does not like.

Practical fixes:
- use the default local unsigned pack path from this repo for a local `.app` directory build; it now sets `mac.identity=null` so electron-builder skips signing entirely
- build the signed/notarized mac release from a local APFS checkout or CI runner instead of an SMB-mounted workspace
- if you need to force a specific interpreter for runtime bundling, set `MNO_PYTHON` to a healthy Python 3.12+ binary such as `/opt/homebrew/bin/python3`
- prefer the local APFS workspace documented in `docs/MAC_PACKAGING.md` for signed app, DMG, and ZIP builds

Then check:
- file paths exist
- reviewed episode file matches the intended memory store
- port is free

## MCP cannot connect

Check runtime health first:

```bash
curl http://127.0.0.1:7340/api/runtime/health
```

Then re-run MCP with the correct `--runtime-base-url`.

If auth is enabled, also check the token source:
- `NO_MCP_AUTH_TOKEN`
- `NO_MCP_OPERATOR_TOKEN`
- `NO_MCP_ADMIN_TOKEN`

## Desktop issues

- run `npm run desktop:test --prefix app/desktop`
- rebuild the managed runtime with `npm run desktop:bundle-runtime --prefix app/desktop`
- if old pack output is confusing the build, run `npm run desktop:clean-pack-output --prefix app/desktop`
- if you just want the guided launch path again, rerun:
  - `./launch_setup_workspace.sh`
  - `./launch_setup_workspace.ps1`
  - `launch_setup_workspace.bat`

## integration-v1 calls fail

Check:
- `schema_version` is `integration.v1`
- bearer auth is present if auth is enabled
- `Idempotency-Key` is present for `writeback.propose`
- your `session_id` is stable for the conversation you are testing

Good first probe:

```bash
curl "http://127.0.0.1:7340/api/integration/v1/capabilities?schema_version=integration.v1&request_id=troubleshoot_caps"
```

## WSS context does not appear

WSS attaches only to runtime v2 context packages when strict scope identity is present. Check that the request supplies stable `work_session_scope.thread_id` and `work_session_scope.workstream_key`, uses the same project/runtime store, and is going through a context-package route rather than the evidence-focused `integration-v1` envelope.

Missing, incomplete, or degraded scope fails closed. In that case the package should omit `work_session_context` instead of guessing.

## Import looks thin or noisy

If the source is mixed or fragmented:
- point import at one folder instead of hand-picking many files
- inspect the resulting store with the desktop app or runtime memory views
- rebuild episode cards after import instead of assuming draft cards already exist
