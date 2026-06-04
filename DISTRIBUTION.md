# Distribution Notes

This repo is intended to be the public source distribution for
ModelNumquamOblita.

## What Should Ship

- `engine/`
- `app/desktop/`
- `tools/`
- `tests/`
- `skills/`
- `docs/`
- launch and setup scripts
- root metadata files such as `README.md`, `LICENSE`, `SECURITY.md`,
  `CONTRIBUTING.md`, and `pyproject.toml`
- the empty `runtime/` workspace skeleton and `.gitkeep` files
- generated public visual exports under `docs/visuals/exports/`

## What Should Not Ship

- populated memory stores
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
```

Passing a narrow smoke test is not enough to call the repo release-ready. The
public branch should be clean, cloneable, documented, and test-green.
