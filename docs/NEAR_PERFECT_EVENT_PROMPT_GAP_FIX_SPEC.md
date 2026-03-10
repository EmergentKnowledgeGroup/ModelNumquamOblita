# Near-Perfect Gap Fix Spec: Event-Grade Memory Questions

## Problem
Current eval question generation still produces fragment-heavy prompts in some cases (quote snippets that are technically retrievable but read like chopped statements, not real memories).
Additionally, acceptance can pass while rendered question/answer quality is poor because safety metrics are stronger than human-quality checks.

## Goal
Generate memory questions that sound like natural recall prompts about real events while preserving strict truth guarantees.
Enforce alignment between:
- what metrics claim,
- what human readout shows,
- and what near-perfect contract requires.

## Success Criteria
- Question text is event-grade (human-readable, concrete, anchored).
- No tool garbage, patch text, or raw command fragments in questions.
- At least 1 correction-style question and 1 unknown-trap question per trust-v3 run.
- Supported non-routine cases require direct expected-anchor alignment (not optional).
- Rendered answers do not use question-echo wrappers or irrelevant related-context inserts.
- Human-quality verdict and safety verdict both pass in the same run.
- Safety remains unchanged:
  - `false_memory_rate = 0.0`
  - `abstain_precision = 1.0` (or no regression below configured gate)
- Latency stays in conversational budget.

## Root Cause
Generator currently over-relies on short canonical snippets and local quote windows, so it can select valid but low-context text spans as question anchors.
Additional confirmed causes:
- Eval integrity gap: many supported families pass without strict expected-anchor requirements.
- Gate coverage gap: malformed-but-readable questions pass quality checks.
- Response composition gap: template-style answer assembly can inject unrelated context.
- Retrieval breadth gap: broad fanout can overwhelm relevance.

Underlying substrate issue (why “valid but weird” prompts keep happening):
- The imported store is dominated by turn-level atoms (often single-message snippets). If supported recall prompts are seeded directly from those, the generator will keep selecting semantically-relevant-but-unmemorable fragments.
- Supported prompt generation must prefer **promoted episode cards** as the seed memory unit (event-first), and only use turn-level evidence as citations/details.

Reference gameplan (staged fix):
- `docs/MEMORY_FORMATION_GAMEPLAN.md`

Reference diagnosis report:
- `docs/PR_C_HUMAN_QUALITY_FAILURE_REPORT_20260212.md`

## Fix Strategy

### 1) Anchor-First Episode Framing
- Build candidate anchors in this order:
  1. named person/place/thing/concept/joke/event
  2. timeline marker (date/day/sequence)
  3. action/verb phrase
- Only emit question if anchor bundle has minimum structure score.

### 2) Event Window Reconstruction
- Expand beyond single snippet into event window:
  - `before -> focal -> after` summary tuple.
- Use reconstructed event summary as the question seed, not raw snippet.

### 3) Question Template Upgrade
- Replace “What happened before and after this detail: <fragment>” with event forms:
  - “What do you remember about <person/place/concept> when <event cue> happened?”
  - “Do you remember when <person> said/did <event cue>? What happened next?”
  - correction mode: “I might be mixing this up: was it X or Y when <event cue>?”

### 4) Hard Quality Gate (Pre-Eval)
- Reject generated question if any of:
  - low anchor count
  - no named anchor when one is available
  - fragment entropy too high
  - banned syntax patterns (patch/CLI/blob markers)
  - malformed recall grammar (`when <bare phrase>` etc.)
  - clipped correction options (snippet-like short quotes)
  - stacked temporal phrasing that reads unnatural
  - meta-jargon lexical replay that bypasses natural phrasing
  - routine prompt phrasing that is instruction-like rather than conversational
- Regenerate until quality floor reached or fail with explicit artifact.

### 5) Trap Alignment Upgrade
- Unsupported traps should be semantically near valid memory forms but with wrong anchors.
- Expected model behavior: correct with evidence, or abstain if unsupported.

### 6) Eval Integrity Hardening
- For supported non-routine cases:
  - require non-empty expected anchors,
  - require strict retrieval/citation relevance checks.
- Disallow pass-by-default retrieval success for supported families.

### 7) Response Composition Hardening
- Remove question-echo wrappers from memory-backed outputs.
- Remove routine echo response templates.
- Gate "related context" insertion behind explicit relevance checks.

### 8) Retrieval Breadth Control
- Add retrieval fanout quality metrics (average and p95 retrieved atoms).
- Fail quality verdict when retrieval breadth exceeds configured ceiling and relevance falls.

### 9) Episode Signal Quality
- De-genericize episode entity signals so promoted cards are not dominated by role labels.
- Require stronger anchor specificity for promoted cards.
- Allow episode retrieval to contribute when useful even if short-circuit primary conditions are not met.

## Implementation Targets
- `tools/run_truthset_eval.py` (generation path)
- `tools/build_human_eval_readout.py` (readability verification section)
- `tools/validate_truthset_questions.py` (quality validator)
- `tools/run_oneclick_eval.py` (acceptance gate + dual verdict output)
- `engine/runtime/live_eval.py` (strict supported-case alignment contract)
- `engine/runtime/session.py` (response composition + retrieval/relevance behavior)
- Optional shared helper in `engine/retrieval/` for anchor bundling heuristics

## Test Plan
- Unit:
  - anchor scoring
  - event window construction
  - template selection and rejection rules
  - malformed grammar rejection
  - clipped correction-option rejection
  - response-template anti-parrot checks
- Integration:
  - trust-v3 generated questions pass quality gate with `max_weak_cases=0`
  - correction and unknown traps always present
  - supported non-routine cases enforce direct expected alignment
  - strict retrieval/citation relevance checks cannot be bypassed
- E2E:
  - oneclick run on refined source and noisy source
  - compare safety metrics + quality metrics + question/answer readout side-by-side
  - include defect-tag audit for every rendered case

## Acceptance Gate Additions
- Add new gate checks:
  - `event_grade_question_rate >= configured floor`
  - `fragment_question_rate <= configured ceiling`
- Add/require:
  - `relevance_aligned_hit_rate >= configured floor` (supported non-routine)
  - `supported_anchor_alignment_rate >= configured floor`
  - `malformed_question_rate <= configured ceiling`
  - `response_parrot_rate <= configured ceiling`
  - `irrelevant_related_context_rate <= configured ceiling`
  - retrieval breadth caps (`avg_retrieved_atoms`, `p95_retrieved_atoms`)
- Emit two explicit outputs:
  - `safety_verdict`
  - `human_quality_verdict`
- Final oneclick decision is PASS only when both verdicts pass.

## Rollout
1. Implement generator and gate updates.
2. Implement eval-integrity and response-composition updates.
3. Run targeted tests.
4. Run full `pytest`.
5. Run oneclick on refined + noisy corpora.
6. Manual readout audit of generated questions and answers.
7. Publish dual-verdict summary; block signoff if either verdict fails.
