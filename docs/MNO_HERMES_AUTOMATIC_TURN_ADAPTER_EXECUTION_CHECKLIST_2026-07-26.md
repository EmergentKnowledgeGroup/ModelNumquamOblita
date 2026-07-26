# MNO Hermes Automatic Turn Adapter Execution Checklist

**Status:** LOCKED v1.0 — 2026-07-26
**Spec:** [MNO Hermes Automatic Turn Adapter Specification](MNO_HERMES_AUTOMATIC_TURN_ADAPTER_SPEC_2026-07-26.md)
**Blockerboard:** [MNO Hermes Automatic Turn Adapter Blockerboard](MNO_HERMES_AUTOMATIC_TURN_ADAPTER_BLOCKERBOARD_2026-07-26.md)

Statuses: `PENDING`, `IN PROGRESS`, `BLOCKED`, `DONE`.

## Phase 0 — locked contract

- `DONE` Inspect MNO and pinned Hermes v0.19.0 source behavior.
- `DONE` Run Sol gap/edge, touchpoint, and guardrail SpecSwarm lanes.
- `DONE` Run fresh Sol final-QA consolidation.
- `DONE` Fold all accepted findings into exactly the spec, checklist, and blockerboard.
- `DONE` Mark all three artifacts `LOCKED` v1.0, scan contradictions, and write the post-lock checkpoint.

## Phase 1 — tests first

- `DONE` Add failing tests for strict loopback URL, scoped token source, config bounds, and redaction.
- `DONE` Add failing tests for eligibility, exact 4,096-character normalization, and adversarial JSON-safe wrapper.
- `DONE` Add failing tests for stable session ID, unique per-turn run ID, absent-turn full no-op, signed-handle pairing, duplicate tombstones, cached origin eligibility, TTL, and cleanup.
- `DONE` Add failing tests for shared 2.5-second cold-capabilities/context budget and sub-25 ms post enqueue.
- `DONE` Add failing tests for one-attempt worker, queue age/overflow, no retry, and no persistent spool.
- `DONE` Add failing tests for canonical/review operation denial and no truth-store mutation.
- `DONE` Add failing tests for installer ownership, atomic update, reparse/path containment, prior enable state, force, doctor/status, and uninstall.
- `DONE` Add failing tests for packaged plugin data, ordinary bundle artifacts, and HCR draft-only bundle exclusion.

## Phase 2 — standalone plugin

- `DONE` Add packaged `engine/integrations/hermes_plugin` tree and manifest.
- `DONE` Implement dependency-free registration for pre/post/end/finalize/reset.
- `DONE` Implement strict config and loopback HTTP client.
- `DONE` Implement opaque installation/session/turn identity derivation.
- `DONE` Implement exact pending correlation with no FIFO fallback.
- `DONE` Implement independent context/observe capability gates and 8,192-character/4,096-token JSON-safe neutral context rejection.
- `DONE` Implement non-blocking post enqueue and one-attempt background observation.
- `DONE` Implement bounded pending/tombstone/queue cleanup and metadata-only diagnostics.
- `DONE` Prove `on_session_end` preserves a successfully queued observation while finalize cleans the old session and reset defensively cleans the new session.
- `DONE` Make enqueue, dequeue, and reset/finalize queue filtering one synchronized queue transaction; release synchronization before HTTP and prove concurrent cross-session cleanup cannot lose another session's observation.
- `DONE` Contain all adapter exceptions and secret-bearing response bodies.

## Phase 3 — auth, installer, and diagnostics

- `DONE` Add dedicated `NO_INTEGRATION_HERMES_ADAPTER_TOKEN` principal limited to four operations.
- `DONE` Add `mno-hermes` console entry point using one Python installer engine.
- `DONE` Implement exact home precedence and Hermes subprocess environment.
- `DONE` Implement atomic install/update, hashes, one backup, enablement, full byte/state rollback, dry-run/force/JSON.
- `DONE` Implement health/capabilities-only doctor and negative authority proof.
- `DONE` Implement static status plus explicit `status --live` read-only probe without hook history.
- `DONE` Implement prior-state-restoring ownership-safe uninstall.
- `DONE` Verify no CLI/config path accepts bearer token values.

## Phase 4 — bundle and compatibility

- `DONE` Add `memory.observe` to integration-v1 endpoint hints.
- `DONE` migrate stale `mno_memory_context.v1` hints to shipped `mno.agent_context.v2`.
- `DONE` Add plugin/example/thin installers/quickstart to ordinary `hermes_agent` export.
- `DONE` Keep HCR draft-curation exports free of automatic observation artifacts.
- `DONE` Verify adapter without MCP.
- `DONE` Verify MCP configuration alone causes no second automatic observation.
- `DONE` Verify coexistence with Hermes memory provider and document overlap honestly.

## Phase 5 — focused and real-world validation

- `DONE` Run focused plugin, auth, installer, bundle, package, and contract tests.
- `DONE` Run standalone plugin import on Python 3.11 and its MNO-integrated tests on supported Python 3.12 and 3.13.
- `DONE` Run disposable installed Hermes lifecycle proof at pinned revision.
- `DONE` Capture actual provider request with one wrapper plus Hermes `messages.api_content` persistence/replay behavior.
- `DONE` Prove two same-session turns have distinct run IDs and expected provisional reinforcement.
- `DONE` Prove duplicate, absent-turn-ID full no-op, interrupt, failed, empty, background, curator, cron, and internal-origin cases.
- `DONE` Prove pinned end-of-every-turn hook ordering does not erase automatic observation.
- `DONE` Prove black-hole/slow MNO does not block Hermes and no post I/O occurs on hook thread.
- `DONE` Prove no canonical/review/evidence-atom/publish/verify/activate mutation.
- `DONE` Prove install/update/uninstall preserves stores and prior plugin state.
- `DONE` Label only actually run platform/surfaces PASS.

## Phase 6 — regression, package, docs, and visuals

- `DONE` Run full Python suite and existing desktop Node suite.
- `DONE` Build wheel/sdist, isolated install smoke, and distribution verifier.
- `DONE` Run privacy/secret scan, `git diff --check`, and DEV diff-scope audit.
- `DONE` Build an `rg` stale-reference inventory for adapter-affected canonical surfaces.
- `DONE` Update README/public README, LLMS, Hermes/agent integration, API, config, compatibility, quickstart, troubleshooting, distribution, security/privacy, changelog, and release notes where affected.
- `DONE` Update only affected architecture visual sources/generators; regenerate and verify their SVG/PNG exports.
- `DONE` Add exact Seby/Lux install, restart, doctor, HCR recovery, and `mno-report` instructions.

## Phase 7 — DEV to CLEAN, PR, review, and merge

- `DONE` Write post-green DEV checkpoint.
- `DONE` Audit changed files against the locked spec and preserve unrelated DEV state.
- `DONE` Copy only release-ready files from DEV to untouched CLEAN.
- `DONE` Create a focused CLEAN branch from current `origin/main`.
- `DONE` Re-run release gates in CLEAN.
- `DONE` Commit, push, open PR, and write PR-open checkpoints in both checkouts.
- `DONE` Run `pr-review-ci-loop`; resolve all actionable comments, nits, threads, and CI failures.
- `DONE` Confirm required checks/reviews green, merge/close PR, and synchronize CLEAN main.
- `DONE` Run post-merge installed-adapter smoke and verify public main contents.
- `DONE` Write post-merge checkpoints and prepare the final Seby/Lux handoff.
