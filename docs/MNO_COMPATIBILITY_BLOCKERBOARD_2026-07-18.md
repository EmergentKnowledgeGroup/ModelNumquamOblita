# MNO Compatibility and Adoption Blocker Board

**Board date:** 2026-07-18
**Audit baseline:** `v0.2.0` / `fbff9f2`
**Release candidate:** `v0.2.1` staged from the DEV SSoT into the clean release checkout
**Overall status:** **LOCAL CANDIDATE GREEN. GitHub artifact-matrix CI remains the final open release-process gate.**

## Status rules

- `OPEN`: source-proven or reproduced and not yet rectified.
- `IMPLEMENTED`: a candidate fix exists, but the full unblock proof has not passed.
- `VERIFIED`: fix and regression matrix passed against the exact release candidate.
- `ACCEPTED_LIMITATION`: deliberately unsupported and removed from product claims/docs.
- `RELEASED` refers to behavior in `v0.2.0`; dirty-tree work is never release evidence.

Severity means:

- `P0`: privacy, secret persistence, destructive loss, or truth-boundary risk; blocks the affected release surface immediately.
- `P1`: common installation, integration, durability, lifecycle, or advertised-capability failure; blocks broad adoption.
- `P2`: important hardening or ambiguity; must be fixed or explicitly bounded before claiming the affected environment.

## Consolidated board

| ID | Sev | State | Root-cause finding and scope | Evidence / reproduction | Objective unblock proof | Depends on | Status |
|---|---:|---|---|---|---|---|---|
| `MNO-COMPAT-001` | P0 | RELEASED | Raw import can persist secret-bearing input before any content-safety boundary. This is a pre-persistence contract failure, not an import-quality score issue. | Reproduced with a unique secret in a raw import; the import reported success and the secret bytes were present in the resulting SQLite database. Source: `engine/ingest/orchestrator.py`, `engine/memory/sqlite_store.py`. | Canary suite proves secrets are removed or quarantined before every database/report/trace write; failed sanitation is fail-closed and leaves no durable residue. | — | VERIFIED |
| `MNO-COMPAT-002` | P0 | DEV source/proof; future desktop release | Electron packaging recursively includes the live repository `runtime`, creating a direct private-memory packaging path. | `app/desktop/package.json` includes `../../runtime`. Existing DEV unpacked resources contained about 2,709 runtime files / 417 MB, including multiple `atoms.sqlite3` paths. No current `v0.2.0` desktop installer asset was found, so no claim is made that the published wheel/sdist leaked these files. | Allowlist manifest builds an empty runtime skeleton; build fails on stores, `-wal`, `-shm`, WSS, checkpoints, reports, traces, caches, or secret canaries; inspect every desktop artifact before publication. | — | VERIFIED |
| `MNO-COMPAT-003` | P1 | RELEASED | Interpreter/bootstrap discovery equates command names and `ensurepip` with MNO capability. PowerShell selects bare `py`; explicit interpreter argv and `/usr/bin/python3` are not consistently considered; uv environments without `ensurepip` are rejected. | Lux sandbox reproduction plus source checks in `setup_local.ps1`, `launch_setup_workspace.ps1`, `tools/preflight.py`, `tools/setup_local.py`, and `app/desktop/run-python.cjs`. | One argv-based resolver passes shadowed PATH, `py -3.12`, python-only, uv/no-ensurepip, explicit override, `/usr/bin/python3`, spaces/Unicode, and supported-version cases across all launch surfaces. | — | VERIFIED |
| `MNO-COMPAT-004` | P1 | RELEASED | Native/WSL executable resolution is capability-blind: WSL can receive Windows `npm.cmd`; native Windows Claude can generate a WSL entry when WSL is absent; Windows packaging can require `bash`. | Simulated WSL npm resolution returned `/mnt/c/Program Files/nodejs/npm.cmd`. Source: `tools/run_mcp_connector_gui.py`, `tools/mcp_connector_common.py`, `app/desktop/package.json`. | Native Windows without WSL emits a supported native/HTTP plan or a precise block; WSL uses Linux executables; platform packaging has no foreign-shell dependency unless declared and preflighted. | 003 | VERIFIED |
| `MNO-COMPAT-005` | P1 | RELEASED | Published wheel/sdist do not implement the documented runnable-product contract. They omit tools, UI, docs, wrappers, and console entry points; installed version/state discovery assumes a source tree. | Public wheel/sdist downloaded and inspected. Isolated wheel target had no UI/index, reported project version `0.0.0`, and default runtime root resolved under the installed package target. `pyproject.toml` discovers only `engine*`. | Declare split SDK/app artifacts or ship a complete app; install exact wheel and sdist without source tree; launch every claimed surface; UI loads; version is `0.2.x`; mutable state is outside read-only installation resources. | — | VERIFIED |
| `MNO-COMPAT-006` | P1 | RELEASED | Generated integration bundles are not relocatable: launchers embed the originating checkout/interpreter and rerun source setup. | Source: `tools/integration_bundle_common.py`; packaging lane inspection of generated Windows/Linux launchers. | Move a generated bundle to a clean host/path with no originating checkout; setup/launch succeeds from declared dependencies or fails before mutation with an exact missing-capability result. | 003, 005 | VERIFIED |
| `MNO-COMPAT-007` | P1 | RELEASED | Code/assets and mutable state are insufficiently separated; setup assumes online, writable source checkouts and packaged first-run policy may target resources. | Source: `tools/setup_local.py`, `tools/run_setup_workspace.py`, `tools/preflight.py`, `tools/run_live_runtime.py`, `app/desktop/main.js`. | Read-only source/package + writable external state passes setup, first run, policy update, restart, logs, locks, and fresh-store flow; offline/cache/proxy behavior is deterministic and documented. | 005 | VERIFIED |
| `MNO-COMPAT-008` | P1 | RELEASED | Connector install/configuration is non-transactional and may target the wrong Windows user. Claude Code removal occurs before replacement proof; JSON writes are not consistently atomic; executable presence substitutes for version/capability. | Source: `tools/mcp_connector_common.py`. Multi-profile simulation selected the newest other-user config. | Current-user-only default discovery; atomic write+backup; stage/verify/swap or rollback; old/missing/current client matrix; failed replacement preserves the prior working connector. | 003, 004 | VERIFIED |
| `MNO-COMPAT-009` | P1 | RELEASED | `writeback.propose` idempotency is process-local, so replay after restart or concurrent processes can duplicate durable proposals; post-commit audit failure is ambiguous. | Source: in-memory replay table in `engine/runtime/server.py`; restart test covers resolution rather than proposal replay. | Persist idempotency identity with proposal; same key+payload across restart/concurrent processes returns the original identity exactly once; mismatched payload conflicts; injected post-commit failure is safely recoverable. | — | VERIFIED |
| `MNO-COMPAT-010` | P1 | RELEASED | Advertised tools/schema can diverge from real authorization, backend, policy, and transport availability. MCP-facing credentials and runtime-integration credentials are separate without a complete propagation/degradation contract. | Source: `engine/mcp/server.py`, `engine/runtime/server.py`, `tools/run_claude_live_mcp.py`, desktop sidecar launch. Native integration audit also found docs/schema drift. | Golden parity fixtures make HTTP/MCP/stdio/desktop return equivalent availability and error semantics; capabilities distinguish exposed, authorized, degraded, and unavailable operations. | 008 | VERIFIED |
| `MNO-COMPAT-011` | P1 | RELEASED | Maintenance lacks a complete durable fairness contract: bounded work, persistent cursor, concurrency exclusion, retry idempotency, and truthful dry-run are not jointly proven. | Source/design audit across provisional maintenance and job surfaces; no hostile continuous-traffic/restart gate found. | Continuous traffic plus restart test proves every eligible item progresses within a bound, cursor resumes correctly, duplicate workers cannot double-apply, and dry-run makes no mutation. | 009, 010 | VERIFIED |
| `MNO-COMPAT-012` | P1 | RELEASED | Import snapshots an active WAL-backed SQLite store by copying only the main file; whole-runtime backup, ACL, and concurrent-operation semantics are incomplete. | `engine/ingest/orchestrator.py` uses `shutil.copy2`; `engine/memory/sqlite_store.py` enables WAL and already exposes SQLite backup machinery. | Active-writer import preserves all committed state via SQLite backup/coordination or refuses safely; backup/restore covers stores and required metadata with permission/error tests. | 001 | VERIFIED |
| `MNO-COMPAT-013` | P1 | RELEASE PROCESS | CI is source/editable-install green, not artifact/hostile-environment green. Windows/macOS desktop packaging, isolated artifacts, ARM64 claims, offline, permissions, WAL, and lifecycle are not proven. | `.github/workflows/ci.yml` tests Python 3.12 on Ubuntu/Windows and desktop tests on Ubuntu; exact public artifact was not the test subject. | The exact release candidate passes the advertised Python/OS/architecture/install/network/filesystem/client matrix; artifact digests tested equal artifact digests published. | 001–012, 014–017 | IMPLEMENTED — awaiting GitHub matrix proof |
| `MNO-COMPAT-014` | P1 | RELEASED | Headless signal handlers record SIGTERM/SIGINT/CTRL_BREAK but do not request loop termination; fixed port assumptions lack structured collision handling. | Source-confirmed in `tools/run_live_runtime.py`: loop exits only for desktop shutdown, timeout, or exception. Default ports include 7340/8765. | Process tests prove bounded exit, lock/SQLite cleanup, no orphan, and clear shutdown reason for each supported signal/parent-death case; occupied ports produce a structured result or published alternate binding. | — | VERIFIED |
| `MNO-COMPAT-015` | P1 | RELEASED | Legacy `.runtime/imports` is preferred over documented canonical `runtime/imports` when both exist, risking attachment to stale memory. | Safe dual-store simulation plus source in `tools/run_live_runtime.py`, `tools/mcp_connector_common.py`, and `tools/run_claude_live_mcp.py`; `docs/QUICKSTART.md` states canonical `runtime`. | One resolver prefers canonical `runtime`; legacy is fallback-only; dual presence warns and never silently selects legacy; every launcher/preflight shares tests. | — | VERIFIED |
| `MNO-COMPAT-016` | P1 | RELEASED | Secret-safe diagnostics are incomplete. Optional MCP stdio tracing logs raw `initialize` params, including `auth_token`; diagnostics may contain memory-bearing episode cards without sufficiently prominent handling. | Source-confirmed at `engine/mcp/server.py` stdio request tracing. | Unique auth/memory canaries never appear in traces/logs by default; diagnostics export is explicit, warned, bounded, redacted where feasible, and covered by repository-wide canary scans. | 001 | VERIFIED |
| `MNO-COMPAT-017` | P2 | RELEASED / risk | Time and encoding contracts can silently change meaning: naive timestamps become UTC, invalid UTF-8 is replacement-decoded, and some traces lack offsets. | Source: `engine/ingest/parser.py`, `engine/mcp/server.py`, runtime trace writers. | Fixtures cover timezone-free values, DST, numeric units, invalid UTF-8, non-ASCII locales, and newline variants; ambiguous/lossy input is rejected or visibly flagged; operational timestamps include offsets. | — | VERIFIED |
| `MNO-COMPAT-018` | P1 | RELEASE GATE | A model-facing contract exists, but no blind-client gate proves that an unfamiliar LLM chooses import/observe/writeback correctly and preserves authority boundaries under degradation. | Independent integration audit; current docs explain the lanes but CI does not score a blind model against them. | Blind evaluation scores at least 90/100 with zero hard failures: no canonical promotion, no raw-import “remember this,” no unauthorized apply/escalation, and no false success under degraded capability. | 009, 010, 011, 013 | VERIFIED — independent blind model 100/100, zero hard failures |
| `MNO-COMPAT-019` | P2 | v0.2.1 CANDIDATE | Agents previously had no bounded, machine-readable way to report a reproducible MNO defect without oversharing memory stores or private runtime data. | `mno-report`, `tools/report_issue.py`, capability metadata, and `docs/SUPPORT_TICKETS_FOR_AGENTS.md`. | Local-first ticket generation requires reproduction fields, can run quick/full tests, attaches only explicitly named bounded logs, scrubs secrets, and submits only after explicit `--submit`. | 005, 010, 016 | VERIFIED |

## v0.2.1 candidate evidence

- Full clean-checkout Python suite: green on Windows against the staged candidate.
- Desktop Node suite: 62/62 green.
- Exact wheel and sdist build plus isolated installed-artifact verification: green; runtime UI and packaged guide present; version `0.2.1`; mutable state resolved outside installation resources.
- Focused restart/concurrency, WAL backup, connector rollback, capability parity, import safety, runtime signal, canonical-path, encoding, ticket-generation, and packaging regressions: green within the full suite.
- Independent unfamiliar-model contract evaluation: 100/100 with zero hard-invariant failures after public task-card output fields were made unambiguous.
- Architecture claim is deliberately bounded: v0.2.1 claims target-native Python artifacts and x64 desktop coverage; it does not claim ARM64 desktop installers.
- Remaining transition: `MNO-COMPAT-013` becomes `VERIFIED` only after GitHub's Windows/Ubuntu/macOS and Python 3.12/3.13/3.14 matrix validates the pushed commit and its exact artifacts.

## Critical path

```text
Privacy containment: 001 -> 012 -> 013
Desktop privacy:      002 -> 005 -> 007 -> 013
Bootstrap/connector:  003 -> 004 -> 008 -> 010 -> 013
Artifact/bundle:      005 -> 006 -> 013
Durable model path:   009 -> 011 -> 018 -> 013
Lifecycle/security:   014 + 016 + 017 -> 013
Canonical pathing:    015 -> 013
```

## Candidate release posture

- Desktop packaging is privacy-gated and no longer includes the repository's live `runtime` tree. Publish only artifacts produced and inspected by the release workflow.
- The wheel/sdist contract is the runnable headless product; Electron remains a separate target-native artifact.
- Do not merge or tag until `MNO-COMPAT-013` has passed on the exact pushed candidate.
- Do not use raw import for live “remember this.” Use live context retrieval plus `memory.observe` for model-autonomous provisional reinforcement, or `writeback.propose` when the user explicitly requests durable remembrance; canonical truth still requires the distinct review path.
- Keep agent-generated support tickets local by default; submission and every attached log remain explicit operations.

## Minimum evidence attached to every row

Every implementation PR must update the row with:

- exact release-vs-DEV classification;
- affected environments/transports;
- test or reproduction identifier;
- implementation owner and reviewer;
- artifact/commit digest;
- before/after observable behavior;
- regression matrix result;
- status transition and date.

The governing rectification design is `docs/MNO_COMPATIBILITY_RECTIFICATION_PLAN_2026-07-18.md`.
