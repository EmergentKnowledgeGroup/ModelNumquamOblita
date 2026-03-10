# MNO Caveman-Proof App Execution Checklist

Derived from: `docs/MNO_CAVEMAN_APP_SPEC.md`  
Top-level goal: **caveman-proof**  
Status: Ready for implementation

## Global Execution Rules

- Keep one implementation slice per PR.
- Frontend tasks must explicitly include `use $frontend-design skill`.
- Do not cross into:
  - `engine/research/*`
  - ANO/JX specs/boards
  - retrieval algorithm redesign unrelated to app-flow guardrails
- Update checkpoints at:
  - phase start
  - post-green tests
  - PR open
  - post-merge
- Never call a phase done unless its regression gate passes.

## Global Done Rules

The app is not done unless all of these are true:

- happy path requires `0` CLI commands
- happy path requires `0` raw config edits
- happy path requires `0` hand-typed file paths
- raw IA `db.json` cannot reach activation
- draft-only artifacts cannot reach MCP install/export
- activation success is observable, not implied
- failed activation mutations can roll back cleanly
- published reviewed sets are restorable and compatibility-checked

## P0: One Coherent GUI Flow

### P0.1 Stage state machine

- [ ] lock the stage order to `Import -> Build Episodes -> Review -> Publish -> Verify -> Activate -> Operate`
- [ ] add explicit entry/exit criteria enforcement in the runtime app state
- [ ] add explicit fast-path rule for `Use existing MNO store`
- [ ] add explicit developer-only exception path for draft activation
- [ ] prevent screen-to-screen disagreement about whether activation is allowed

Done when:

- activation gating is identical in all views
- existing-store bypass only works when a compatible published set exists
- draft-only path is clearly labeled and cannot be mistaken for normal success

### P0.2 Import and store validation

- [ ] accept IA archive import via file picker
- [ ] classify selected files before saving state:
  - valid IA archive
  - valid existing MNO store
  - unsupported JSON / partial archive
  - invalid or corrupted file
- [ ] validate existing stores for schema, marker tables, permissions, corruption, and fingerprint generation
- [ ] reject non-MNO sqlite files even if the file opens successfully

Done when:

- raw IA archive cannot be mistaken for a runtime store
- invalid sqlite or partial JSON cannot enter the happy path

### P0.3 Review, publish, and restore

- [ ] persist draft review state across app restarts
- [ ] bind review state to store fingerprint + build identifier
- [ ] force rebuild or stale-state discard when artifacts changed underneath the review
- [ ] make `Publish` a distinct visible step
- [ ] version published reviewed sets with timestamp, store fingerprint, schema version, episode counts, and build identifier
- [ ] retain published history with restore support and compatibility checks

Done when:

- published reviewed sets are versioned and restorable
- stale review state cannot silently publish against the wrong artifacts

### P0.4 Verify and guided remap

- [ ] enforce one authoritative verify gate:
  - `Safe`
  - `Needs attention`
  - `Blocked`
- [ ] make `Safe` the only caveman-path success state
- [ ] restrict `Needs attention` to local developer override only
- [ ] make `Blocked` always stop activation
- [ ] add guided remap for moved/deleted artifacts
- [ ] add explicit reset/backout path for irrecoverable stale state

Done when:

- no screen can treat `Needs attention` as normal success
- missing/moved files trigger remap instead of crash

### P0.5 Activation center

- [ ] unify direct/internal activation and MCP activation into one screen
- [ ] show prerequisites, status, and last-checked timestamp per target
- [ ] define direct-runtime success:
  - runtime health responds
  - store fingerprint matches
  - reviewed-set fingerprint matches
  - runtime status is `Running`
- [ ] define MCP success:
  - config write/update succeeds
  - selected store + published set are referenced
  - initialize handshake succeeds
  - UI shows `installed / not installed / remove failed / stale config`
- [ ] block MCP install/export for draft-only runs

Done when:

- both activation modes are reversible and independently visible
- export cannot bypass publish/verify rules

### P0.6 MCP ownership and rollback safety

- [ ] detect whether an existing MCP entry is app-owned, adopted, or unknown
- [ ] support `Adopt / Overwrite / Cancel` for unknown ownership
- [ ] remove only app-owned or explicitly adopted entries
- [ ] roll back config mutations when post-write handshake fails
- [ ] define direct runtime port ownership using PID/lockfile plus tokenized health ownership
- [ ] provide stale-lock cleanup flow

Done when:

- no third-party MCP entry can be overwritten silently
- no failed install leaves the UI claiming success

### P0.7 Frontend shell unification

`use $frontend-design skill`

- [ ] redesign the current runtime wizard into a single polished app shell
- [ ] make the stage rail visually dominant
- [ ] add first-time, resume, and existing-store entry lanes
- [ ] remove typed-path dependence from the happy path
- [ ] surface publish history and restore plainly
- [ ] show mixed activation states clearly without jargon

Done when:

- first-time users can see where they are, what is done, and what is next without docs

### P0.8 P0 regression gate

- [ ] real IA archive end-to-end walk-through passes
- [ ] resume works after restart
- [ ] remove/reinstall works
- [ ] raw IA activation attempt is blocked in plain language
- [ ] publish/store mismatch is blocked
- [ ] port-in-use is handled gracefully
- [ ] handshake-fail rollback works
- [ ] unknown MCP ownership is never overwritten silently

P0 phase closes only when all checks above are green.

## P1: Caveman-Proof Polish

### P1.1 UX/copy hardening

`use $frontend-design skill`

- [ ] replace jargon-heavy labels with plain language
- [ ] add short hover/help copy for confusing settings
- [ ] make empty states and error states explicit and recoverable
- [ ] make recovery actions visible instead of buried

### P1.2 Review ergonomics

`use $frontend-design skill`

- [ ] add pagination or batching for large review sets
- [ ] keep list interaction readable and stable
- [ ] make approve/edit/reject operations obvious and low-friction

### P1.3 Developer-mode containment

- [ ] hide draft-only activation behind explicit developer mode
- [ ] keep `viewer` and `strict` as defaults
- [ ] keep mutation tools off by default
- [ ] visibly label all draft-only states as unsafe/non-final
- [ ] persist override audits

### P1.4 Resume and backout polish

- [ ] improve remap UX for moved files
- [ ] improve restore UX for published history
- [ ] make packaged-app fallback restore prior wizard state cleanly
- [ ] ensure `open-config` remains reveal-only in normal flow

### P1.5 P1 regression gate

- [ ] scripted usability checklist passes
- [ ] low-literacy copy review passes on critical actions
- [ ] happy path still uses `0` typed paths
- [ ] draft-only path cannot appear as normal success anywhere

P1 phase closes only when all checks above are green.

## P2: Desktop Packaging

### P2.1 Desktop shell

`use $frontend-design skill`

- [ ] package the front-facing app as a real desktop shell
- [ ] preserve the same P0/P1 state machine and activation rules
- [ ] avoid browser/admin/debug-panel look and feel

### P2.2 Lifecycle and fallback

- [ ] handle background runtime lifecycle cleanly
- [ ] support config/log folder access without requiring edits
- [ ] preserve published history and wizard state across packaged/local fallbacks
- [ ] keep uninstall from deleting retained published sets by default

### P2.3 P2 regression gate

- [ ] packaged app completes the full P0 flow
- [ ] packaged fallback preserves state and data
- [ ] packaged and non-packaged paths share the same guardrails and outcomes

P2 phase closes only when all checks above are green.

## Final Release Checklist

- [ ] all required P0 items closed
- [ ] all required P1 items closed
- [ ] P2 decision explicitly made:
  - ship packaged now
  - or ship improved local UI first and package later
- [ ] final blockerboard updated
- [ ] checkpoints updated
- [ ] operator guide updated
- [ ] no remaining caveman-path ambiguity on import, publish, verify, activate, remove, or restore
