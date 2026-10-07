# Installed MNO Runtime

This package provides the local headless runtime and MCP command surfaces:

```text
mno-runtime --setup-mode
mno-mcp --help
mno-import --help
mno-curate --help
mno-curation-mcp --help
```

Mutable databases, policy, locks, reports, and diagnostics live in the
platform user-state directory by default. Set `MNO_RUNTIME_STATE_ROOT` to use
an explicit writable location.

The Electron desktop application is distributed separately from the Python
wheel. See the public repository documentation for desktop packaging and the
full build/review/publish workflow.

## Headless curation

If an agent or operator starts from raw source or an unreviewed store, use the
generic local Headless Curation Room before normal runtime activation:

```text
mno-curate --input /absolute/path/to/source-or-folder
mno-curate --store /absolute/path/to/atoms.sqlite3
```

The command opens a browser room bound to one setup run. An agent may inspect
cards and submit draft-only proposals through `mno-curation-mcp`; a human must
still decide the review cards and complete Publish, Verify, and Activate.
Normal `mno-runtime` and live MCP launchers stop with `CURATION_REQUIRED` when
reviewed episode cards are missing. `--allow-uncurated` is an explicit unsafe
development override, not a successful setup path.

## Temporal facts

The runtime can expose bounded server-clock facts and source-backed provisional temporal notes through `integration-v1` and `mno-mcp`. Use `mno-mcp --help` after starting the runtime, then call capabilities before using temporal tools. Time uses IANA zones and server snapshots; the optional due poll is read-only and never starts a daemon, notification, wake-up, or action.

For the complete schedule/list/get/resolve contract, source-handle requirement, and durable SQLite boundary, use the source-checkout-only `docs/API.md` and `docs/MCP_INTEGRATION.md`, or read their versioned copies in the [v0.2.2 repository](https://github.com/EmergentKnowledgeGroup/ModelNumquamOblita/tree/v0.2.2/docs).

## Lean packets, drafts, and briefs

V2 context calls accept optional non-empty `answer_claims`. Read the returned verdict and its scope: `retrieved_evidence` is not verification of a proposed answer. Unverified claims abstain; canonical related excerpts remain bounded and explicitly labeled. Compact `agent_context` preserves `verification` through its context budget.

In a normal runtime MCP profile, an authorized operator/admin with mutations enabled can use `integration.learning.propose` to submit a host-authored `lesson` or `summary`, linking existing `evidence_ids`. Supply `text`, `idempotency_key`, `session_id`, and `run_id`; stop at pending human review. This tool is unavailable in the run-bound HCR profile. Native automatic capture remains separate and MCP installation alone does not create a lifecycle hook.

Anchor briefs and wake-up-pack briefs identify the selected extractive summary's source support. These changes add no model or runtime dependency and preserve human Review → Publish → Verify → Activate. See the repository [API guide](https://github.com/EmergentKnowledgeGroup/ModelNumquamOblita/blob/main/docs/API.md) and [MCP guide](https://github.com/EmergentKnowledgeGroup/ModelNumquamOblita/blob/main/docs/MCP_INTEGRATION.md) for the full contract.
