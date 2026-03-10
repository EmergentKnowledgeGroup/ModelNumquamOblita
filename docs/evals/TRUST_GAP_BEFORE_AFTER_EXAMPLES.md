# Trust Gap Remediation — Before/After Clarify Examples (Final Push)

Date: 2026-02-20  
Scope: Final trust-gap remediation pass only (`ARCHIVIST_TRUST_GAP_REMEDIATION_SPEC`), using one representative query per corpus band.

## Source artifacts

- Transition matrix (official before/after decision flips):
  - `runtime/evals/document_research/trust_gap_transition_eval_20260220T111002Z/trust_gap_transition_eval_report.json`
- Trust-pack validation:
  - `runtime/evals/document_research/trust_gap_remediation_eval_20260220T110907Z/trust_gap_remediation_eval_report.json`
- Corpus runs (post-remediation):
  - `runtime/evals/document_research/wikipedia_dump_eval_20260220T110257Z/wikipedia_dump_eval_report.json`
  - `runtime/evals/document_research/wikipedia_dump_eval_20260220T110403Z/wikipedia_dump_eval_report.json`
  - `runtime/evals/document_research/wikipedia_dump_eval_20260220T110552Z/wikipedia_dump_eval_report.json`

## Method note

The transition artifact stores decision/warning deltas, not full answer text.  
So full “before answer” text below is reconstructed via controlled replay on the same corpus/settings by temporarily bypassing trust gates; full “after answer” text is from the current trust-hardened behavior.

---

## 140k band example

- Query: `What does Wikipedia say about Astatine?`
- Transition artifact status: `SUPPORTED -> CLARIFY`

### Before (pre-trust behavior style)

- Decision: `SUPPORTED`
- Example answer text:
  - `Supported evidence found:`
  - `- ... Astatine is only produced in minuscule quantities ...`
  - `- ... Astatine may form bonds to the other chalcogens ...`
  - `- ... diatomic molecules ... astatine and tennessine ...`
- Citations: 3

### After (trust-hardened)

- Decision: `CLARIFY`
- Clarify response text:
  - `I found low-alignment evidence for this wording. Please narrow the request with exact terms, document scope, or date range.`
- Citations: none
- Trigger: `low_query_evidence_overlap:1/4`

---

## 260k band example

- Query: `What does Wikipedia say about Wikipedia:Adding Wikipedia articles to Nupedia?`
- Transition artifact status: `SUPPORTED -> CLARIFY`

### Before (pre-trust behavior style)

- Decision: `SUPPORTED`
- Example answer text:
  - `Supported evidence found:`
  - `- ... Founding of Wikipedia ... Nupedia wiki-style workflow ...`
  - `- ... In March 2000, the Nupedia project was started ...`
  - `- ... third snippet was topically adjacent but not clearly on-target ...`
- Citations: 3

### After (trust-hardened)

- Decision: `CLARIFY`
- Clarify response text:
  - `I found evidence, but it does not align cleanly with the named entity or topic in your query. Please clarify the exact person, place, or project.`
- Citations: none
- Trigger: `entity_anchor_mismatch:1/2`

---

## 340k band example

- Query: `Summarize dependable facts for Albert Gore with citations.`
- Transition artifact status: `SUPPORTED -> CLARIFY`

### Before (pre-trust behavior style)

- Decision: `SUPPORTED`
- Example answer text:
  - `Supported evidence found:`
  - `- ... generic "Albert" disambiguation content ...`
  - `- ... Albert III ...`
  - `- ... Albert I ...`
- Citations: 3

### After (trust-hardened)

- Decision: `CLARIFY`
- Clarify response text:
  - `I found low-alignment evidence for this wording. Please narrow the request with exact terms, document scope, or date range.`
- Citations: none
- Trigger: `low_query_evidence_overlap:1/6`

---

## What changed at system level (plain-language)

- Before: the system often gave a confident answer when evidence was only “nearby.”
- After: the system now refuses to over-claim and asks for clarification when entity/topic alignment is weak.
- Net effect in transition report:
  - 140k: `107` `SUPPORTED -> CLARIFY`, `3` opposite
  - 260k: `101` `SUPPORTED -> CLARIFY`, `3` opposite
  - 340k: `107` `SUPPORTED -> CLARIFY`, `5` opposite
- Citation integrity stayed clean: unresolved citations remained `0` in all bands.
