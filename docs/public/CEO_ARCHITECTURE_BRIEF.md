# NumquamOblita — CEO Architecture Brief (1 page)

## Executive summary

`NumquamOblita` is a local-first memory system that makes assistants **trustworthy about what they “remember”**.

Core rule: **no memory claim without evidence**.

Instead of letting a model “free-associate” about the past, the system:
1) builds a provenance-locked memory base from conversation archives,
2) promotes event-level memories into reviewable “episodes”, and
3) constrains any responder model with a bounded evidence packet + verification.

## What it connects to (self-contained vs outside)

Self-contained (works entirely on one machine):
- Archive import, memory building, review/publish, and runtime memory retrieval
- Operator UI (wizard + memory browser + “Why this answer?” + health/diagnostics)

Optional outside connections (configurable, not required):
- A responder model endpoint (local self-hosted or cloud)
- Client integrations (for other apps/agents) via a standard tool protocol layer

## The pipeline (clean box + arrow view)

```mermaid
flowchart LR
  A[Conversation archive export] --> B[Import + normalization]
  B --> C[Evidence store (atoms)\nprovenance locked]
  C --> D[Episode builder\n(event-level memories)]
  D --> E[Human review + compile\n(publish step)]
  E --> F[Published episodic memory set]
  F --> G[Runtime memory service\n(route + retrieve + bound)]
  G --> H[Context package\n(bounded evidence + verdict)]
  H --> I[Responder model\n(local or cloud)]
  I --> J[Verifier\n(fail closed)]
  J --> K[Final answer\n+ optional “Why”]
```

## Runtime behavior (in plain terms)

On each user message, the system:
- decides whether memory retrieval is warranted (routine chat should stay routine),
- retrieves a bounded set of relevant evidence (prefer event-level “episodes” when available),
- produces a structured “context package” that includes:
  - evidence snippets + citation tokens,
  - a deterministic service verdict that constrains what the model is allowed to claim,
- verifies the responder output against the delivered evidence,
- returns one of: supported answer, abstain, or a single clarifying question.

## Why this is different (and defensible)

- **Traceability**: every supported memory claim has a provenance path back to an original source message.
- **Human-in-the-loop where it matters**: event memories are reviewed before being treated as recall-grade.
- **Fail-closed**: when evidence is weak or conflicting, the system does not “guess”.
- **Operational usability**: operators can inspect “Why”, disable problematic memories, and roll back safely.

## What success looks like (business-level)

- Users stop seeing confident “made-up” memories.
- Operators can explain and fix behavior without engineers.
- The system can run offline with predictable costs; cloud usage is optional.
- Integrations can safely reuse memory via standardized tool access, without bypassing verification.

## Implementation path (high-level)

If you’re sequencing delivery, the clean order is:
1) Make import → episodes → review/publish stable and repeatable.
2) Make runtime retrieval bounded + verifiable with high abstain precision.
3) Add a universal integration layer (MCP) so any agent/client can use memory safely.
4) Expand visualization so operators can debug and correct memory behavior quickly.

Engineering SOP (for every change): do a targeted test pass first, then a regression + end-to-end smoke pass before moving on.
