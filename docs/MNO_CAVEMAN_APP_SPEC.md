# MNO Caveman-Proof App Spec

Status: Locked after 4-pass QA  
Owner: MNO product/runtime  
Last updated: 2026-03-09

Derived docs:

- `docs/MNO_CAVEMAN_APP_EXECUTION_CHECKLIST.md`
- `docs/MNO_CAVEMAN_APP_BLOCKERBOARD.md`

## Goal

Top-level goal: **caveman-proof**.

That means the finished MNO app must let the least technical user complete the full MNO path:

1. choose an IA `db.json`
2. import it into MNO
3. build episode cards
4. review and publish a reviewed episode set
5. verify the runtime is healthy
6. activate MNO in one of two ways:
   - internal/direct connector mode
   - MCP mode
7. recover, remove, or re-run without touching scripts, raw config files, or shell commands

The frontend can be a packaged desktop shell. The backend can stay Python. The user contract is GUI-first, not script-first.

## Why This Spec Exists

The repo already contains most of the MNO pipeline and most of a GUI wizard:

- import + build + review + verify + go-live API surfaces already exist
- a local runtime web UI already exposes those stages
- the MCP connector now exists as a separate desktop GUI

What does **not** exist is one coherent front-facing MNO app that ties those together in a simple, user-proof flow.

Current user failure mode:

- the connector accepts a memory path before the user has necessarily run the MNO pipeline
- users can confuse IA transcript truth (`db.json`) with MNO runtime memory state
- pipeline UI and connector UI are separate products in the user’s mind
- the system exposes too much implementation detail and too many intermediate artifact concepts

This spec turns the existing pieces into one product.

## Product Decision

Build a single **front-facing MNO app** that reuses the existing runtime wizard/API surfaces and integrates the MCP connector as a final activation/output stage.

Do **not** build a second disconnected pipeline.

Do **not** make users run raw Python scripts as the primary path.

## Root Cause

The backend already has the right mental model:

- IA `db.json` is transcript truth
- MNO imports transcript truth into atoms
- MNO builds draft episodes
- the operator reviews and publishes the reviewed set
- runtime uses the imported store + reviewed set

The UX problem is that these stages are split across:

- raw CLI scripts
- an existing local runtime web UI
- a separate desktop MCP connector

The system is operationally valid, but the product boundary is still fragmented.

## Non-Negotiable User Contract

The finished app must satisfy all of these:

1. No raw scripts required for normal use.
2. No hand-editing JSON config files for normal use.
3. No confusion between IA transcript files and MNO runtime stores.
4. Every stage must show what the user is doing, what happened, and what the next step is.
5. The app must block invalid stage order:
   - no MCP/direct activation before import/build/review is complete
   - no raw IA `db.json` passed off as a runtime store
   - exception: local developer-only draft activation may bypass publish/verify, but only under the explicit draft-only policy below
6. Safe defaults must remain locked:
   - viewer role
   - strict compat mode
   - mutations off
7. Failures must be recoverable in plain language.
8. Previous published reviewed set must be restorable.
9. Removing/uninstalling connector outputs must be as easy as installing them.
10. Frontend implementation tasks must explicitly say `use $frontend-design skill`.

## SpecSwarm Fold-In Status

This spec is being hardened in four passes:

1. gap / edge-case review
2. implementation touchpoint mapping
3. final QA review
4. author final QA lock

Every blocking issue found in those passes must be folded into the main body of this spec before checklist/blockerboard derivation.

## Scope

### In scope

- the end-to-end front-facing MNO app flow
- reuse/hardening of existing runtime wizard APIs and runtime UI
- integration of MCP install/remove/export into the same app
- internal/direct connector activation path in the same app
- path/file pickers and stateful resume UX
- packaging direction for a desktop shell
- caveman-proof messaging and stage guardrails

### Out of scope

- removed document-research/add-on features
- connector/governance/indexing flows that are outside standalone MNO
- retrieval-quality redesign unrelated to app flow
- large backend architecture split work that belongs in the dedicated disconnect program
- new model/provider work unrelated to app UX

## No-Touch / Boundary Rules

### MNO app allowed surfaces

- `engine/runtime/ui/*`
- `engine/runtime/server.py` wizard/runtime activation endpoints
- `engine/runtime/session.py` only for additive activation/runtime-state reporting if required
- `tools/run_mcp_connector_gui.py`
- `tools/mcp_connector_common.py`
- `tools/run_claude_live_mcp.py`
- packaging/launcher surfaces for the MNO app shell
- docs/guides/operator/app docs

### No-touch surfaces

- removed document-research/add-on surfaces
- dedicated disconnect/spec-governance docs unless explicitly coordinated
- enterprise/scale harnesses outside standalone MNO
- retrieval algorithm changes unless the app spec calls for a minimal validation guard

## Existing Assets To Reuse

These already exist and should be treated as starting points, not throwaway code:

### Existing GUI pipeline base

- runtime wizard shell in `engine/runtime/ui/index.html`
- runtime wizard logic in `engine/runtime/ui/app.js`
- wizard endpoints in `engine/runtime/server.py`
- wizard API contract in `docs/api/API_MATRIX.md`

### Existing MCP output manager

- desktop connector UI in `tools/run_mcp_connector_gui.py`
- install/export helpers in `tools/mcp_connector_common.py`

### Existing pipeline backend

- IA archive import: `tools/import_ia_db.py`
- episode build: `tools/build_episode_cards.py`
- review pack compile: `tools/build_episode_review_pack.py`
- runtime launch: `tools/run_live_runtime.py`

## Architecture Decision

### Chosen direction

Use the existing MNO runtime wizard as the core app workflow and fold the MCP connector into it as the final activation surface.

For desktop packaging, target an **Electron-hosted MNO app shell** around the existing local UI/runtime path.

### Why this direction

- reuses existing wizard and API investments
- keeps Python in the backend where it already works
- gives a true GUI-first user experience
- avoids maintaining two separate frontends that do overlapping work
- makes MCP and direct-connector activation just two output modes of the same pipeline

### Resulting mental model

- **Pipeline tab**: import -> build -> review -> publish -> verify
- **Activation tab**: run direct/internal mode or install/remove/export MCP mode
- **Memory tab**: inspect atoms/cards/episodes after publish
- **Health tab**: runtime health, store path, active reviewed set, logs, rollback

## UX Principle

If the user can make the wrong move, the UI should prevent it instead of explaining afterward.

Examples:

- selecting IA `db.json` in the activation step must fail immediately with a clear message
- selecting “Install MCP” before a reviewed set exists must be blocked
- “Enable mutation tools” must never use ambiguous language
- recovery paths must be visible actions, not hidden docs

## Frontend Direction

All frontend implementation tasks in this spec must explicitly be marked:

`use $frontend-design skill`

Design direction:

- dark-first
- deliberate, strong hierarchy
- large stage framing
- friendly but not childish
- zero dev-tool vibes
- obvious progress and action states
- no browser-admin-dashboard look

The app should feel like a polished memory appliance, not a local debug panel.

## Required User Flows

### Flow A: First-time setup from IA archive

1. open app
2. click `Start New Memory Build`
3. choose IA `db.json` via file picker
4. validate archive
5. import archive into MNO sqlite store
6. build episode cards
7. review cards in-app
8. compile reviewed set
9. run verification
10. choose activation:
   - `Run MNO Here`
   - `Install MCP`
11. app confirms runtime/store/reviewed-set paths and current activation target

### Flow B: Resume existing pipeline

1. open app
2. app offers `Resume last run`
3. app restores wizard state and last known artifact paths
4. user continues at the next incomplete stage

### Flow C: Already have imported store

1. open app
2. choose `Use existing MNO store`
3. select sqlite store
4. app validates store shape and shows whether reviewed episodes already exist
5. user either:
   - jumps to verify/activate if a compatible published set already exists
   - jumps to build/review/publish if a compatible published set does not exist
   - or rebuilds episodes if needed

### Flow D: Remove or switch activation target

1. open app
2. go to activation
3. remove Claude Code or Claude Desktop integration
4. optionally install a different target
5. app confirms exactly what changed

## Stage Model

The app stage order is locked:

1. `Import`
2. `Build Episodes`
3. `Review`
4. `Publish`
5. `Verify`
6. `Activate`
7. `Operate`

The current wizard’s `Go Live` step must be split operationally into:

- `Publish`
- `Verify`
- `Activate`
- `Operate`

because “runtime live” and “connector installed” are not the same thing.

### Stage entry / exit criteria

#### Import

Entry:

- valid IA archive or valid existing MNO store selected

Exit:

- imported MNO store exists
- store shape validation passes
- store fingerprint and schema version are recorded in app state

#### Build Episodes

Entry:

- imported or selected MNO store is valid

Exit:

- draft episode cards and rejects are generated
- build artifacts are recorded in app state

#### Review

Entry:

- draft episode artifacts exist

Exit:

- every reviewable card is explicitly approved, edited, or rejected
- no unresolved review rows remain

#### Publish

Entry:

- review is complete

Exit:

- `episode_cards.reviewed.json` is compiled
- published set receives a timestamped version record
- published set is bound to the originating store fingerprint and schema version
- published set is added to the restore history

#### Verify

Entry:

- published reviewed set exists

Exit:

- verify result is one of:
  - `Safe`
  - `Needs attention`
  - `Blocked`
- only the authoritative verify rule below may decide whether activation is allowed

#### Activate

Entry:

- valid store exists
- for normal activation:
  - compatible published reviewed set exists
  - verify result is `Safe`
- for draft-only developer activation:
  - only local internal/direct mode may be used
  - draft-only warning is acknowledged and persisted
  - verify may be skipped, but the runtime must be labeled `Unreviewed draft`
- activation prerequisites pass for the chosen target

Exit:

- chosen target reports activation success using the mode-specific success contract below

#### Operate

Entry:

- at least one activation target is active or installed

Exit:

- not applicable; this is the steady-state runtime/management view

## Activation Modes

The app must present activation as explicit choices:

### Mode 1: Internal / Direct Connector

Use this when the host product embeds MNO directly and does not need MCP.

Requirements:

- app launches runtime cleanly in background
- app shows runtime status, host, port, active store, active reviewed set
- app provides the exact integration contract details for the embedding host
- app supports stop/restart
- app must show activation as successful only if:
  - runtime health responds within the configured startup window
  - active store fingerprint matches the selected store
  - active reviewed set fingerprint matches the selected published set
  - the runtime status card shows `Running`

### Mode 2: MCP Connector

Use this when the host is Claude Code, Claude Desktop, or any MCP-capable client.

Requirements:

- app reuses the current install/remove/export logic
- app may extend that logic to add handshake verification, ownership detection, and rollback
- app blocks raw IA `db.json`
- app supports:
  - install Claude Code
  - remove Claude Code
  - install Claude Desktop
  - remove Claude Desktop
  - export generic MCP JSON
- app must show activation as successful only if:
  - target config entry was written or updated successfully
  - the written entry points at the selected store and published set
  - a local MCP initialize handshake succeeds
  - the UI can distinguish `installed`, `not installed`, `remove failed`, and `stale config`

### Mixed activation state rules

- direct/internal runtime and MCP installs may coexist
- the app must show them as separate targets, not one blended status
- removing one target must not silently remove or stop another target
- the app must never imply that an MCP install means the internal runtime is currently running

### Draft-only activation policy

- draft-only activation is never part of the normal caveman path
- draft-only activation is allowed only inside an explicit `Developer mode`
- draft-only activation may target internal/direct mode only
- draft-only activation is forbidden for MCP install/export paths
- draft-only activation must be labeled `Unreviewed draft` in every relevant status view
- draft-only activation can never yield a green `ready` or `published` success label
- once a published reviewed set exists, the app must require explicit re-activation to switch from draft-only to published artifacts
- draft-only activation must persist an audit record containing:
  - operator acknowledgement
  - timestamp
  - selected store/build identifiers
  - reason for bypass
- role remains `viewer` and compat mode remains `strict` even in draft-only mode
- mutation tools remain off by default and may only be enabled in developer mode for internal/direct sessions

## Detailed Requirements

### Import

- file picker for IA archive
- validate before import
- show conversation/message counts and obvious issues
- let user pick default output location with sensible defaults
- show generated store path and report paths
- never require command-line flags
- selection must be classified before state is saved as one of:
  - valid IA archive
  - valid existing MNO store
  - unsupported JSON / partial archive
  - invalid or corrupted file
- existing-store validation must check:
  - supported schema version
  - MNO store marker/tables present
  - readable file permissions
  - writable output destination when publish/activation requires it
  - corruption detection for sqlite-backed stores
  - stable store fingerprint generation

### Build Episodes

- build policy selector with plain-language presets
- show promoted/candidate/rejected counts
- show links to draft/reject/readout artifacts
- keep current build profile hidden unless user opens advanced mode

### Review

- in-app review list must be the primary path
- approve/edit/reject must be obvious and one-click
- compile reviewed set from inside app
- show resulting `episode_cards.reviewed.json`
- review UI must support pagination or batching for large card sets
- review state must survive app restart without losing pending edits
- saved review state must be bound to the originating build identifier and store fingerprint
- if the underlying build artifacts changed, the app must force the user to:
  - reopen the matching draft state
  - or discard stale review state and rebuild

### Publish

- publish must be a distinct user-visible step
- publish creates the active reviewed artifact from the completed review state
- publish records:
  - timestamp
  - source store fingerprint
  - schema version
  - episode counts
  - originating build identifier
- app keeps a restorable history of published reviewed sets
- restore must refuse incompatible store/schema combinations with plain-language guidance
- when the user selects an existing store:
  - if a compatible published reviewed set already exists, the app may skip directly to Verify or Activate
  - otherwise the app must require Build Episodes -> Review -> Publish

### Verify

- show a simple summary:
  - Safe
  - Needs attention
  - Blocked
- link directly to the things the user needs to fix
- do not expose raw internals first; show human summary first
- define `Blocked` as activation-preventing
- define `Needs attention` as developer-override-only, not caveman-path success
- show why a result is blocked vs warning-only in plain language
- if artifact paths moved or were deleted, verify must enter guided remap instead of a hard crash
- one authoritative verify gate applies everywhere:
  - `Safe`: normal activation allowed
  - `Needs attention`: normal activation blocked; local internal/direct activation allowed only with explicit developer override and stored audit note
  - `Blocked`: all activation blocked
- the developer override path must record:
  - approver identity or local operator marker
  - timestamp
  - reason
  - affected target
- guided remap must provide:
  - missing path summary
  - file/folder picker to remap
  - cancel/backout path
  - option to reset stale wizard state if remap fails

### Activate

- direct/internal mode and MCP mode side by side
- both modes show prerequisites and current status
- install/remove/export actions must be reversible
- current active target must be visible
- app must show per-target success criteria and last-checked timestamp
- if the selected target client is missing, locked, or already configured by another tool, activation must fail with target-specific recovery guidance
- exporting generic MCP JSON must obey the same validation rules as install; it is not a bypass around publish/verify rules
- MCP config ownership rules:
  - if an entry already exists and was created by this app, update in place
  - if an entry exists but ownership is unknown, show `Adopt / Overwrite / Cancel`
  - remove may only delete entries owned by this app or explicitly adopted by the user
- if config mutation succeeds but handshake fails, the app must revert the change or offer immediate rollback before showing final failure
- direct runtime port ownership must be determined by app-owned PID/lockfile plus startup token or health token, not by port presence alone
- stale lock or stale ownership markers must offer guided cleanup before retry

### Operate

- show active runtime/store/reviewed-set
- show health
- expose open-folder/open-log/open-config actions
- show restore-last-published and stop runtime actions
- `open-config` is read-only/reveal-only for normal use; it must never imply hand-editing is part of the supported flow
- show if the current published set is live, draft-only, or stale

## Validation Guards

The app must explicitly reject:

1. raw IA transcript JSON in activation mode
2. MCP install against an unreviewed/draft-only run
3. activation without a valid imported MNO store
4. activation with missing reviewed set unless the user explicitly chooses a draft-only dev mode
5. contradictory UI copy like “Enable X” combined with “off by default”
6. published reviewed set whose store fingerprint or schema version does not match the selected store
7. resume state whose artifact paths no longer exist without first running guided remap
8. activation when direct runtime port is already occupied and not owned by the current app session
9. removal claims that do not verify the target entry is actually gone afterward
10. existing store selection when the file is not a valid MNO store even if it is a valid sqlite database

### Verify blocker vs warning rules

`Blocked` examples:

- no valid imported MNO store
- no published reviewed set for normal activation
- published set/store fingerprint mismatch
- schema incompatibility
- target client missing for the chosen action
- direct runtime health check failed
- MCP initialize handshake failed

`Needs attention` examples:

- optional metadata missing
- large archive or review set likely to degrade UI performance
- stale inactive connector entry exists for a different target
- restore history is available but not yet trimmed

Authoritative rule:

- `Safe` is the only caveman-path success state
- `Needs attention` blocks the caveman path and may proceed only through the explicit developer-override path for local internal/direct mode
- `Blocked` always prevents activation

## Frontend Tasks

All frontend tasks below must include:

`use $frontend-design skill`

### Frontend Task Group A: Pipeline shell unification

`use $frontend-design skill`

- redesign the current runtime wizard into a polished app shell
- make stage rail visually dominant and idiot-proof
- add first-time, resume, and existing-store entry lanes
- add file-pickers and no-typing defaults where missing
- make `Publish` a distinct stage with visible before/after state
- show restore history and current published set without jargon

### Frontend Task Group B: Activation center

`use $frontend-design skill`

- fold MCP connector UI into the runtime app
- separate direct/internal mode from MCP mode visually and conceptually
- show install/remove/export actions and live status in one activation view
- surface mixed activation states clearly
- show target-specific success/failure criteria in plain language

### Frontend Task Group C: Packaging shell

`use $frontend-design skill`

- package the front-facing app as an Electron shell over the local runtime UI/backend
- preserve the same flows in packaged and dev mode
- avoid browser/admin/local-debug aesthetics

## Backend / Plumbing Tasks

### Backend Task Group A: Wizard hardening

- keep using existing wizard endpoints
- fill any missing stage contract for activation/remove actions
- ensure wizard state tracks activation target and active reviewed artifact
- persist store fingerprint, schema version, published-set identity, and restore history
- support guided remap when saved paths are missing

### Backend Task Group B: Activation services

- expose direct/internal runtime activation state cleanly
- expose MCP install/remove status cleanly
- centralize active store/reviewed-set resolution
- define and expose mode-specific activation success checks
- keep install/remove idempotent and reversible
- verify target presence/lock conditions before mutating client config
- extend the current MCP install/remove/export helpers as needed for handshake verification and rollback; reuse does not mean freeze the current helper contract
- persist config ownership markers and adoption state for safe remove/update

### Backend Task Group C: Validation

- prevent raw IA archive misuse at the app boundary
- require reviewed/published artifact before normal activation
- preserve restore/backout paths
- enforce store/reviewed-set compatibility checks
- differentiate verify blockers from warnings in API responses
- validate existing-store selections before wizard state is committed
- validate unknown JSON and partial archives with explicit error classes

### Backend Task Group D: Tests and regression gates

- add end-to-end GUI flow coverage for:
  - first-time IA import to publish to activation
  - resume with moved or missing paths
  - existing-store path
  - remove and reinstall target actions
- add guard tests for:
  - raw IA rejection at activation
  - draft-only activation blocked for MCP
  - publish/store fingerprint mismatch
  - runtime port-in-use detection
  - target client missing/locked behavior
  - unknown MCP config ownership adopt/overwrite/cancel flow
  - config-write succeeds but handshake fails, followed by rollback
  - existing sqlite that is not an MNO store
  - stale review-state mismatch after build artifact changes

## File / Surface Map

### Existing surfaces to extend

- `engine/runtime/ui/index.html`
- `engine/runtime/ui/app.js`
- `engine/runtime/server.py`
- `engine/runtime/session.py` for additive runtime-state reporting only if required
- `tools/run_mcp_connector_gui.py`
- `tools/mcp_connector_common.py`
- `tools/run_claude_live_mcp.py`

### Likely new surfaces

- packaged app launcher/bootstrap docs
- optional `app/desktop/*` Electron wrapper surfaces
- shared activation-status helpers
- app-specific guide docs
- integration tests such as:
  - `tests/integration/test_mno_gui_flow.py`
  - `tests/integration/test_mno_activation_ui.py`
  - `tests/integration/test_mno_resume_flow.py`
  - `tests/integration/test_packaged_mno_app.py`

## Rollout Plan

### P0: One coherent GUI flow

Goal:

- unify import/build/review/verify/activate in one user-facing app flow

Required scope:

- reuse existing runtime wizard
- integrate MCP connector actions into activation step
- add raw-IA rejection at activation boundary
- expose direct/internal activation alongside MCP
- stage guardrails prevent wrong-order usage
- add distinct Publish stage and restore history
- define and enforce activation success contracts
- define existing-store fast path and draft-only exception path explicitly
- define MCP config ownership/adoption and rollback behavior

Done when:

- a new user can go from IA `db.json` to active reviewed runtime without scripts
- MCP is installed/removed from inside the app, not a separate side tool
- direct/internal activation is available from the same app
- activation status is testable and unambiguous
- publish/restore history is visible and functional

Regression gate:

- full stage walk-through passes on a real IA archive
- restart/resume works
- remove/reinstall connector works
- raw IA activation attempt is blocked with plain-language error
- publish/store mismatch is blocked
- direct runtime port-in-use is handled gracefully
- handshake failure after config write rolls back cleanly
- unknown existing MCP config entry is never overwritten silently

### P1: Caveman-proof polish

Goal:

- remove jargon, reduce error recovery friction, improve visibility

Required scope:

- better copy
- better empty/error states
- better review ergonomics
- first-use onboarding hints
- clearer activation status
- verify warning vs blocker language
- draft-only developer mode labeling and containment

Done when:

- a low-technical user can recover from common mistakes without reading docs

Regression gate:

- scripted usability checklist passes
- no hand-typed path required for the happy path
- low-literacy copy review passes on all critical actions

### P2: Desktop packaging

Goal:

- ship the front-facing MNO app as a real desktop product shell

Required scope:

- Electron wrapper
- clean launch behavior
- config/log folder access
- background runtime lifecycle handling
- preserve the same state machine and activation rules as P0/P1

Done when:

- user opens one app, not a browser tab plus separate helper

Regression gate:

- packaged app can complete the same P0 flow end-to-end
- packaged rollback to the local web UI path preserves data and state

## Metrics / Acceptance

The app is not done just because it looks nicer.

It is done only if:

- happy-path completion requires zero CLI
- happy-path completion requires zero raw file editing
- raw IA archive misuse is blocked at the UI layer
- reviewed set compile happens in-app
- MCP install/remove happens in-app
- direct/internal activation happens in-app
- runtime health and active artifacts are visible
- restore/backout is visible
- frontend tasks explicitly carry `use $frontend-design skill`
- stage transitions are locked and testable
- activation success is observable, not implied
- published-set retention and restore are bounded and compatible

### Success metrics

- happy-path completion by a first-time tester without shell usage
- zero hand-typed file paths in the happy path
- zero ability to reach MCP install from raw IA `db.json`
- restore of the last published set succeeds in one guided flow
- remove actions fully remove the chosen target without touching other targets
- review UI remains usable on large sets through pagination or batching
- packaged and non-packaged app paths share the same outcome and guardrails

## Rollback / Backout

Must support all of these:

1. restore previous published reviewed set
2. remove Claude Code MCP entry
3. remove Claude Desktop MCP entry
4. stop background runtime
5. reopen prior wizard run

### Retention / restore policy

- keep at least the latest 5 published reviewed sets by default
- keep at most the latest 20 unless the user explicitly exports/archive-pins older ones
- each retained set stores:
  - timestamp
  - source store fingerprint
  - schema version
  - episode counts
  - original artifact path
- restore must pick only sets compatible with the selected store unless the user first changes stores
- uninstall or packaged-app rollback must not delete retained published reviewed sets by default
- pruning must happen only after a successful new publish
- pruning must show the user what was pruned and what was retained
- pinned/exported sets must never be pruned automatically

## Rollout / Migration Notes

- existing users of the separate MCP connector must be migrated into the unified activation center without losing install/remove capability
- existing runtime web UI users must retain access to their last wizard state and published artifacts
- the packaged desktop shell must be able to fall back to the local web UI without data loss
- `open-config` and similar support actions must remain diagnostics/reveal actions, not required editing steps
- migration must detect existing MCP installs and choose one of:
  - adopt current MNO-owned entry
  - leave unrelated third-party entry untouched
  - require explicit overwrite confirmation
- packaged-app fallback must restore the last wizard state instead of forcing re-import

## SpecSwarm Pass Fold-In Log

### Pass 1: Gap / edge-case review folded in

- added explicit `Publish` stage and stage entry/exit criteria
- defined draft-only activation policy and containment
- defined published-set retention and restore rules
- defined activation success criteria for direct/internal and MCP modes
- clarified `open-config` as read-only/reveal-only
- added verify blocker vs warning rules
- added compatibility/remap/port-in-use/client-missing edge cases

### Pass 2: Implementation mapping folded in

- tied the spec to `engine/runtime/ui/*`, `engine/runtime/server.py`, `engine/runtime/session.py`, `tools/run_mcp_connector_gui.py`, `tools/mcp_connector_common.py`, and packaging surfaces
- added explicit regression tests and integration test lanes
- reinforced standalone-boundary limits and retrieval algorithm redesign constraints

### Pass 3: Final QA review folded in

- clarified the draft-only exception to normal activation rules
- made verify gating authoritative and consistent
- defined existing-store bypass rules
- added MCP config ownership, adoption, and rollback rules
- defined remap/reset behavior for moved paths and stale review state
- defined port ownership in terms of app-owned process/lock state

### Pass 4: Author final QA lock

- fixed the remaining pipeline-order contradiction by locking `Publish` before `Verify`
- removed the stale `approved Needs attention` wording and deferred all activation decisions to the authoritative verify gate
- clarified Flow C so existing-store resume only skips forward when a compatible published set already exists
- clarified that MCP helper reuse may be extended for handshake/rollback requirements

## Remaining Non-Blocking Decisions

1. Should packaged desktop shell be Electron immediately in P0, or should P0 ship as the improved local runtime UI first and package in P2?
2. What exact direct/internal connector contract does the Rust host need from the activation screen?
3. Which runtime health and logs are most useful to show by default for caveman-proof support?
4. Should the current standalone MCP connector survive as a dev/operator tool, or be fully absorbed into the app?
