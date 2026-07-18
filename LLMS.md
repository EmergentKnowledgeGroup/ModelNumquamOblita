# Read This First If You Are an LLM

You are looking at **Model Numquam Oblita (MNO)**: an evidence-backed memory system for an existing model or agent. MNO is not a second personality, a replacement model, or a database that treats every sentence as truth.

Your job is to use MNO as a memory sidecar while preserving its authority boundaries.

## The one rule you must not blur

Repeated independent evidence may make a provisional memory more stable and more retrievable. It does **not** make that memory human-reviewed canonical truth.

The authority path is:

```text
model-autonomous observation
  -> provisional observed
  -> provisional reinforced
  -> provisional consolidated

explicit human review and apply
  -> evidence atom

normal build, review, publish, and activate workflow
  -> human-reviewed canonical memory
```

Ten thousand provisional reinforcements still do not cross the human-review boundary.

## Know the memory layers

| Layer | What it means | How you should use it |
|---|---|---|
| `human_reviewed_canonical` | Published and activated through MNO's human review pipeline | Prefer it over every lower tier |
| `evidence_atom` | Durable evidence accepted through explicit reviewer apply, but not yet published canonical truth | Cite it as evidence; do not call it human-reviewed canonical |
| `provisional_consolidated` | A deterministic synthesis supported by enough independent eligible evidence | Use with an explicit provisional label |
| `provisional_observed` / `provisional_reinforced` | Direct observations with one or more independent evidence units | Treat as tentative and preserve conflict warnings |
| `proposal_pending` | A request waiting for an authorized human decision | Never describe it as saved truth |
| STM | Short-term working memory for the current interaction | Do not treat it as durable evidence |
| WSS | Scoped work-session scratchpad context | Helpful context only; never evidence or canonical memory |

Authority and maturity are separate. A consolidated provisional memory is more mature than a one-off observation, but it remains below an evidence atom and below human-reviewed canonical memory.

## The normal external-agent loop

1. Call `integration.context.build` before answering when durable memory may matter.
2. Read every returned item's `authority_tier`, `maturity`, `lifecycle`, `conflict_state`, citations, and lineage.
3. Prefer reviewed canonical evidence. Keep provisional labels and contradictions visible in your answer.
4. Produce the model response.
5. Report the completed turn with `integration.memory.observe`.
6. Pass back the signed `source_registration` and `retrieval_receipt` exactly as MNO issued them.
7. If the user explicitly says “remember this,” report `remember_intent: "user_explicit"` and tell the user that human-reviewed writeback is still required for durable evidence/canonical truth.

Before using a write or maintenance operation, call `integration.capabilities.get`. Distinguish an exposed tool from one that is authorized and available for your current principal. If the response says unavailable, degraded, or unauthorized, report that state; do not invent success, switch credentials, or bypass the operation through raw import.

`context.build` is read-only. `memory.observe` is the explicit live write that lets MNO evaluate safe provisional evidence. Do not use raw import as the day-to-day “remember this” path.

## Source identity and self-echo rules

- Never invent or edit a `source_registration` or `retrieval_receipt`.
- Never replay retrieved memory as if it were new independent support.
- Never mint new message IDs to make repeated text look independent.
- Quotations, paraphrases, summaries, and derived answers from retrieved material do not reinforce that material.
- Assistant-authored text normally contributes zero support. A self-claim can contribute only under the stricter policy when a valid receipt proves that no memory evidence was retrieved.
- System and developer messages never count as durable support.
- If a handle is absent, invalid, expired, or bound to different content, expect zero support or an atomic error. Do not retry with fabricated identity.

## “Remember this” is live writeback, not raw import

For an explicit user memory request:

1. Call `integration.writeback.propose` with the candidate and its evidence.
2. Stop at `pending_review`.
3. An authenticated human principal with the separate `review_apply` capability calls `integration.writeback.resolve` with `decision: "approve"` and `apply: true`.
4. The result is an `evidence_atom` with `human_reviewed: false`.
5. The normal MNO build/review/publish/activate workflow is still required before it becomes `human_reviewed_canonical`.

You may propose. You may not grant yourself `review_apply`, impersonate a reviewer with `decided_by`, approve your own proposal, or silently apply a mutation. `decided_by` is display metadata; the authenticated principal is authoritative.

Raw import remains appropriate for initial corpus/history ingestion followed by MNO's curation workflow. It is not the live conversational memory API.

## Consolidation behavior

MNO v0.2 consolidation is bounded and deterministic:

- only eligible independent evidence increases support;
- exact `claim_key` matches may consolidate;
- semantic near-duplicates are detected and logged, not silently merged;
- conflict blocks consolidation under the default policy;
- unchanged inputs replay as a no-op;
- new eligible support creates an immutable superseding revision;
- decay can move memories to dormant or archived states without erasing lineage;
- none of these operations mutate review decisions, published artifacts, activation state, or canonical truth.

## Security behavior

Do not send credentials, bearer tokens, passwords, API keys, private keys, or equivalent secrets as memory content. MNO sanitizes or rejects secret-like content before persistence. Never try to bypass that policy by encoding or hashing a secret.

High-risk identity and relationship inference capture is off by default. Respect proposal-only/quarantine responses and do not present them as memory.

When that opt-in lane is enabled, `integration.memory.proposals.list` is metadata-only for operators; content inspection, `.dismiss`, and `.bridge` require `review_apply`. A bridge creates a source-backed pending review proposal only. It does not apply an atom, publish memory, or make the proposal true.

## When you explain MNO to a human

Use this wording:

> MNO lets the model form tentative memories from repeated independent evidence, but repetition only increases provisional maturity. Human-reviewed published memory remains the source of truth.

If asked whether human approval is required for every provisional observation, answer **no**. If asked whether autonomous reinforcement can become canonical truth, answer **no**.

## If you find an MNO bug

Use `mno-report` instead of inventing a report format. Supply a title, summary, exact reproduction steps, expected behavior, actual behavior, and useful agent notes. The command can run the bounded compatibility checks and can include only logs you explicitly name; selected logs are size-bounded and secret-redacted. It never sweeps memory stores or private runtime data.

Create and review the local bundle first. Use `--submit` only when the human has explicitly authorized opening a GitHub issue and the GitHub CLI is authenticated. Never attach databases, WAL/SHM files, credentials, WSS data, or private source datasets. See [`docs/SUPPORT_TICKETS_FOR_AGENTS.md`](docs/SUPPORT_TICKETS_FOR_AGENTS.md).

## Where to go next

- Human quick start: [`docs/QUICKSTART.md`](docs/QUICKSTART.md)
- Integration contract: [`docs/AGENT_INTEGRATION.md`](docs/AGENT_INTEGRATION.md)
- API reference: [`docs/API.md`](docs/API.md)
- Architecture and trust boundaries: [`docs/public/ARCHITECTURE.md`](docs/public/ARCHITECTURE.md)
- Configuration: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)
- Security and privacy: [`docs/SECURITY_AND_PRIVACY.md`](docs/SECURITY_AND_PRIVACY.md)
- Compatibility and artifact support: [`docs/COMPATIBILITY_AND_SUPPORT.md`](docs/COMPATIBILITY_AND_SUPPORT.md)
- Agent bug reports: [`docs/SUPPORT_TICKETS_FOR_AGENTS.md`](docs/SUPPORT_TICKETS_FOR_AGENTS.md)
- The locked v0.2 design contract: [`docs/MNO_V0_2_MODEL_CONSOLIDATION_SPEC_2026-07-17.md`](docs/MNO_V0_2_MODEL_CONSOLIDATION_SPEC_2026-07-17.md)

When code and prose appear to disagree, preserve the authority boundary above, report the mismatch, and do not invent a shortcut.
