# MNO / ANO Ownership Inventory

Status: Active  
Owner: MNO / ANO separation program  
Last Updated: 2026-03-10

## Purpose

This document is the canonical ownership inventory for the staged MNO / ANO disconnect.

Use it to answer three practical questions:

1. Which repo/root is authoritative for MNO work right now?
2. Which surfaces are MNO-only vs ANO-only vs historical?
3. Which mixed surfaces are already resolved inside the standalone MNO repo?

## Repo Roots

| Root | Role | Current authority |
| --- | --- | --- |
| `/mnt/z/modelNumquamOblita` | Standalone MNO repo root | Authoritative for MNO runtime, tooling, packaging, and docs in the separated lane |
| `/mnt/z/openaidata/numquamoblita` | Legacy mixed monorepo root | Historical source for prior mixed work; current ANO execution still lives here until ANO is extracted |
| `/mnt/z/openaidata/numquamoblita_mno_desktop_gui` | Historical MNO staging tree | Historical only; not authoritative after standalone cutover |

## Current Ownership Map

### MNO-owned in the standalone repo

- `engine/config.py`
- `engine/contracts.py`
- `engine/memory/*`
- `engine/retrieval/*`
- `engine/continuity/*`
- `engine/runtime/*` except removed ANO runtime surfaces
- `engine/mcp/*`
- `engine/write_gate/*`
- `tools/import_*`
- `tools/build_episode_*`
- `tools/run_*` surfaces that operate the MNO runtime, eval, signoff, pilot, packaging, or MCP layers
- `tests/unit/*` and `tests/integration/*` that exercise MNO-only behavior
- MNO operator docs, guides, specs, blockerboards, and public docs

### ANO-owned outside the standalone repo

- `engine/research/*`
- `engine/runtime/ano_incremental.py`
- document-research / scale / qualification / supervisor tooling
- ANO operator UI/server surfaces
- ANO distribution/release docs, blockerboards, and eval harnesses

Current practical location: the legacy monorepo remains the only live ANO workspace until ANO gets its own standalone repo.

### Shared surfaces

- None are active in the standalone MNO repo today.

If a future shared lane is created, it must stay limited to:

- stable contracts
- narrow adapter interfaces
- version/schema constants

### Compatibility shims

- None are active in the standalone MNO repo today.

Any future shim must declare:

- owner
- preserved path/behavior
- reason
- removal trigger
- latest allowed release/version

## Mixed Surfaces Resolved For Standalone MNO

| Former mixed surface | Standalone MNO outcome | Status |
| --- | --- | --- |
| `engine/__init__.py` | exports only MNO-owned symbols | Resolved |
| `engine/runtime/server.py` | no ANO runtime manager or ANO endpoints on mandatory path | Resolved |
| `engine/runtime/ui/index.html` | no ANO operator controls | Resolved |
| `engine/runtime/ui/app.js` | no ANO incremental/client logic | Resolved |
| `tests/integration/test_runtime_server.py` | MNO-only runtime assertions retained | Resolved |
| packaging identity | standalone package name `modelnumquamoblita` | Resolved |

## External Blockers Still Outside This Repo

These are real remaining disconnect blockers, but they are not finishable from the standalone MNO repo alone:

- ANO standalone repo/root does not exist yet as a clean extracted lane
- ANO cannot yet prove it consumes only public MNO contracts because ANO is still operating from the legacy mixed repo
- cross-lane compatibility gate enforcement cannot be marked complete until ANO has a release/test lane that consumes the canonical matrix

## Practical Rule

When working on standalone MNO:

- treat this repo as authoritative for MNO
- do not copy ANO code back in
- do not point normal MNO docs/operators at ANO tooling
- treat any future ANO dependency as a blocker unless it is a declared public contract
