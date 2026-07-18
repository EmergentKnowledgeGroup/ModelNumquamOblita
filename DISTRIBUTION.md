# Distribution Notes

This repo is intended to be the public source distribution for
ModelNumquamOblita.

## v0.2.1 Artifact Contract

- The Python wheel is a runnable headless runtime, MCP sidecar, import CLI, and setup CLI. It includes the runtime web UI and uses platform user state outside `site-packages`.
- The source distribution contains the public source tree plus an empty runtime skeleton. It must never contain a populated store, WAL/SHM file, trace, checkpoint, or private research tree.
- The Electron desktop application is a separate artifact with a managed Python runtime. It must be built per target OS; no desktop installer is implied by the Python wheel.
- Exported integration launchers call installed `mno-runtime` and `mno-agent-mcp` commands. They never embed the builder's checkout and never install dependencies at launch time.

See [Compatibility and Support](docs/COMPATIBILITY_AND_SUPPORT.md) for the claimed host matrix.

## What Should Ship

- `engine/`
- `app/desktop/`
- `tools/`
- `tests/`
- `skills/`
- `docs/`
- launch and setup scripts
- root metadata files such as `README.md`, `LICENSE`, `SECURITY.md`,
  `CONTRIBUTING.md`, `LLMS.md`, and `pyproject.toml`
- the empty `runtime/` workspace skeleton and `.gitkeep` files
- generated public visual exports under `docs/visuals/exports/`
- canonical WSS documentation such as `docs/WORK_SESSION_SCRATCHPAD.md`

## What Should Not Ship

- populated memory stores
- populated WSS scratchpad sidecars
- private source datasets
- generated checkpoint files
- local setup reports
- desktop `.runtime-cache/`
- desktop `dist/`, `out/`, or bundled runtime output
- copied dependency folders
- private agent configs
- benchmark debris or local audit reports

## Release Smoke Commands

Run these before publishing a release branch:

```bash
python tools/setup_local.py --plan-only
python tools/run_live_runtime.py --setup-mode --plan-only
python tools/run_mcp_server.py --help
python -m pytest -q
npm run desktop:test --prefix app/desktop
python -m build --outdir runtime/tmp/release-dist
python tools/verify_distribution_artifacts.py --dist-dir runtime/tmp/release-dist --work-root runtime/tmp/artifact-proof
```

Passing a narrow smoke test is not enough to call the repo release-ready. The
public branch should be clean, cloneable, documented, and test-green.
