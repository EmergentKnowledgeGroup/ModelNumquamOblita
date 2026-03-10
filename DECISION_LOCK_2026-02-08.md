# Decision Lock (2026-02-08)

This file freezes core architecture decisions approved by product and design.

## Locked decisions

1. Memory representation uses both:
   - `episode` level memory atoms ("what happened"),
   - `atomic fact` memory atoms ("stable facts/traits/preferences"),
   - with explicit links between the two.

2. Truth policy is strict:
   - never synthesize unsupported memory claims,
   - if evidence is weak or conflicting, respond with uncertainty and citations.

3. PII policy:
   - raw PII is retained in local storage,
   - no automatic redaction pipeline in core memory storage.

4. Mutation policy:
   - no autonomous destructive edits by model/runtime,
   - model may propose edits/deletes with reason codes,
   - destructive actions require explicit user approval.

5. Provenance policy:
   - provenance is the authority and is immutable by default,
   - operational delete path is `tombstone + delayed purge`,
   - user can explicitly request immediate physical erase override.

6. Forgetting policy:
   - default salience half-life is `180 days`,
   - forgetting is priority decay, not factual source deletion.

7. Performance and cost policy:
   - prioritize low-latency retrieval path,
   - always expose token and cost telemetry in logs/UI.

8. Runtime target order:
   - first: native minimal chat runtime,
   - second: adapters (`OpenClaw`, `nanobot`).

## Implementation consequences

- Derived continuity layers can shape ranking/phrasing, but cannot create factual authority.
- Any unsupported claim in verifier path is a blocking failure, not a warning.
- All destructive memory operations must be auditable and reversible until final purge.
