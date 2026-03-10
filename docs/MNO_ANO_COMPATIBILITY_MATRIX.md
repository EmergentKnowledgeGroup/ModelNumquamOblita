# MNO / ANO Compatibility Matrix

Status: Placeholder during extraction  
Owner: MNO/ANO separation program

## Purpose

This is the canonical compatibility matrix for the separation program.

Until the split is complete, this file is the source of truth for:

- supported IA -> MNO version pairs
- supported MNO -> ANO version pairs
- deprecation policy
- stop-ship unsupported pairs

## Current extraction note

The standalone MNO repo is being staged first.

Until ANO is extracted into its own lane, this matrix is intentionally minimal.

## Required future fields

- IA version
- MNO version
- ANO version
- shared-contract version, if any
- support status
- release lane owner
- required contract tests
- deprecation date
