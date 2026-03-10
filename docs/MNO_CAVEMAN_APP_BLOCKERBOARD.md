# MNO Caveman-Proof App Blockerboard

Spec source: `docs/MNO_CAVEMAN_APP_SPEC.md`  
Execution source: `docs/MNO_CAVEMAN_APP_EXECUTION_CHECKLIST.md`  
Top-level goal: **caveman-proof**  
Status language:

- `Open`: not started
- `In Progress`: active implementation
- `Blocked`: not done because another prerequisite is unresolved
- `Frozen`: do not touch without explicit approval
- `Closed`: implemented, verified, and regression gate passed

## Top-Level Must-Hit Metrics

- `CLI commands on happy path = 0`
- `Raw config edits on happy path = 0`
- `Hand-typed file paths on happy path = 0`
- `Raw IA activation installs allowed = 0`
- `Draft-only MCP installs/exports allowed = 0`
- `Silent MCP overwrite incidents = 0`
- `Activation rollback failures after handshake failure = 0`
- `Published-set/store compatibility violations reaching activation = 0`
- `Caveman-path screens treating Needs attention as success = 0`

## Phase Summary

| Phase | Goal | Exit Gate |
| --- | --- | --- |
| P0 | one coherent GUI flow from IA archive to activation | full end-to-end stage walk, resume, remove/reinstall, raw-IA rejection, mismatch/ownership/rollback guards all green |
| P1 | caveman-proof polish and recovery hardening | usability checklist, low-literacy copy review, no typed paths, draft-only containment all green |
| P2 | desktop packaging parity | packaged flow completes same guarded path with fallback/state preservation |

## P0 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MCAB-001 | Open | Lock stage state machine | `engine/runtime/server.py`, `engine/runtime/ui/*` | Stage order is enforced everywhere as `Import -> Build -> Review -> Publish -> Verify -> Activate -> Operate`; existing-store fast path and draft-only exception path are explicit and consistent | invalid-order attempts blocked in all screens/tests |
| MCAB-002 | Open | Classify imports and existing stores | `engine/runtime/server.py`, `engine/runtime/ui/*` | IA archive, existing MNO store, unsupported JSON, invalid/corrupted file are distinguished before state save; non-MNO sqlite is rejected | raw IA activation blocked; non-MNO sqlite blocked |
| MCAB-003 | Open | Persist review state and publish versioning | `engine/runtime/server.py`, `engine/runtime/ui/*` | Review state binds to store fingerprint + build id; publish emits versioned reviewed artifact with restore history | stale review-state mismatch blocked; publish/store mismatch blocked |
| MCAB-004 | Open | Verify gate and guided remap | `engine/runtime/server.py`, `engine/runtime/ui/*` | `Safe / Needs attention / Blocked` is authoritative everywhere; remap/reset flow exists for missing paths | `Needs attention` never passes as caveman success; remap works after restart |
| MCAB-005 | Open | Unify activation center | `engine/runtime/ui/*`, `engine/runtime/server.py` | Direct/internal and MCP activation share one screen with visible prerequisites, status, and last-checked timestamps | end-to-end activation passes for both modes |
| MCAB-006 | Open | MCP ownership, install/remove safety, rollback | `tools/mcp_connector_common.py`, `engine/runtime/server.py`, `engine/runtime/ui/*` | Unknown config ownership gets `Adopt / Overwrite / Cancel`; failed handshake rolls back; remove only touches owned/adopted entries | no silent overwrite; handshake-fail rollback green |
| MCAB-007 | Open | Frontend shell unification | `engine/runtime/ui/*` | `use $frontend-design skill`; stage rail, entry lanes, publish history, and mixed activation states are user-visible and plain-language | first-time user completes happy path without docs or typed paths |
| MCAB-008 | Open | P0 regression suite | `tests/integration/*`, `tests/unit/*` | Real archive walk-through, resume, remove/reinstall, mismatch, port ownership, unknown ownership, rollback, raw-IA rejection all covered | full P0 gate green |

## P1 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MCAB-101 | Open | Caveman copy hardening | `engine/runtime/ui/*`, docs | `use $frontend-design skill`; critical actions use low-literacy plain language; help copy exists for confusing settings | copy review passes |
| MCAB-102 | Open | Review ergonomics at scale | `engine/runtime/ui/*`, `engine/runtime/server.py` | `use $frontend-design skill`; large review sets use pagination or batching; no unreadable all-row dump path | large-set usability check passes |
| MCAB-103 | Open | Developer-mode containment | `engine/runtime/ui/*`, `engine/runtime/server.py` | Draft-only path is hidden behind developer mode, visibly unsafe, local-only, and audited | draft-only never appears as normal success or MCP-eligible |
| MCAB-104 | Open | Recovery and restore polish | `engine/runtime/ui/*`, `engine/runtime/server.py` | Remap, restore-last-published, and packaged/local fallback all provide guided recovery | recovery checklist passes |
| MCAB-105 | Open | P1 usability gate | tests/docs/usability checklist | no typed paths, no jargon-heavy dead ends, no ambiguous mutation/activation language | scripted usability checklist green |

## P2 Blockers

| ID | Status | Item | Scope | Strict exit criteria | Regression gate |
| --- | --- | --- | --- | --- | --- |
| MCAB-201 | Open | Desktop shell packaging | `app/desktop/*`, `engine/runtime/ui/*` | `use $frontend-design skill`; app launches as one desktop product, not browser + helper sprawl | packaged shell launches and completes flow |
| MCAB-202 | Open | Desktop lifecycle and fallback | `app/desktop/*`, `engine/runtime/server.py` | background runtime lifecycle, config/log access, and fallback to local UI preserve state/data | fallback test green |
| MCAB-203 | Open | Packaged parity gate | packaged app + tests | packaged and non-packaged paths share the same outcomes, validations, and rollback semantics | packaged parity suite green |

## Global Blockers To Watch

| ID | Status | Blocker | Practical meaning |
| --- | --- | --- | --- |
| MCAB-G01 | Open | Existing wizard/API gaps | if the current server endpoints cannot represent publish/verify/activate distinctly, P0 stalls until additive runtime contract work lands |
| MCAB-G02 | Open | Store fingerprint/schema compatibility gaps | if store/reviewed-set compatibility cannot be enforced cleanly, publish/restore/activate remain unsafe |
| MCAB-G03 | Open | MCP ownership ambiguity | if existing third-party config ownership cannot be detected safely, install/remove must not be called done |
| MCAB-G04 | Open | Packaging decision not yet fixed | if P0 ships before Electron is chosen, blockerboard must explicitly keep P2 open instead of pretending it is bundled |

## Closeout Rule

Do not mark this initiative `Closed` until:

- all required P0 items are `Closed`
- all required P1 items are `Closed`
- the P2 decision is explicit
- the happy path is shell-free, edit-free, and typed-path-free
- the app blocks wrong-order use instead of explaining after the fact
