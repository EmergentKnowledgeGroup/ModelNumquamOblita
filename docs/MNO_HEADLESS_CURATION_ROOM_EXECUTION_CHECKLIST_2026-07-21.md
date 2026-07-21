# MNO Headless Curation Room Execution Checklist

**Source spec:** `docs/MNO_HEADLESS_CURATION_ROOM_SPEC_2026-07-21.md`

## Boundaries

- [x] Generic HCR contract; no Hermes-specific behavior.
- [x] Existing wizard state and APIs remain the SSoT.
- [x] Human review remains authoritative.
- [x] Draft-only MCP remains unable to publish, verify, activate, install, or self-promote.
- [x] CLEAN remains untouched until DEV validation is green.

## Contract And CLI

- [x] Add lean HCR status computation and endpoint.
- [x] Add `mno-curate` console entrypoint.
- [x] Add `mno-curation-mcp` with an exact run-bound curation-only tool profile.
- [x] Support `--input`, `--store`, and `--run-id` flows.
- [x] Default HCR to loopback and reject non-loopback binding.
- [x] Emit stable machine-readable status and URL.
- [x] Open the browser by default with `--no-open` support.
- [x] Shut down the child runtime cleanly on signals and errors.
- [x] Reject mismatched run IDs, hidden tool dispatch, and agent force-release.

## HCR Surface

- [x] Serve `/curate/<run_id>` from the packaged runtime UI.
- [x] Load exactly the requested run.
- [x] Focus the UI on Review -> Publish -> Verify -> Activate.
- [x] Preserve proposal comparison, bounded context, audit/lease visibility, and direct review editing.
- [x] Keep desktop wizard behavior unchanged.
- [x] Verify desktop and mobile layout.

## Curation Wall

- [x] Normal `mno-runtime` launch without reviewed episode cards fails with `CURATION_REQUIRED`.
- [x] Add explicit `--allow-uncurated` development/operator bypass.
- [x] Mark bypass binding and startup output as uncurated.
- [x] Keep setup mode and plan-only diagnostics deterministic.

## Tests

- [x] Unit-test HCR state transitions.
- [x] Integration-test HCR route and exact run binding.
- [x] Integration-test store/input/resume CLI preparation.
- [x] Test exact MCP allowlist, direct-call rejection, and cross-run isolation.
- [x] Test loopback-only enforcement and browser opt-out.
- [x] Test curation wall and explicit bypass.
- [x] Re-run draft-curation, review, publish, verify, activate, runtime, MCP, packaging, and distribution tests.
- [x] Run full Python suite and desktop Node suite.
- [x] Run browser QA with populated cards on desktop and mobile.

## Documentation And Release

- [x] Update README, QUICKSTART, API, configuration, troubleshooting, MCP/agent integration, distribution, security, and LLMS guidance.
- [x] Update changelog and release-facing notes.
- [x] Update architecture diagrams/flowcharts and generated exports.
- [x] Verify docs and packaged artifacts contain no DEV-only paths or private data.
- [x] Snapshot post-green DEV checkpoint.
- [x] Port only the validated HCR diff into CLEAN.
- [x] Run CLEAN validation and diff-scope audit.
- [ ] Commit, push, open PR, and run review/CI to merge readiness.
