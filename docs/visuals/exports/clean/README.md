# Clean Public Diagram Exports

These diagrams are simplified public-facing renders derived from the canonical visual specs. They intentionally bundle dense fan-ins and fan-outs into readable stages instead of preserving every raw draw.io connector.

The public renders include WSS as a strict active project/thread/workstream
scoped continuity helper for active agent work. It attaches only when that scope
gate passes, and its label is intentionally separate from reviewed memory and
evidence paths.

Regenerate them with:

```bash
python tools/export_clean_public_visuals.py
```

## Recommended Public Images

- [Launch Pipeline SVG](mno-launch-pipeline-clean.svg)
- [Launch Pipeline PNG](mno-launch-pipeline-clean.png)
- [Runtime And Integration SVG](mno-runtime-integration-clean.svg)
- [Runtime And Integration PNG](mno-runtime-integration-clean.png)
- [Current Pipeline SVG](mno-current-pipeline-clean.svg)
- [Current Pipeline PNG](mno-current-pipeline-clean.png)
- [Runtime Memory And Decision SVG](mno-runtime-memory-decision-clean.svg)
- [Runtime Memory And Decision PNG](mno-runtime-memory-decision-clean.png)
