# Near-Perfect Goal

This is the standing target for NumquamOblita memory quality.

## What “near-perfect” means
- Memory prompts read like real events, not chopped fragments.
- Anchors are concrete: person, place, idea, concept, joke, or named event.
- Wrong-detail prompts trigger correction behavior (`X, not Y`) with citations.
- True unknown prompts trigger abstain behavior (`I don't have that memory`).
- Routine chat stays lightweight and does not over-recall memory.
- Retrieval remains fast enough for normal conversation flow.

## Quality bar for eval generation
- No generic prompt stems like “this moment:” without concrete anchors.
- No tooling garbage in prompts (hex dumps, patch syntax, command blobs).
- At least one explicit correction-style case in larger trust-v3 runs.
- At least one explicit abstain-style unknown trap in every trust-v3 run.

## Runtime behavior expectations
- Fast lane: short-term + current context first.
- Deep lane: long-term retrieval only when needed.
- Every memory-backed answer is traceable to source IDs.

## Product promise
- This system is a memory assistant, not a fantasy generator.
- If it cannot support a claim, it says so.
