# IA ↔ NO Integration Plan

Status: Implemented baseline (import + runtime usage), constrained by offline-first and no direct IA mutation  
Owner: NumquamOblita Core  
Last Updated: 2026-02-16

This document defines the current integration contract between:
- **IA** (archive export input, `db.json` conversations), and
- **NO** (NumquamOblita import/runtime pipeline).

It is the operator-facing source of truth for what is integrated now, what is intentionally out of scope, and what constraints must not drift.

## 1) Scope and goal

Goal: reliably convert IA conversation export data into provenance-locked NO memory artifacts that drive runtime responses through `context_package v2` and verifier constraints.

In scope:
- IA archive validation + import into NO evidence store.
- Episode build/review/publish flow using imported evidence.
- Runtime retrieval/citation usage from imported evidence and reviewed episodes.

Out of scope (current release):
- Direct writeback into IA source systems.
- Background bidirectional sync with IA.
- Any dependency on cloud-only providers for import/runtime correctness.

## 2) Integration contract (current)

### 2.1 IA input contract

Primary import input is `db.json` with:
- top-level `conversations` array,
- stable conversation ids,
- per-message role + text/content + timestamp where available.

NO supports deterministic normalization/synthesis where needed (for example stable synthetic message ids when absent).

References:
- `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md` (Input contract section)
- `tools/import_ia_db.py`

### 2.2 NO import and artifact outputs

Import path:
1. `POST /api/wizard/import/validate`
2. `POST /api/wizard/import/run` (or CLI equivalent)

Artifacts produced:
- evidence store: `.runtime/imports/atoms.sqlite3`
- import report(s): `.runtime/imports/import_ia_<stamp>.{json,md}`
- wizard state pointers: `runtime/wizard_runs/wizard_<stamp>/wizard_state.json`

### 2.3 Runtime usage after import

Imported evidence is used by:
- episode builder (`tools/build_episode_cards.py`) for draft episodes/rejects/readout,
- review/compile to publish `runtime/episodes/episode_cards.reviewed.json`,
- runtime retrieval/context package flow (`context_package v2`) and verifier-gated chat responses.

## 3) Constraints (non-negotiable)

1. **Offline-first correctness**  
   Import, retrieval, and runtime decisioning must work locally without a cloud dependency.

2. **Provenance lock**  
   PASS memory claims must be traceable to import evidence (`source_id#message_id` citation contract).

3. **No destructive source mutation**  
   NO does not modify IA source exports/systems. Runtime memory edits are NO-side state controls, not IA writes.

4. **Deterministic ingest semantics**  
   ID synthesis/normalization must be stable across repeated imports of unchanged input.

5. **Bounded retrieval behavior**  
   Runtime retrieval fanout remains bounded; broad unrelated retrieval is treated as quality failure in evals.

## 4) Operator verification checklist

Use this checklist to validate IA ↔ NO integration on a fresh archive:

- Validate import payload in wizard (`/api/wizard/import/validate`).
- Run import and confirm `.runtime/imports/atoms.sqlite3` exists.
- Build episodes and verify draft + rejects + readout artifacts are produced.
- Compile reviewed episodes and confirm published reviewed set exists.
- Run verify stage and confirm actionable checks are safe before go-live.
- Run a known supported recall prompt and confirm citations resolve through `/api/archive/citation/<token>`.

## 5) Known limitations

- Optional external provider choices (for responder model calls) are runtime/provider concerns, not IA integration dependencies.
- Integration currently assumes archive pull/export has already happened outside NO; NO consumes the export artifact.
- Any future IA direct-sync feature must ship behind an explicit separate contract doc and must preserve current provenance/safety guarantees.
