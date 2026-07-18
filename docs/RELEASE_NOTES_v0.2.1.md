# ModelNumquamOblita v0.2.1

v0.2.1 is the compatibility and release-hardening follow-up to v0.2.0. It preserves the intended memory design: models may autonomously observe, reinforce, and consolidate provisional memory, while human-reviewed canonical truth remains a separate higher-authority layer.

## What changed

- Raw import now rejects secret-like content before any conversation, raw-context, report, trace, or database persistence.
- Live SQLite/WAL imports use consistent backup semantics instead of copying only the main database file.
- Python selection uses argument-vector capability discovery, supports explicit and uv-managed interpreters, and does not require `ensurepip` as a health proxy.
- Native Windows and WSL executable discovery rejects cross-format commands; WSL is optional.
- The Python artifact now includes runnable runtime, MCP, combined agent-MCP, setup, and import commands plus runtime UI/package data, with mutable state outside the installation.
- Exported integration launchers are relocatable and never run setup implicitly.
- Connector discovery is current-user scoped and connector updates are capability-probed, atomic, backup-protected, and rollback-safe.
- Durable writeback proposal replay and provisional maintenance now survive restart/concurrency with bounded, truthful behavior.
- Runtime shutdown, canonical store-path precedence, trace redaction, UTF-8 handling, and timestamp diagnostics are hardened.
- Capability responses distinguish exposure from effective authorization/backend/policy availability.
- Agents can run `mno-report` to create a redacted, reproducible, local-first support ticket with bounded diagnostics; GitHub submission and each log attachment require explicit opt-in.
- CI covers Python 3.12-3.14 on Windows, Ubuntu, and macOS; desktop tests on all three; and an isolated exact-artifact proof with recorded digests.

## Artifact contract

The Python wheel is the runnable headless product. The Electron desktop app remains a separate target-native artifact. v0.2.1 does not claim ARM64 desktop installers.

## Model integration reminder

Raw import is corpus/backfill ingestion. Live `memory.observe` is the autonomous provisional reinforcement lane. An explicit user “remember this” uses `writeback.propose`; only a separately authenticated human `review_apply` workflow can resolve/apply it, and that creates an evidence atom—not published canonical truth.

See [Compatibility and Support](COMPATIBILITY_AND_SUPPORT.md), [LLM Read First](../LLMS.md), and [Agent Integration](AGENT_INTEGRATION.md).
