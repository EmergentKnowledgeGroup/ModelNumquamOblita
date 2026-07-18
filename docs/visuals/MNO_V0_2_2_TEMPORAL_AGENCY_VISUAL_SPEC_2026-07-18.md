# MNO v0.2.2 Temporal Agency Visual Specification

**Companion source:** [MNO_V0_2_2_TEMPORAL_AGENCY_2026-07-18.drawio](MNO_V0_2_2_TEMPORAL_AGENCY_2026-07-18.drawio)
**Generated exports:** [SVG](exports/MNO_V0_2_2_TEMPORAL_AGENCY_2026-07-18__p01_temporal-agency-contract.svg) and [PNG](exports/MNO_V0_2_2_TEMPORAL_AGENCY_2026-07-18__p01_temporal-agency-contract.png)

## Purpose

Show the complete v0.2.2 temporal contract without making MNO look autonomous. The diagram is a single engineering-readable page, but its labels must stay understandable to a non-specialist.

## Required visual claims

1. A per-turn server-clock envelope supplies `now_utc`, `now_local`, IANA timezone/source, and prior-turn provenance as neutral facts only.
2. Authority, maturity, retrieval lifecycle, and temporal disposition are separate axes. The lifecycle is `active -> dormant -> archived`; availability is not evidence.
3. A live source-backed structured schedule creates a provisional scheduled note. Raw import is separately marked evidence ingest and cannot schedule it.
4. Pending/snoozed notes hold decay until `decay_not_before_utc`; read/delivery/repetition do not reinforce.
5. Due selection is deterministic and context injection orders canonical corrections first, due provisional notes next, and cue-aware dormant fallback last. Archived content stays explicit history/deep read.
6. Only new eligible signed evidence can reinforce/reactivate a dormant or archived record.
7. `list(due_only=true, include_upcoming=false, limit=3)` is a read-only heartbeat seam. The diagram must explicitly rule out daemon, wake-up, notification, and action behavior.

## Source and export rules

- Edit the `.drawio` source, not an SVG/PNG by hand.
- `python tools/export_drawio_visuals.py` regenerates the canonical temporal SVG/PNG.
- The public-clean and engineering generator suites each render a matching temporal diagram; they must describe the same boundary without claiming a different lifecycle or action model.
- Keep the visual indexes and front-facing links aligned with the generated slug.
