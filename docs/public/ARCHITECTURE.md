# Public Architecture

## High-level build flow

`raw source -> import/normalize -> atoms.sqlite3 -> draft episode cards -> optional draft curation -> human review -> reviewed episode cards -> runtime`

## High-level runtime flow

`incoming turn -> route -> shortlist evidence -> build context package -> answer or abstain -> optional proposal-only writeback`

## Import behavior

Raw-source import is normalized before extraction:
- supported files are converted into clean conversations and turns
- original normalized wording is preserved in a bounded raw-context sidecar for provenance and quote retrieval
- whitespace is cleaned
- roles and timestamps are normalized when possible
- junk folders are skipped during folder walks
- the desktop setup flow lets operators pick files and folders through the explorer UI, mix them in one source list, and either create a new store or append into an existing one

## Main memory layers

- atoms
  - the durable evidence substrate
- reviewed episode cards
  - the reviewed event-memory layer
  - can carry explicit truth-family lineage so corrected versions stay linked
- runtime helper layers
  - short-term memory
  - provisional memory
  - proposal-only writeback
  - continuity surfaces like pins, action log, wake-up pack, and resume pack

Important rule:

Runtime helper layers do not outrank reviewed truth.

Reviewed lineage metadata also does not silently rewrite history. It helps the runtime prefer the current reviewed version while still preserving older reviewed context.

## Retrieval shape

Current retrieval shape is:

`query -> lexical + bm25 + semantic + sequence + quote + excerpt + temporal + graph + bounded ANN -> fusion -> guarded shortlist -> evidence pack -> verifier`

`ANN` means `approximate nearest neighbor`.

In MNO it is:
- local
- bounded
- additive only
- kill-switchable

## Integration surfaces

- desktop shell
- headless runtime over HTTP
- `integration-v1` public orchestration contract
- MCP sidecar
- compatibility adapters for `reference`, `openclaw`, and `nanobot`

## Truth boundaries

- import creates evidence atoms
- build creates draft cards
- optional draft curation stays draft-only
- human review remains authoritative
- writeback is propose/resolve gated
- verifier remains in the live answer path

## Visual reference

![Launch Pipeline](../visuals/exports/clean/mno-launch-pipeline-clean.svg)

![Runtime And Integration](../visuals/exports/clean/mno-runtime-integration-clean.svg)

## Engineer architecture reference

![System Context](../visuals/exports/architecture/mno-architecture-system-context.svg)

![Runtime Retrieval](../visuals/exports/architecture/mno-architecture-runtime-retrieval.svg)

![Memory Trust Boundaries](../visuals/exports/architecture/mno-architecture-memory-trust-boundaries.svg)

- [Clean Public Diagram Exports](../visuals/exports/clean/README.md)
- [Architecture Diagram Exports](../visuals/exports/architecture/README.md)
- [Rendered SVG/PNG Export Index](../visuals/exports/README.md)
- [Launch Pipeline Visual Spec](../visuals/MNO_LAUNCH_PIPELINE_VISUAL_SPEC_2026-04-12.md)
- [Launch Pipeline Draw.io](../visuals/MNO_LAUNCH_PIPELINE_2026-04-12.drawio)
- [Launch Runtime And Integration Visual Spec](../visuals/MNO_LAUNCH_RUNTIME_AND_INTEGRATION_VISUAL_SPEC_2026-04-12.md)
- [Launch Runtime And Integration Draw.io](../visuals/MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-12.drawio)
- [Current Pipeline Visual Spec](../visuals/MNO_CURRENT_PIPELINE_VISUAL_SPEC_2026-04-12.md)
- [Current Pipeline Draw.io](../visuals/MNO_CURRENT_PIPELINE_2026-04-12.drawio)
- [Current Runtime Memory And Decision Visual Spec](../visuals/MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_VISUAL_SPEC_2026-04-12.md)
- [Current Runtime Memory And Decision Draw.io](../visuals/MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_2026-04-12.drawio)
- [Response To "Why Long-Term Memory Remains Unsolved"](MNO_RESPONSE_TO_WHY_LONG_TERM_MEMORY_REMAINS_UNSOLVED_2026-04-12.md)
