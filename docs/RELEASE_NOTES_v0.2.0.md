# ModelNumquamOblita v0.2.0

MNO v0.2.0 completes the intended autonomous provisional-memory loop while preserving human-reviewed canonical truth as the highest authority.

## What changed

- Signed live observation can create, independently reinforce, and deterministically consolidate provisional memories.
- Repetition changes provisional maturity only. It never promotes a memory into human-reviewed canonical truth.
- `remember this` now has a clear live path: propose writeback, explicit human `review_apply`, then a durable evidence atom with `human_reviewed=false`.
- Source registrations and retrieval receipts prevent retrieved text, replayed messages, and fabricated IDs from counting as new support.
- Provisional storage now has durable identity, migration, lifecycle/decay, conflict blocking, immutable consolidation lineage, and restart-stable explanation.
- High-risk opt-in proposals can be inspected, dismissed, or bridged into pending human review without entering evidence or published truth.
- HTTP, MCP, headless, generated launcher, and desktop startup share the versioned policy path.
- Public docs and diagrams now distinguish canonical reviewed memory, evidence atoms, provisional memory, STM, and WSS.
- [LLMS.md](../LLMS.md) gives models and integrating agents one authoritative read-first contract.

## Authority and migration

The authority order is:

```text
human-reviewed canonical
  -> evidence atom
  -> consolidated provisional
  -> observed/reinforced provisional
  -> STM/WSS helper context
```

Fresh v0.2 setups write the safe standard provisional policy. Existing configurations that omit v0.2 fields preserve the v0.1 disabled posture until explicitly changed. Provisional sidecars migrate transactionally to schema v3; downgrade requires restoring a verified pre-migration backup.

If the pre-migration safety scan detects secret-like legacy content, automatic migration stops with `LEGACY_SECRET_DETECTED` before a writable SQLite connection is opened. Reviewer-authorized scrub mode requires and verifies a separate v2 backup before changing the original; see [Security and Privacy](SECURITY_AND_PRIVACY.md#legacy-v01-provisional-stores).

## Integration guidance

- Use raw import for a historical corpus followed by normal curation.
- Use `context.build` and signed `memory.observe` for the live conversational loop.
- Use `writeback.propose` for an explicit durable memory request.
- Only an authenticated human credential with `review_apply` may resolve/apply.
- Reviewer apply creates evidence substrate, not published canonical memory.

Start with [LLMS.md](../LLMS.md), then see [Agent Integration](AGENT_INTEGRATION.md), [API](API.md), and [MCP Integration](MCP_INTEGRATION.md).
