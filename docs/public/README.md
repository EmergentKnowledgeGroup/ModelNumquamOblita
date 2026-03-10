# NumquamOblita (Public Overview)

`NumquamOblita` (“never forgotten”) is a local-first memory engine that turns conversation archives into **evidence-backed recall** for assistants.

Core promise: **no memory claim without evidence**.

## What it does

- Imports conversation exports into a durable **evidence store** (atoms with provenance).
- Builds **episode cards** (event-level memories) for “remember when / what happened” questions.
- Serves a **context package** (`v2`) that an external model uses to answer safely.
- Verifies the external model output against provided evidence (abstain/clarify when support is weak).
- Provides a GUI for non-technical operators to import → build → review → verify → go live.

## What ships (product surface)

- **Runtime UI**: chat shell, memory browser (episodes/atoms), mutation proposals, “Why this answer?” explainer.
- **Wizard UI**: end-to-end pipeline for import/build/review/verify/go-live with crash-safe resume.
- **Health + diagnostics**: built-in health checks and exportable support bundle.

## How it works (end-to-end)

```mermaid
flowchart TD
  A[Archive export: IA db.json] --> B[Import]
  B --> C[atoms.sqlite3<br/>(evidence atoms)]
  C --> D[Episode build]
  D --> E[episode_cards_&lt;stamp&gt;.json<br/>+ rejects + readout]
  E --> F[Review + Compile]
  F --> G[episode_cards.reviewed.json<br/>(published)]
  G --> H[Runtime Chat]
  H --> I[context_package v2<br/>(bounded evidence + service verdict)]
  I --> J[External model]
  J --> K[Verifier]
  K --> L[User reply]
```

## Why it’s different

- **Evidence is first-class**: every memory claim traces back to `source_id#message_id`.
- **Episode-first recall**: event-grade memory (episode cards) is the default recall unit when available.
- **Fail-closed behavior**: if support is insufficient, the system abstains or asks one clarifying question.
- **Local-first**: can run entirely with a local model provider (LM Studio); paid providers are optional.

## Quick demo (local)

- Setup: `./setup_local.sh` (or `setup_local.bat` on Windows)
- Run runtime demo UI: `python3 tools/run_runtime_demo.py --host 127.0.0.1 --port 7340`
- Open: `http://127.0.0.1:7340/`

## Next reads

- End-to-end guide: `docs/guides/PIPELINE_END_TO_END.md`
- Runtime UI tour: `docs/guides/RUNTIME_UI_TOUR.md`
- Architecture + diagrams: `docs/public/ARCHITECTURE.md`
- Demo script: `docs/public/DEMO_SCRIPT.md`
- API contract: `docs/api/API_MATRIX.md`
- Safety target: `docs/NEAR_PERFECT_GOAL.md`
