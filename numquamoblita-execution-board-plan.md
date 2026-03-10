# Plan: NumquamOblita Execution Board

**Generated**: 2026-02-08
**Estimated Complexity**: High
**Mode**: Modular PR sequence with regression gates

## Overview
Build `NumquamOblita` as a local-first, evidence-first memory engine that can attach to stateless chat calls without hallucinated memory. Work is split into small PRs so each merge is demoable, testable, and rollback-safe.

## Prerequisites
- Python 3.12+
- Existing local corpus from `conversations.json`
- No external services required for core tests (use deterministic stubs)
- Source-of-truth constraints from `DECISION_LOCK_2026-02-08.md`

## Locked Constraints (Must Never Regress)
- No factual claim without evidence atom.
- On low confidence/conflict: uncertainty + citations.
- No autonomous destructive mutation.
- Delete path: tombstone then delayed purge; immediate erase is explicit user override.
- Default salience half-life: 180 days.
- Raw PII retained locally.
- Memory representation includes episode + atomic fact atoms with explicit links.

## Implementation Layout (Frozen Before Coding)
- `NumquamOblita/engine/ingest/`
- `NumquamOblita/engine/memory/`
- `NumquamOblita/engine/retrieval/`
- `NumquamOblita/engine/continuity/`
- `NumquamOblita/engine/runtime/`
- `NumquamOblita/tests/unit/`
- `NumquamOblita/tests/integration/`
- `NumquamOblita/tests/fixtures/`

## PR Sequence

Dependency order:
- PR-01 -> PR-02 -> PR-03 -> PR-04 -> PR-05 -> PR-06 -> PR-07 -> PR-08 -> PR-09
- PR-10 depends on PR-08 and PR-09 completion.

### PR-01: Foundation + Contracts
**Goal**: Establish package layout, typed contracts, config, and test harness.
**Tasks**:
1. Define canonical dataclasses/schemas for `NormalizedTurn`, `CandidateAtom`, `WriteDecision`, `MemoryPack`. (Complexity 4)
2. Add config module for thresholds, decay, budgets. (Complexity 3)
3. Add baseline `pytest` harness and CI-local test entrypoint. (Complexity 2)
**Validation**:
- `python3 -m pytest -q`
- Contract serialization roundtrip tests pass.

### PR-02: Ingest + Normalization
**Goal**: Deterministic parser for large exports and auxiliary docs.
**Tasks**:
1. Streaming parser for JSON export with robust timestamp normalization. (7)
2. Role normalization + preface/tool-noise stripping with reason codes. (6)
3. Fixture generator using slices from real `conversations.json`. (5)
**Validation**:
- Parser/role/timestamp regression suite.
- FC-01/02/03/06 targeted tests.

### PR-03: Atom Store + Provenance Ledger
**Goal**: Source-authoritative storage with immutable lineage.
**Tasks**:
1. Implement atom repository and append-only provenance ledger. (6)
2. Implement contradiction graph and version links. (6)
3. Implement salience metadata and 180-day decay fields. (4)
**Validation**:
- Invariant tests (`source_refs` required, no destructive overwrite).
- FC-04/05/08 guard tests.

### PR-04: Write Gate A + Salience Prefilter
**Goal**: Cheap deterministic triage before model spend.
**Tasks**:
1. Deterministic salience feature extraction. (6)
2. Stage-A write gate rules (`ADD/UPDATE/IGNORE`). (5)
3. Decision logging with reason codes. (4)
**Validation**:
- Noise-rejection and callback-rescue tests.
- FC-06/07/09 regression tests.

### PR-05: Write Gate B + Mutation Review
**Goal**: Ambiguous-case judgment + approval-required destructive flow.
**Tasks**:
1. Stage-B judgment adapter interface with offline deterministic stub. (6)
2. Add `PROPOSE_EDIT/PROPOSE_DELETE` queue. (5)
3. Implement tombstone + delayed purge executor. (5)
**Validation**:
- No autonomous delete tests.
- Mutation queue auditability tests.

### PR-06: Retrieval + Verifier + Abstain
**Goal**: Multi-channel recall with fail-closed claim verifier.
**Tasks**:
1. Lexical/vector/time/graph retrieval fusion with bounded budgets. (8)
2. Build `MemoryPack` with core/context/conflict/continuity sections. (5)
3. Claim-evidence verifier; force rewrite/abstain on mismatch. (7)
**Validation**:
- `recall@8`, evidence precision tests.
- FC-20/21/22/23 must-pass tests.

### PR-07: Consolidation + Continuity Objects
**Goal**: Build continuity layers without bypassing evidence contract.
**Tasks**:
1. Consolidation jobs for episodic->semantic promotion and decay. (7)
2. Derive `dynamic_pattern`, `constellation`, `narrative_arc`, `shared_language_key`. (8)
3. Recognition telemetry capture and bounded influence in ranking. (6)
**Validation**:
- Continuity coherence tests.
- FC-10/11/12/13/14 regression tests.

### PR-08: Native Runtime + Telemetry UI
**Goal**: Minimal local chat runtime using stateless API + memory layer.
**Tasks**:
1. Build runtime endpoint pipeline: retrieve -> verify -> respond -> async writeback. (7)
2. Add visible token/cost/latency telemetry per turn and aggregate. (5)
3. Add evidence trace panel (non-secret, source-citation view). (6)
**Validation**:
- Integration tests for stateless continuity behavior.
- Telemetry and evidence trace assertions.

### PR-09: Gate Harness + Failure Library Automation
**Goal**: Operational readiness gate with PASS/CONDITIONAL/FAIL.
**Tasks**:
1. Implement acceptance metric runner and confidence intervals. (7)
2. Encode `V3_FAILURE_CASE_LIBRARY.md` as executable test matrix. (6)
3. Generate daily pilot report artifacts and incident template output. (5)
**Validation**:
- Must-pass subset green.
- Stop conditions correctly trigger fail status.
- Gate datasets meet minimum sizes (`gold`, `contradiction`, `adversarial`, `drift`, `recognition`) with temporal holdout.
- Anti-gaming checks pass: `memory_claim_coverage` floor, macro + worst-slice pass, slice reports by query class and memory age.

### PR-10: Adapter Layer (`OpenClaw`, `nanobot`)
**Goal**: Plug memory engine into external chat runtimes after native runtime is stable.
**Tasks**:
1. Adapter interface contract and reference implementation. (5)
2. `OpenClaw` adapter + integration tests. (6)
3. `nanobot` adapter + integration tests. (6)
**Validation**:
- Contract compliance tests.
- Runtime parity tests vs native behavior.

## Regression Gates (Applied Every PR)
1. Unit tests pass with zero flaky failures.
2. Relevant FC-* targeted tests pass for touched subsystem.
3. No increase in unsupported claim count on deterministic traces.
4. No schema/contract drift without version bump + migration note.
5. Logs remain human-readable with root-cause hints.

## Stop Rules
- Immediate stop on any P0 failure (`FC-20/21/22/25`).
- Immediate stop if any unsupported memory claim reaches final response path.
- Block merge if contradiction behavior loses uncertainty+citation response.

## Runtime Rollback Triggers
- Roll back on verifier bypass incident.
- Roll back when false-memory incidents exceed accepted threshold window.
- Roll back on canary mismatch against control per acceptance criteria.

## Gate Reporting Contract
- Every gate run outputs:
  - metric summary,
  - per-set error analysis,
  - root-cause by layer (`ingest/write/retrieval/verifier/generation`),
  - decision (`PASS`/`CONDITIONAL`/`FAIL`),
  - slice reports (query class, memory age, continuity object usage).

## PR Workflow (Per Step)
1. Create branch from latest `main`.
2. Implement only that PR scope.
3. Run local test gates and targeted failure tests.
4. Update docs/spec deltas and changelog note.
5. Open PR to `main`.
6. Resolve review feedback completely.
7. Merge and tag gate result in runtime report.

## Demo Milestones
- After PR-03: deterministic ingest + auditable memory ledger demo.
- After PR-06: evidence-backed recall demo with abstain behavior.
- After PR-08: end-to-end stateless chat continuity demo.
- After PR-09: runnable readiness gate for pilot decision.
