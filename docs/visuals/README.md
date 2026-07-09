# Visuals Guide

The canonical flowchart set in this repo is the `2026-04-12` pair:

- `MNO_LAUNCH_PIPELINE_VISUAL_SPEC_2026-04-12.md` + `MNO_LAUNCH_PIPELINE_2026-04-12.drawio`
- `MNO_LAUNCH_RUNTIME_AND_INTEGRATION_VISUAL_SPEC_2026-04-12.md` + `MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-12.drawio`
- `MNO_CURRENT_PIPELINE_VISUAL_SPEC_2026-04-12.md` + `MNO_CURRENT_PIPELINE_2026-04-12.drawio`
- `MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_VISUAL_SPEC_2026-04-12.md` + `MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_2026-04-12.drawio`

Older dated files are historical snapshots and should not replace the `2026-04-12` files unless a newer dated set is created. They are not current user-facing WSS/live-runtime diagrams.

Canonical WSS behavior is documented in `docs/WORK_SESSION_SCRATCHPAD.md`. Diagrams should show it as strict active-scope `scratchpad_ephemeral` work-continuity context, not reviewed truth or evidence.

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
