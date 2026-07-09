# Work-Session Scratchpad

The work-session scratchpad, or `WSS`, is MNO's built-in continuity helper for active agent work.

It exists for one job: help an agent resume work without rereading the same local background over and over.

## Runtime Shape

WSS stores deterministic helper summaries in one project-local sidecar under the runtime state root. When a v2 context package has strict project, thread, and workstream scope identity, MNO can attach those summaries as:

```text
work_session_context.trust_tier = scratchpad_ephemeral
```

No separate user-facing feature toggle is required for the normal live behavior. Strict scope identity is the safety gate:

- project identity
- thread identity
- workstream identity
- runtime-store fingerprint

If that scope is missing or degraded, WSS fails closed and no `work_session_context` is attached.

## What WSS Is

- project-local helper state
- deterministic summary state
- strict-scope context-package continuity
- short-lived operational memory for the current work lane
- a context-diet helper for agents that would otherwise reread repeated background

## What WSS Is Not

WSS is not:

- reviewed memory
- retrieval evidence
- MemoryPack truth
- review, publish, verify, or activation state
- a prompt-history mutator
- a source of memory claims
- a promoted scratchpad status
- an LLM-generated memory map

The key rule is:

```text
WSS can remind an agent what work it was doing.
WSS cannot prove a memory.
```

## Where It Appears

WSS can appear in runtime v2 context packages as `work_session_context` when strict `work_session_scope` is present.

Context-package and adapter callers can provide scope as:

```json
{
  "work_session_scope": {
    "thread_id": "thread_or_conversation_id",
    "workstream_key": "stable_workstream_key",
    "workstream_name": "Human readable workstream name"
  }
}
```

The compatibility aliases `work_session_thread_id`, `work_session_workstream_key`, and `work_session_workstream_name` are also accepted by runtime context-package endpoints.

The stable `integration-v1` memory envelope remains evidence-focused. Do not treat WSS as part of the public evidence contract.

## Trust Boundary

WSS rows are non-authoritative. They may be useful context, but they never outrank:

- reviewed episode cards
- source-linked atoms
- provenance and raw-context receipts
- verifier decisions
- human review

If an answer needs a memory claim, it still needs evidence outside WSS.

## Configuration

The live defaults are documented in [Configuration](CONFIGURATION.md#work-session-scratchpad). Operational config can disable WSS, but the product behavior is live-on for strict-scope context packages.

## Related Docs

- [Public Architecture](public/ARCHITECTURE.md)
- [Pipeline Guide](PIPELINE_GUIDE.md)
- [Agent Integration](AGENT_INTEGRATION.md)
- [API](API.md)
- [Security And Privacy](SECURITY_AND_PRIVACY.md)
- [Visuals Guide](visuals/README.md)
