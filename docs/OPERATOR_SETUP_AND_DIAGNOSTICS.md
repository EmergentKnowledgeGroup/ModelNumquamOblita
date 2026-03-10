# Operator Setup and Diagnostics

This is the shortest path to a clean local install and first runtime launch.

## 1) One-command setup

Run from repo root:

- Unix/macOS:
  - `./setup_local.sh`
- Windows PowerShell:
  - `.\setup_local.ps1`
- Windows Command Prompt:
  - `setup_local.bat`

What setup does:
- runs setup preflight checks,
- creates/reuses `.venv`,
- installs editable project + `pytest`,
- runs a quick smoke test,
- writes reports to `runtime/setup/`.

Useful setup modes:
- plan only (no changes): `python3 tools/setup_local.py --plan-only`
- preflight only: `python3 tools/setup_local.py --preflight-only`

## 2) Runtime/pilot preflight

Check runtime prerequisites before launch:

- `python3 tools/preflight.py --mode runtime --memories .runtime/imports/atoms.sqlite3`

Check pilot prerequisites:

- `python3 tools/preflight.py --mode pilot --memories .runtime/imports/atoms.sqlite3 --input <conversations.json>`

When checks fail, output includes plain-language remediation steps.

## 3) First launch commands

- Full export-to-pilot path:
  - `python3 tools/run_full_export_pilot.py --input <conversations.json>`
- Launch runtime from produced manifest:
  - `python3 tools/run_live_runtime.py --from-live-manifest runtime/live_runs/live_*/live_manifest.json`
- Fast local demo UI (includes wizard + memory management panes):
  - `python3 tools/run_runtime_demo.py --host 127.0.0.1 --port 7340`
  - open `http://127.0.0.1:7340/`

Windows wrappers:
- `tools\run_full_export_pilot.ps1`
- `tools\run_live_runtime.ps1`

## 4) Windows single-exe packaging

Build a bundled runtime executable (PyInstaller workflow):

- Python command:
  - `python3 tools/build_windows_single_exe.py --onefile`
- PowerShell wrapper:
  - `tools\build_windows_single_exe.ps1`
- Batch wrapper:
  - `tools\build_windows_single_exe.bat`

Packaging outputs:
- run folder: `runtime/packaging/windows_<stamp>/`
- manifest: `runtime/packaging/windows_<stamp>/packaging_manifest.json`
- expected exe path: `runtime/packaging/windows_<stamp>/dist/NumquamOblitaRuntime.exe`

Use `--dry-run` to verify packaging command/materialization paths without invoking PyInstaller.

## 5) Diagnostic artifacts

Key artifact folders:
- `runtime/setup/` setup reports (`setup_*.json`, `setup_*.md`)
- `runtime/live_runs/` import + pilot manifests
- `runtime/evals/` eval outputs
- `runtime/pilot/` pilot scorecards + support bundles

If something fails, share the latest JSON/MD report from these folders first.

## 6) Next reads

- End-to-end pipeline guide (GUI + CLI): `docs/guides/PIPELINE_END_TO_END.md`
- Runtime UI tour: `docs/guides/RUNTIME_UI_TOUR.md`
