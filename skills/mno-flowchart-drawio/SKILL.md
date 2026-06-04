---
name: mno-flowchart-drawio
description: Review or edit the draw.io flowcharts in docs/visuals for this repo. Use when updating diagrams.net files, checking flowchart readability, syncing a visual spec with its matching .drawio, removing stale duplicate visual artifacts, or auditing label density/page structure in the MNO launch/current-state diagrams.
---

# MNO Flowchart Draw.io

Use this skill for the MNO diagram set in `docs/visuals`.

## Scope

- `2026-04-12` files are the canonical visuals
- older dated files are historical references
- `Engineering` pages can be denser and lane-based
- `Caveman` pages should read as the simplest end-user flowchart

## Workflow

1. Open the matching visual spec and `.drawio` together.
2. Keep the page list in sync with the spec before adjusting wording or flow.
3. Prefer short, scannable node labels on caveman pages.
4. Preserve the trust boundary language:
   - reviewed truth outranks helper layers
   - raw-context lanes are inspectability support, not truth authority
   - proposal-only writeback is separate from trusted reviewed memory
5. Remove stray duplicate artifacts like `- Copy.drawio` files instead of leaving ambiguity in `docs/visuals`.

## Checks

- XML sanity: `xmllint --noout <file.drawio>`
- Structural audit: `python3 skills/mno-flowchart-drawio/scripts/drawio_audit.py docs/visuals/*.drawio`
- Canonical inventory: read `docs/visuals/README.md`

## When Labels Need Work

- If a caveman node feels like a paragraph, split it or move details into the engineering page.
- If an engineering node exceeds a quick skim, prefer one main statement plus one short qualifier.
- If a spec says a page should exist but the `.drawio` file does not include it, fix that mismatch first.

## References

- Read `references/diagram-standards.md` for repo-specific conventions.
