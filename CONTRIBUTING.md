# Contributing

Thanks for helping make MNO more useful and more honest.

## Project Rules

- No memory claim without evidence.
- Human review remains authoritative.
- Draft, proposal, provisional, feedback, and helper layers must not silently
  become reviewed truth.
- WSS `scratchpad_ephemeral` state may help agents continue local work, but it
  must not become memory evidence, reviewed truth, or publish/verify truth.
- Fix root-cause behavior, not benchmark-shaped symptoms.
- Keep changes lean, reversible, and covered by targeted tests.

## Before Opening A Pull Request

Run the relevant checks from the repo root:

```bash
python -m pytest -q
npm run desktop:test --prefix app/desktop
```

For smaller changes, run the focused tests that prove your change first, then
broaden to the full suites when shared behavior or public contracts are touched.

## Runtime Data

Do not commit populated `runtime/` data, memory stores, WSS sidecars, setup
reports, checkpoint files, desktop build output, private paths, or copied
dependencies.

The public repo should contain source, docs, tests, launch scripts, and small
required assets only.
