# MNO Headless Curation Room Blockerboard

**Source spec:** `docs/MNO_HEADLESS_CURATION_ROOM_SPEC_2026-07-21.md`

## Stop-Ship Rules

- Stop if an agent can create or promote a human review decision without explicit human action.
- Stop if HCR duplicates or diverges from wizard review/publish/verify/activate truth.
- Stop if a normal headless launch can silently treat an uncurated store as an activated reviewed set.
- Stop if HCR binds publicly by default or leaks local paths/content into external telemetry.
- Stop if the desktop wizard regresses.
- Stop if CLEAN receives partial or unvalidated DEV state.

## Board

| ID | Priority | Status | Blocker | Exit Evidence |
|---|---:|---|---|---|
| HCR-001 | P0 | CLOSED | No standalone headless curation entrypoint | `mno-curate` input/store/resume tests green |
| HCR-002 | P0 | CLOSED | No small machine-readable curation-wall contract | HCR status transition tests green |
| HCR-003 | P0 | CLOSED | Raw headless launch can bypass reviewed episode workflow | default wall + explicit bypass tests green |
| HCR-004 | P0 | CLOSED | Existing review UI is packaged as the full runtime wizard | `/curate/<run_id>` focused UI browser proof green |
| HCR-005 | P0 | CLOSED | Human/agent authority could blur in a convenience flow | proposal separation and human reviewer tests green |
| HCR-006 | P1 | CLOSED | HCR process/browser behavior may be non-portable | PR #17 Python and desktop matrices passed on Windows, Linux, and macOS; release artifact proof passed |
| HCR-007 | P1 | CLOSED | Docs still describe Claude-specific draft curation and raw runtime commands | user/LLM/API/docs/flowchart parity audit green |
| HCR-008 | P1 | CLOSED | Packaged wheel/sdist may omit HCR UI or command | isolated package install smoke green |
| HCR-009 | P1 | CLOSED | Desktop wizard may regress from shared UI changes | desktop Node + runtime UI integration tests green |
| HCR-010 | P1 | CLOSED | Dirty DEV SSoT could contaminate CLEAN staging | surgical HCR-only CLEAN port, full suite, package proof, and diff-scope audit green |
| HCR-011 | P0 | CLOSED | Generic MCP can expose unrelated tools or accept a different run ID | exact HCR allowlist and cross-run isolation tests green |
