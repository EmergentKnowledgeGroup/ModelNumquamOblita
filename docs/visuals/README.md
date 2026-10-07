# Visuals Guide

The canonical flowchart set in this repo is the `2026-04-12` pair:

- `MNO_LAUNCH_PIPELINE_VISUAL_SPEC_2026-04-12.md` + `MNO_LAUNCH_PIPELINE_2026-04-12.drawio`
- `MNO_LAUNCH_RUNTIME_AND_INTEGRATION_VISUAL_SPEC_2026-04-12.md` + `MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-12.drawio`
- `MNO_CURRENT_PIPELINE_VISUAL_SPEC_2026-04-12.md` + `MNO_CURRENT_PIPELINE_2026-04-12.drawio`
- `MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_VISUAL_SPEC_2026-04-12.md` + `MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_2026-04-12.drawio`

The v0.2.2 temporal contract adds the current canonical package:

- `MNO_V0_2_2_TEMPORAL_AGENCY_VISUAL_SPEC_2026-07-18.md` + `MNO_V0_2_2_TEMPORAL_AGENCY_2026-07-18.drawio`

Older dated files are historical snapshots and should not replace the `2026-04-12` files unless a newer dated set is created. They are not current user-facing WSS/live-runtime diagrams.

Canonical WSS behavior is documented in `docs/WORK_SESSION_SCRATCHPAD.md`. Diagrams should show it as strict active-scope `scratchpad_ephemeral` work-continuity context, not reviewed truth or evidence.

For v0.2, diagrams must also keep authority and maturity separate: `human_reviewed_canonical` outranks `evidence_atom`, then `provisional_consolidated`, then `provisional_observed`. `observed -> reinforced -> consolidated` is provisional maturity, never a promotion to canonical truth. Raw import creates evidence atoms; signed live `memory.observe` creates provisional records; explicit reviewer `review_apply` can materialize a `human_reviewed=false` evidence atom. STM and WSS remain non-evidence helper state.

For v0.2.2, authority, maturity, retrieval lifecycle, and temporal disposition are four independent axes. The retrieval lifecycle is `active -> dormant -> archived`; dormant fallback is cue-aware and lower priority, and only new eligible signed evidence can reactivate. Per-turn clock/due context is neutral facts only. A due poll must never be drawn as a daemon, timer, wake-up, notification, or action path.

For v0.2.3, the integration diagrams show the optional Hermes v0.19.0 plugin as an adapter over `integration-v1`: automatic `context.build` before an eligible human turn and one `memory.observe` attempt only after a completed turn. The arrow must end in provisional memory, never reviewed/canonical truth.

Rendered SVG/PNG exports live in `docs/visuals/exports/`.

For public docs, prefer `docs/visuals/exports/clean/`. Those images simplify dense fan-ins and fan-outs into readable public diagrams with no connector overlap through boxes.

For engineer-facing architecture docs, prefer `docs/visuals/exports/architecture/`. Those images preserve subsystem layers, trust boundaries, runtime paths, integration contracts, and data lineage while using routed buses to avoid connector overlap.

Regenerate the clean public image assets with:

```bash
python tools/export_clean_public_visuals.py
```

Regenerate the architecture image assets with:

```bash
python tools/export_architecture_visuals.py --strict
```

Regenerate the public image assets with:

```bash
python tools/export_drawio_visuals.py
```

Flowchart expectations:

- engineering pages can use lane containers and denser labels
- caveman pages should stay simple, sequential, and readable at a glance
- companion visual spec files should stay aligned with the matching `.drawio`
- duplicate `- Copy` artifacts should not live beside canonical files

For a quick structural check, run:

```bash
python3 skills/mno-flowchart-drawio/scripts/drawio_audit.py docs/visuals/*.drawio
```

## v0.3 lean context and learning inserts

The current runtime seam accepts optional `answer_claims`. Whole eligible canonical text matches may be supported; other interpretations are `UNVERIFIED` and require abstention from a previously passing packet. Without submitted claims the scope remains retrieved evidence, not a checked answer. Related canonical excerpts use the existing 320-character limit and label truncation; they are not original-source quotations.

The MCP-only `integration.learning.propose` shortcut uses the existing host agent and source IDs to draft a lesson or summary in the existing pending human-review queue. It adds no model, daemon, schema, or automatic promotion. Existing import, observation, human review, publish, verify, and activation paths retain their roles.

MCP anchor briefs and runtime wake/resume briefs retain the selected row's source and confidence in `summary_support`; `summary_kind=extractive` distinguishes these bounded source selections from generated synthesis. The existing aggregate confidence and graph ranking remain unchanged. Pending learning drafts do not become recall-graph facts.
