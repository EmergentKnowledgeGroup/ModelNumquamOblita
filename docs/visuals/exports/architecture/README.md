# Architecture Diagram Exports

These are engineer-facing architecture renders. They preserve the internal layer shape from the canonical visual specs while avoiding draw.io-style connector overlap.

Use these when someone asks how MNO actually works internally:

- what each layer does
- where trust boundaries live
- how runtime retrieval flows through evidence packaging and verification
- how integration surfaces attach without becoming separate truth contracts
- how WSS `scratchpad_ephemeral` context attaches to strict-scope work-session
  packages without becoming truth
- how source evidence stays traceable through reviewed memory and `context.why`

Regenerate them with:

```bash
python tools/export_architecture_visuals.py --strict
```

## Recommended Architecture Images

- [System Context SVG](mno-architecture-system-context.svg)
- [System Context PNG](mno-architecture-system-context.png)
- [Build Pipeline SVG](mno-architecture-build-pipeline.svg)
- [Build Pipeline PNG](mno-architecture-build-pipeline.png)
- [Runtime Retrieval SVG](mno-architecture-runtime-retrieval.svg)
- [Runtime Retrieval PNG](mno-architecture-runtime-retrieval.png)
- [Memory Trust Boundaries SVG](mno-architecture-memory-trust-boundaries.svg)
- [Memory Trust Boundaries PNG](mno-architecture-memory-trust-boundaries.png)
- [Integration Contract SVG](mno-architecture-integration-contract.svg)
- [Integration Contract PNG](mno-architecture-integration-contract.png)
- [Data Lineage SVG](mno-architecture-data-lineage.svg)
- [Data Lineage PNG](mno-architecture-data-lineage.png)
- [Deployment And Process Model SVG](mno-architecture-deployment-process.svg)
- [Deployment And Process Model PNG](mno-architecture-deployment-process.png)

## Diagram Layers

- `docs/visuals/exports/clean/` is the caveman-friendly public explanation layer.
- `docs/visuals/exports/architecture/` is the engineer-facing architecture layer.
- `docs/visuals/exports/` contains literal page exports from the canonical draw.io files.
