# NumquamOblita — One Pager

## Problem
Assistants either forget everything or “remember” confidently without support. Both break trust.

## Solution
`NumquamOblita` is a local-first memory pipeline that only allows memory claims that are **traceable to evidence**.

## Product surfaces
- **Wizard UI**: import → build episodes → curate → review → verify → go live (crash-safe resume)
- **Runtime UI**: chat + memory management (episodes/atoms) + “Why this answer?” explainer
- **Health + diagnostics**: run checks and export a support bundle

## How it works (short)
1. Import archive → durable evidence atoms (sqlite).
2. Build episode cards (event-level memories) + rejects/readout artifacts.
3. Review/compile reviewed set (published episodes used at runtime).
4. Runtime builds `context_package v2` (bounded evidence + service verdict).
5. External model answers; verifier checks citations/support and fails closed.

## Differentiators
- **No memory claim without evidence** (strict citation token format: `source_id#message_id`)
- **Episode-first recall** (events, not snippets)
- **Verified output** (post-model verifier enforces support/abstain)
- **Local-first by default** (LM Studio supported; cloud optional)

## Who it’s for
- Builders shipping assistants that must be trustworthy
- Operators who need a GUI to audit and correct memory behavior
- Teams that want reproducible evals and strict acceptance gates

## Links
- Overview: `docs/public/README.md`
- End-to-end guide: `docs/guides/PIPELINE_END_TO_END.md`

