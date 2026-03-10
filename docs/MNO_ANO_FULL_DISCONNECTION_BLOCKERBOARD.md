# MNO / ANO Full Disconnection Blockerboard

Spec source: `docs/MNO_ANO_FULL_DISCONNECTION_SPEC.md`  
Execution source: `docs/MNO_ANO_FULL_DISCONNECTION_EXECUTION_CHECKLIST.md`  
Top-level goal: **full disconnection**  
Status language:

- `Open`: not started
- `In Progress`: active implementation
- `Blocked`: prerequisite unresolved
- `Frozen`: do not touch without explicit approval
- `Closed`: implemented, verified, and gated

## Must-Hit Metrics

- `MNO startup imports ANO-only modules = 0`
- `MNO UI surfaces exposing ANO-only controls = 0`
- `Top-level MNO exports of ANO symbols = 0`
- `Hidden plugin/dynamic ANO autoloads on MNO startup = 0`
- `Mixed mandatory runtime files remaining = 0`
- `MNO standalone install/test/runtime = PASS`
- `ANO standalone install/test/runtime = PASS`
- `Undeclared shared surfaces = 0`
- `Expired compatibility shims = 0`
- `Supported version-pair matrix coverage gaps = 0`

## Phase Summary

| Phase | Goal | Exit gate |
| --- | --- | --- |
| P0 | boundary lock and inventory | no unresolved ownership/definition ambiguity |
| P1 | MNO startup/runtime detox in current tree | MNO passes with ANO absent and package excludes ANO |
| P2 | folder/package extraction | no mixed mandatory paths remain; parity/shim rules enforced |
| P3 | repo/package split | both lanes build/test/release independently with valid data continuity |
| P4 | post-split hardening | audits and compatibility gates prevent re-coupling |

## P0 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-001 | Closed | Ownership inventory | mixed startup/runtime/UI/tests/docs/package surfaces | every mixed surface is tagged MNO, ANO, shared, or shim-owner target | no ownership ambiguity remains |
| MAD-002 | Closed | Separation definitions lock | spec + docs contract | `ANO absent`, `public MNO contract`, shared-lane rules, shim policy, duplicate-first rules are fixed | no definition ambiguity remains |
| MAD-003 | Closed | Compatibility matrix anchor | `docs/MNO_ANO_COMPATIBILITY_MATRIX.md` | canonical matrix location, owner, support window, deprecation rules, stop-ship rules are defined | both future lanes can gate against one matrix |

## P1 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-101 | Closed | Top-level export detox | `engine/__init__.py`, package exports | MNO top-level package no longer exports ANO research symbols; no transitive ANO import through public MNO imports | dependency trace green |
| MAD-102 | Closed | Runtime server detox | `engine/runtime/server.py`, `engine/runtime/ano_incremental.py` | MNO startup path no longer imports ANO runtime manager; optional boundary is explicit-enable and default-off only | MNO startup succeeds with ANO imports failing |
| MAD-103 | Closed | Runtime UI detox | `engine/runtime/ui/index.html`, `engine/runtime/ui/app.js` | MNO UI exposes no ANO-only controls; ANO UI surfaces moved out | MNO UI smoke has zero ANO controls |
| MAD-104 | Closed | Test-lane detox | `tests/*` | MNO standalone CI imports no ANO directly/transitively; compatibility tests moved out of standalone gate | MNO standalone CI green with ANO absent |
| MAD-105 | Closed | Packaging/docs detox | `pyproject.toml`, package scripts, MNO docs | MNO packaging excludes ANO-owned modules; MNO docs do not route normal users through ANO | MNO standalone package/install green |

## P2 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-201 | Blocked | Explicit product roots | package/folder layout | clear MNO-owned and ANO-owned roots exist | ownership by path is obvious |
| MAD-202 | Closed | Mixed-surface split | runtime server/UI/tests/docs/package paths | mixed files reduced to zero or thin shims only | no mixed mandatory paths remain |
| MAD-203 | Closed | Duplicate parity / divergence | duplicated surfaces | every duplicated surface has parity tests or declared intentional divergence | no ungoverned duplicate drift |
| MAD-204 | Closed | Shim discipline | shim files | every shim has owner, reason, trigger, expiry; no indefinite bridge | shim inventory green |
| MAD-205 | Closed | Packaging/doc re-home | scripts/docs/fixtures | no removed mixed paths remain referenced | packaging/docs path audit green |

## P3 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-301 | Closed | Standalone MNO lane | MNO repo/package | MNO can build/test/release independently | MNO standalone lane green |
| MAD-302 | Blocked | Standalone ANO lane | ANO repo/package | ANO can build/test/release independently against declared contracts | ANO standalone lane green |
| MAD-303 | Blocked | Public-contract enforcement | shared/public interfaces | ANO consumes only declared MNO/shared contracts | no private MNO internal imports from ANO |
| MAD-304 | Closed | Operator continuity | migration docs/data paths | existing users migrate without forced re-import due solely to repo split | data path continuity green |
| MAD-305 | Closed | Repo authority fallback | release/cutover governance | one authoritative lane is defined for partial-failure cases | failed cutover does not create split-brain release state |

## P4 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-401 | Closed | Boundary audit | imports/dependencies/startup paths | hidden/static/transitive recoupling is detected and blocked | boundary audit green |
| MAD-402 | Blocked | Compatibility gate enforcement | release/test lanes | both lanes gate releases on canonical matrix | compatibility lane green |
| MAD-403 | Closed | Shim retirement | shim inventory | expired shims are removed or explicitly renewed before release | no expired shims remain |
| MAD-404 | Closed | Shared-lane discipline | shared package/surfaces | shared lane contains only contracts/types/constants/narrow interfaces | shared-lane bloat audit green |

## Global Blockers To Watch

| ID | Status | Blocker | Practical meaning |
| --- | --- | --- | --- |
| MAD-G01 | Closed | Runtime server still centralizes both products | MNO runtime server no longer imports or serves ANO-owned mandatory surfaces |
| MAD-G02 | Closed | MNO package still bundles ANO code | standalone package path excludes removed ANO modules and passes standalone tests |
| MAD-G03 | Closed | Compatibility matrix not yet canonicalized | canonical matrix is now active in `docs/MNO_ANO_COMPATIBILITY_MATRIX.md` |
| MAD-G04 | Closed | Mixed tests still sitting in MNO CI | standalone CI now carries boundary audit coverage and no active ANO test dependencies |
| MAD-G05 | Closed | Shared-lane temptation | no shared lane exists in standalone MNO today; future shared surfaces remain spec-gated only |

## Current State

- Standalone MNO is complete inside `ModelNumquamOblita`.
- Remaining required disconnect work is external to the standalone MNO repo and depends on ANO-side extraction plus cross-lane contract enforcement:
  - `MAD-201`
  - `MAD-302`
  - `MAD-303`
  - `MAD-402`

Those items cannot be truthfully closed from the standalone MNO repo alone.

## Closeout Rule

Do not mark this initiative `Closed` until:

- all required P0 items are `Closed`
- all required P1 items are `Closed`
- all required P2 items are `Closed`
- all required P3 items are `Closed`
- all required P4 items are `Closed`
- the canonical compatibility matrix is active
- MNO is truly standalone, not just ANO-hidden
