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
| MAD-001 | Open | Ownership inventory | mixed startup/runtime/UI/tests/docs/package surfaces | every mixed surface is tagged MNO, ANO, shared, or shim-owner target | no ownership ambiguity remains |
| MAD-002 | Open | Separation definitions lock | spec + docs contract | `ANO absent`, `public MNO contract`, shared-lane rules, shim policy, duplicate-first rules are fixed | no definition ambiguity remains |
| MAD-003 | Open | Compatibility matrix anchor | `docs/MNO_ANO_COMPATIBILITY_MATRIX.md` | canonical matrix location, owner, support window, deprecation rules, stop-ship rules are defined | both future lanes can gate against one matrix |

## P1 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-101 | Open | Top-level export detox | `engine/__init__.py`, package exports | MNO top-level package no longer exports ANO research symbols; no transitive ANO import through public MNO imports | dependency trace green |
| MAD-102 | Open | Runtime server detox | `engine/runtime/server.py`, `engine/runtime/ano_incremental.py` | MNO startup path no longer imports ANO runtime manager; optional boundary is explicit-enable and default-off only | MNO startup succeeds with ANO imports failing |
| MAD-103 | Open | Runtime UI detox | `engine/runtime/ui/index.html`, `engine/runtime/ui/app.js` | MNO UI exposes no ANO-only controls; ANO UI surfaces moved out | MNO UI smoke has zero ANO controls |
| MAD-104 | Open | Test-lane detox | `tests/*` | MNO standalone CI imports no ANO directly/transitively; compatibility tests moved out of standalone gate | MNO standalone CI green with ANO absent |
| MAD-105 | Open | Packaging/docs detox | `pyproject.toml`, package scripts, MNO docs | MNO packaging excludes ANO-owned modules; MNO docs do not route normal users through ANO | MNO standalone package/install green |

## P2 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-201 | Open | Explicit product roots | package/folder layout | clear MNO-owned and ANO-owned roots exist | ownership by path is obvious |
| MAD-202 | Open | Mixed-surface split | runtime server/UI/tests/docs/package paths | mixed files reduced to zero or thin shims only | no mixed mandatory paths remain |
| MAD-203 | Open | Duplicate parity / divergence | duplicated surfaces | every duplicated surface has parity tests or declared intentional divergence | no ungoverned duplicate drift |
| MAD-204 | Open | Shim discipline | shim files | every shim has owner, reason, trigger, expiry; no indefinite bridge | shim inventory green |
| MAD-205 | Open | Packaging/doc re-home | scripts/docs/fixtures | no removed mixed paths remain referenced | packaging/docs path audit green |

## P3 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-301 | Open | Standalone MNO lane | MNO repo/package | MNO can build/test/release independently | MNO standalone lane green |
| MAD-302 | Open | Standalone ANO lane | ANO repo/package | ANO can build/test/release independently against declared contracts | ANO standalone lane green |
| MAD-303 | Open | Public-contract enforcement | shared/public interfaces | ANO consumes only declared MNO/shared contracts | no private MNO internal imports from ANO |
| MAD-304 | Open | Operator continuity | migration docs/data paths | existing users migrate without forced re-import due solely to repo split | data path continuity green |
| MAD-305 | Open | Repo authority fallback | release/cutover governance | one authoritative lane is defined for partial-failure cases | failed cutover does not create split-brain release state |

## P4 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MAD-401 | Open | Boundary audit | imports/dependencies/startup paths | hidden/static/transitive recoupling is detected and blocked | boundary audit green |
| MAD-402 | Open | Compatibility gate enforcement | release/test lanes | both lanes gate releases on canonical matrix | compatibility lane green |
| MAD-403 | Open | Shim retirement | shim inventory | expired shims are removed or explicitly renewed before release | no expired shims remain |
| MAD-404 | Open | Shared-lane discipline | shared package/surfaces | shared lane contains only contracts/types/constants/narrow interfaces | shared-lane bloat audit green |

## Global Blockers To Watch

| ID | Status | Blocker | Practical meaning |
| --- | --- | --- | --- |
| MAD-G01 | Open | Runtime server still centralizes both products | until startup and endpoints are surgically split, MNO cannot honestly claim ANO-free runtime |
| MAD-G02 | Open | MNO package still bundles ANO code | tests can pass while distribution remains fake-separated |
| MAD-G03 | Open | Compatibility matrix not yet canonicalized | both future lanes can drift and still claim support |
| MAD-G04 | Open | Mixed tests still sitting in MNO CI | ANO dependency can sneak back into MNO through fixtures/test helpers |
| MAD-G05 | Open | Shared-lane temptation | if shared package grows beyond contracts/types/interfaces, the split collapses back into a blob |

## Closeout Rule

Do not mark this initiative `Closed` until:

- all required P0 items are `Closed`
- all required P1 items are `Closed`
- all required P2 items are `Closed`
- all required P3 items are `Closed`
- all required P4 items are `Closed`
- the canonical compatibility matrix is active
- MNO is truly standalone, not just ANO-hidden
