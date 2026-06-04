# Diagram Standards

## Canonical Files

Treat the `2026-04-12` visual spec and draw.io files as the current source of truth for public-facing and current-state flowcharts.

## Page Intent

- `Engineering*`: lane-based architecture or runtime maps for technical readers
- `Caveman*`: low-jargon flowcharts for quick comprehension

## Practical Review Rules

- Keep caveman pages linear and glanceable.
- Keep engineering pages aligned to the companion spec headings.
- Avoid orphaned duplicate files in `docs/visuals`.
- Prefer dated replacements over silent overwrites when a major diagram meaning changes.
- Update the matching spec when a page name, page count, or major flow step changes.

## Audit Heuristics

- Long labels are more acceptable on engineering pages than caveman pages.
- A page with no edges is suspicious unless it is intentionally a legend or notes page.
- A new file should not become canonical without an updated dated spec pair.
