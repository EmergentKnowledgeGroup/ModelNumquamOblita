# MNO / ANO Compatibility Matrix

Status: Active during staged separation  
Owner: MNO / ANO separation program  
Last Updated: 2026-03-10

## Purpose

This is the canonical compatibility matrix for the separation program.

Every claimed compatibility statement between IA, MNO, and ANO must anchor here before release language, docs, or gates can claim support.

## Canonical Policy

This file is the source of truth for:

- supported IA -> MNO version pairs
- supported MNO -> ANO version pairs
- any future shared-contract version pairing
- deprecation policy
- stop-ship unsupported pairs

No other file may overrule this matrix.

## Current Extraction State

- standalone MNO exists now in `ModelNumquamOblita`
- ANO does not yet exist as a standalone repo/package lane
- therefore, current supported claims are intentionally narrow

## Supported Pairs

### IA -> MNO

| IA shape/version | MNO version | Status | Release lane owner | Required contract tests | Deprecation |
| --- | --- | --- | --- | --- | --- |
| IA normalized conversation export (`conversations[]` archive shape used by `tools/import_ia_db.py`) | `0.1.x` | Supported | MNO | import pipeline tests, standalone boundary audit, full `pytest -q` | none |

### MNO -> ANO

| MNO version | ANO version | Shared-contract version | Status | Release lane owner | Required contract tests | Deprecation |
| --- | --- | --- | --- | --- | --- | --- |
| `0.1.x` standalone | not yet extracted | none | Unsupported to claim compatibility until ANO standalone lane exists | Separation program | n/a | n/a |

### Legacy Monorepo -> Standalone MNO

| Source lane | Target lane | Status | Release lane owner | Required contract tests | Deprecation |
| --- | --- | --- | --- | --- | --- |
| legacy `NumquamOblita` monorepo MNO artifacts | standalone `ModelNumquamOblita` `0.1.x` | Migration-supported | MNO | migration guide checks, standalone boundary audit, runtime launch against existing store | retire after ANO standalone cutover is complete |

## Stop-Ship Rules

Do not ship a compatibility claim if any of the following is true:

- a claimed pair is missing from this matrix
- ANO claims support against standalone MNO before ANO standalone extraction exists
- a lane consumes private/internal APIs instead of declared public contracts
- required contract tests for a claimed pair are missing or failing
- deprecation has passed without explicit renewal

## Update Rules

- update this file in the same PR that changes a claimed compatibility contract
- both future lanes must gate releases against this file once ANO standalone exists
- if no ANO standalone lane exists yet, MNO may ship standalone-only releases without inventing a fake ANO compatibility row
- deprecation dates must be concrete before a pair is marked `deprecated`
