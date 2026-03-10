# NumquamOblita — Pitch Outline

## Slide 1 — Title
- NumquamOblita: evidence-backed memory for assistants
- “No memory claim without evidence”

## Slide 2 — The trust failure
- Hallucinated recall destroys credibility
- Over-recall during routine chat is annoying and expensive
- Teams need memory that is *auditable*, not magical

## Slide 3 — The core idea
- Separate layers:
  - Evidence atoms (source-backed, immutable provenance)
  - Episode cards (event-grade recall unit)
  - Context package (bounded payload + deterministic guidance)
- External model is *not* trusted as the memory authority

## Slide 4 — End-to-end architecture
- Import archive → build episodes → review/publish → runtime context package → external model → verifier
- Everything is local-first and reproducible

## Slide 5 — What users get
- Wizard UI for non-technical operators
- Runtime UI for audit/management
- “Why this answer?” explainer (evidence, citations, time window)
- Health checks + diagnostic export

## Slide 6 — Safety posture (why it’s trustworthy)
- Fail closed: abstain/clarify when evidence is insufficient
- Verifier enforces citation correctness against delivered evidence set
- Bounded retrieval fanout and bounded evidence payload

## Slide 7 — Differentiation
- Evidence-backed claims + explicit provenance
- Episode-first recall improves naturalness
- Operator control surfaces (disable/undo/audit)

## Slide 8 — Where it’s going
- Safe writeback proposals (OFF by default; approval-required)
- Packaging for easy distribution (one-click run)
- Tight eval gates for “near-perfect” behavior

## Slide 9 — Ask (example)
- Pilot deployments / design partners
- Feedback on operator UX and trust criteria

