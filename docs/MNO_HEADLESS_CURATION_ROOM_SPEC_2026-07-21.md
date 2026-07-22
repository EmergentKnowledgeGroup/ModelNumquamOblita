# MNO Headless Curation Room (HCR) Spec

**Date:** 2026-07-21  
**Scope:** A generic, local, browser-accessible curation handoff for agents and users who run MNO without the desktop shell.

## Product Contract

HCR is the missing front door to MNO's existing draft-curation and human-review machinery. It is not a Hermes integration, a second review engine, or a way around human authority.

The headless workflow is:

`Import -> Build -> CURATION_REQUIRED -> Agent proposes + human decides -> Publish -> Verify -> Activate -> Operate`

The agent may perform preparation and proposal work. The human remains authoritative for every review decision that enters `review_decisions`. Runtime activation still requires a published reviewed set and a `Safe` verification result.

## Goals

- Give any compatible local agent one deterministic command and one machine-readable status contract for headless curation.
- Open a lightweight local browser room bound to one wizard `run_id`.
- Reuse the existing episode-card review, draft proposal, audit, publish, verify, and activation contracts.
- Make the pre-curation boundary explicit enough that a headless integration cannot silently mistake raw imported atoms for an activated reviewed memory set.
- Keep normal post-activation memory operation autonomous except where existing canonical-mutation policy requires review.

## Non-Goals

- No Hermes-specific adapter, copy, assumptions, or branding.
- No new truth store or duplicate curation state.
- No agent self-promotion into `review_decisions`.
- No background autonomous reviewer.
- No change to retrieval ranking, provisional-memory promotion, or canonical mutation policy.
- No public-network review server by default.

## User Experience

### Prepare a raw source

```text
mno-curate --input /path/to/export
```

### Prepare an existing imported MNO store

```text
mno-curate --store /path/to/atoms.sqlite3
```

### Resume an existing curation run

```text
mno-curate --run-id wizard_...
```

The command starts a loopback-only setup runtime, prepares or resumes the draft, prints one JSON status object, prints the HCR URL, and opens the user's browser unless `--no-open` is supplied.

The browser route is:

```text
http://127.0.0.1:<port>/curate/<run_id>
```

HCR reuses the normal wizard UI but focuses it on Review, Publish, Verify, and Activate. Import, build, chat, memory exploration, trace, and ops controls are not presented as competing surfaces inside HCR.

## Agent Handoff Contract

`GET /api/wizard/hcr/status?run_id=<run_id>` returns a bounded object with:

- `schema`
- `run_id`
- `state`
- `human_action_required`
- `agent_can_propose`
- `human_review_required`
- `counts`
- `next_action`
- `curation_url`
- `build_id`
- `published_version_id`
- `verification_status`

Allowed states:

- `build_required`
- `curation_required`
- `review_in_progress`
- `ready_to_publish`
- `published_unverified`
- `verification_blocked`
- `ready_to_activate`
- `ready`

The response is workflow information. It must not instruct the model how to emotionally frame or behaviorally react to that information.

### Run-Bound Agent Tools

The HCR agent connection uses a dedicated MCP profile bound to exactly one wizard `run_id`.

- Tool listing and tool dispatch are both allowlisted to the draft-curation read, lease, heartbeat, release, and proposal-upsert operations.
- An omitted `run_id` is replaced with the configured room run.
- A different supplied `run_id` fails before any runtime API request.
- Human proposal promotion, direct review updates, publish, verify, activate, MCP installation, and administrative tools are absent and rejected even if called by name.
- Agent `force_release` is rejected. Human/operator force-release remains available only through the local browser/operator surface and stays audited.

## Headless Runtime Wall

The standard `mno-runtime` CLI must not silently launch a normal integration runtime without reviewed episode cards.

- When no reviewed episode artifact is available, normal launch exits with a structured `CURATION_REQUIRED` result and points to `mno-curate`.
- `--allow-uncurated` is an explicit developer/operator bypass.
- The bypass prints a prominent warning and marks the runtime binding `artifact_mode=uncurated_override`.
- Setup mode remains allowed without episode cards because it is the curation environment, not an activated memory runtime.
- Direct library embedding remains governed by the embedding application; this CLI wall does not claim to police arbitrary third-party Python construction.

## Authority And Security Invariants

1. HCR binds to exactly one existing wizard `run_id`.
2. The server binds to loopback by default.
3. A non-loopback HCR host is rejected; remote sharing is outside this version.
4. Agent proposals remain in `draft_proposals` until explicit human promotion.
5. Direct card review remains a browser/operator action and is never exposed through the HCR agent MCP profile.
6. Publish remains blocked until every reviewable card is approved, edited, or rejected, and at least one card is publishable.
7. Verify and Activate gates remain unchanged.
8. Rebuild invalidates stale proposals through the existing `build_id` binding.
9. The existing lease and append-only audit trail remain authoritative.
10. HCR never adds publish, verify, activate, install, or reviewer-impersonation capabilities to the draft-only MCP surface.

## Minimal Implementation

- Add `tools/run_headless_curation.py` and the `mno-curate` console entrypoint.
- Add a run-bound HCR tool profile and `mno-curation-mcp` console entrypoint.
- Add a lean HCR status helper and HTTP endpoint to `engine/runtime/server.py`.
- Serve `/curate/<run_id>` from the existing packaged runtime UI.
- Add an HCR UI mode in `engine/runtime/ui/app.js` and `styles.css`; reuse the existing wizard cards and API calls.
- Add the normal-runtime curation wall and explicit development bypass in `tools/run_live_runtime.py`.
- Update packaging verification, API/docs/LLM guidance, troubleshooting, changelog, and architecture diagrams.

## Acceptance Criteria

- `mno-curate --store <valid-store> --no-open` creates a run, builds draft episode cards, starts HCR, and emits `curation_required` or `review_in_progress` with a usable loopback URL.
- `mno-curate --input <source> --no-open` imports then reaches the same state.
- `mno-curate --run-id <run>` resumes exactly that run.
- HCR loads the requested run rather than whichever run is latest.
- The HCR page exposes only the focused review-to-activation path.
- Agent proposals do not alter review truth without a human promotion call.
- The HCR agent profile cannot list or directly dispatch non-curation, human-review, publish, verify, activation, installation, or administrative tools.
- The HCR browser stays on its URL-bound run, and the HCR agent profile cannot read or mutate another run.
- Direct human review, publish, Safe verify, and activation complete through the reused workflow.
- `mno-runtime --memories <store>` without reviewed episode cards fails with `CURATION_REQUIRED`.
- `mno-runtime --allow-uncurated ...` remains available, loud, and machine-detectable.
- Existing desktop wizard and no-draft-curation paths remain green.
- Wheel/sdist contain the HCR UI and `mno-curate` entrypoint.

## Final Rule

HCR succeeds when an agent can do the dirty work, stop at an unmistakable human curation wall, open one shared local room, and then continue with a verified activated memory system without creating any new path around human-reviewed canonical truth.

