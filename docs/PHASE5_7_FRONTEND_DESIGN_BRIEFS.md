# Phase 5–7 Frontend Design Briefs (`$frontend-design`)

This file records the required design brief before implementation for each new UI surface.

## Phase 5 — Wizard Conductor
- Purpose / user goal: Guide a non-technical operator from archive import to live runtime without CLI usage, with crash-safe resume.
- Bold aesthetic direction: Editorial operations console with parchment + brass accents, high-contrast section cards, and clear step choreography.
- Memorable differentiator: A “pipeline rail” that always shows stage state (`ready`, `blocked`, `done`) and exactly which artifact path was produced at each step.

## Phase 6 — Memory Workbench + Why Panel
- Purpose / user goal: Let operators inspect, correct, and trust memory behavior directly from runtime UI.
- Bold aesthetic direction: Forensic notebook style with split evidence panes, terse labels, and compact provenance chips.
- Memorable differentiator: One-click “Why this answer?” explainer that toggles citations and opens citation matches in an inline archive viewer.

## Phase 7 — Operations Safety Deck
- Purpose / user goal: Keep live memory updates safe and make deployment diagnostics understandable for non-technical users.
- Bold aesthetic direction: Industrial control deck with safety-first warning hierarchy and explicit OFF-by-default writeback posture.
- Memorable differentiator: A health command center that can export a diagnostics bundle and surface packaging/run commands in the same panel.
