# Implementation Blueprint

## Architecture components

- `ingest_worker`: parse/normalize conversation and document sources.
- `atom_extractor`: structured candidate generation.
- `write_gate`: `ADD/UPDATE/IGNORE` decision engine.
- `mutation_review`: queue and approval workflow for proposed edits/deletes.
- `memory_store`: atom store + indexes + provenance ledger.
- `consolidator`: periodic promotion/decay/conflict maintenance.
- `continuity_builder`: derives dynamics, constellations, arcs, and shared-language keys.
- `retriever`: multi-channel candidate fetch + fusion/rerank.
- `response_gate`: claim verification and abstention policy.
- `recognition_capture`: captures post-retrieval recognition telemetry.
- `eval_harness`: offline and online quality checks.

## Minimal interfaces

### Ingest output
- `NormalizedTurn[]`

### Extractor output
- `CandidateAtom[]`

### Write gate output
- `WriteDecision[]`

### Mutation review output
- `ApprovedMutation[] | RejectedMutation[]`

### Retrieval output
- `MemoryPack`

### Continuity output
- `ContinuityPack`

### Response gate output
- `AllowedResponse | AbstainResponse | ClarifyResponse`

## Build phases

### Phase A: Deterministic foundation
- ingestion parser
- atom schema
- provenance ledger
- baseline indexes
- salience prefilter feature extractor

### Phase B: Write intelligence
- extractor prompts/schema validators
- two-stage write gate and decision logs
- dedupe and contradiction graph
- mutation review queue (`PROPOSE_EDIT`, `PROPOSE_DELETE`)
- tombstone + delayed purge executor (user-approved only)

### Phase C: Retrieval quality
- multi-channel retrieval
- fusion/rerank scoring
- claim-evidence verifier
- abstention thresholds

### Phase D: Consolidation and scale
- periodic consolidation jobs
- continuity builder jobs (dynamic patterns, constellations, narrative arcs)
- decay/archive rules
- default salience half-life = `180 days`
- latency and throughput tuning
- adaptive retrieval budget controller

### Phase E: Hardening
- red-team suite
- false-memory incident pipeline
- recognition-signal calibration
- calibration and release gating

## Release gate checklist

- false-memory rate under target threshold.
- evidence precision meets minimum.
- contradiction handling passes scenario set.
- retrieval latency within SLO under target scale.
- full audit trail available for sampled responses.
- token and cost telemetry exposed per request and in aggregate run reports.

## Coexistence with ImpressioAnimae

`ImpressioAnimae` output can seed `NumquamOblita` by:
- using cleaned conversation corpus for ingestion,
- importing anchor/cadence features as high-value procedural-style priors,
- preserving run-level provenance links for reproducibility.

## Current implementation status

- `PR-08` ships a native local runtime:
  - `engine/runtime/session.py`: retrieve -> verify -> respond -> async writeback loop.
  - `engine/runtime/server.py`: local HTTP API and static UI hosting.
  - `engine/runtime/ui/*`: telemetry and evidence-trace interface.
- `PR-10A` adds adapter contract primitives:
  - `engine/runtime/adapters.py`: adapter registry + canonical request/response contract.
  - `engine/runtime/server.py`: adapter discovery and adapter-scoped chat endpoint.
- `PR-10B` adds `openclaw` adapter envelope:
  - OpenClaw-style `messages[]` request normalization.
  - Chat-completion-shaped response payload with explicit memory evidence block.
- `PR-10C` adds `nanobot` adapter envelope:
  - Nanobot-style `query/meta/safety` request normalization.
  - Flat response contract with answer, sources, memory confidence, and usage telemetry.
