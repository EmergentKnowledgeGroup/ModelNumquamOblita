# V5 Execution and Freeze Plan

## Purpose
Define a finite next cycle for `NumquamOblita` and avoid open-ended feature drift.

This plan is intentionally short: five blocks, each with strict acceptance gates, then release freeze.

## Hard stop rule
After Block 5 passes and full end-to-end validation is green:
- feature development stops,
- repo enters bug-fix-only mode,
- new features require explicit version-scope approval (`v6+`).

## V5 blocks

### Block 1: Memory trigger quality tuning
Goal: reduce unnecessary memory use in routine chat.

Deliver:
- tighten front-desk routing around smalltalk/routine prompts,
- improve route reasons for skip/use decisions,
- add regression fixtures that assert low over-trigger rates.

Accept:
- routine chat fixtures route to `none` at higher precision,
- no regression on supported recall fixtures.

### Block 2: Visual memory map UI
Goal: show how memories connect.

Deliver:
- graph-style visualization from existing memory graph API,
- card-to-graph drilldown and selected-node detail panel,
- safe fallback when graph is sparse/unavailable.

Accept:
- users can navigate linked memory structure without CLI,
- graph render remains responsive on typical local datasets.

### Block 3: Simpler chat UX mode
Goal: make default runtime understandable for non-technical users.

Deliver:
- default simple mode (advanced controls collapsed),
- plain-language state badges and route explanations,
- clearer warning text for abstain/uncertain outputs.

Accept:
- first-run chat flow works without touching advanced settings,
- no loss of route/telemetry observability in advanced mode.

### Block 4: Adapter reliability hardening
Goal: keep integration paths stable under real usage patterns.

Deliver:
- stronger adapter integration coverage (`reference/openclaw/nanobot`),
- long-session and malformed-payload negative-path tests,
- contract parity checks for memory metadata fields.

Accept:
- adapter endpoint suites pass under regression and load-smoke conditions,
- no adapter-specific path bypasses claim verification rules.

### Block 5: Packaging and install path
Goal: predictable local install + launch path.

Deliver:
- one-command setup scripts for Windows and Unix-like shells,
- preflight checks and actionable error messages,
- operator docs for install, run, and diagnostics.

Implementation references:
- `setup_local.sh`, `setup_local.ps1`, `setup_local.bat`
- `tools/setup_local.py`
- `tools/preflight.py`
- `docs/OPERATOR_SETUP_AND_DIAGNOSTICS.md`

Accept:
- clean-machine setup succeeds with documented commands,
- failures produce user-readable remediation steps.

## Validation policy (each block)
- targeted tests for changed subsystem,
- full `pytest` regression sweep,
- syntax checks for touched JS files,
- full PR workflow with feedback gate before merge.

## Final signoff (end of V5)
- run full export pilot and runtime smoke,
- run trust-v3 eval path and release gate,
- publish a short release note with freeze status.
