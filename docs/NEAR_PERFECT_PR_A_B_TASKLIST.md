# Near-Perfect PR A/B/C Tasklist

## Purpose
- Raise evidence quality without losing current safety and speed.
- Keep implementation general (not tuned to one user/export style).
- Prevent metric/readout disconnect by requiring dual-verdict signoff.

## Generalization guardrails (must hold)
- No hard-coded names, phrases, projects, or source-file assumptions.
- Promotion and alignment logic must run only on structural signals:
  - entity density, time anchoring, action verbs, novelty, citation support.
- Add cross-source sanity checks:
  - run same eval pack on both refined input and noisy export input.
- Any quality gain that appears on one corpus but regresses on the other is a fail.

## Baseline (before PR A)
- Capture oneclick baseline from current `main`:
  - `python3 tools/run_oneclick_eval.py --skip-import --store .runtime/imports/atoms.sqlite3 --run-dir runtime/evals/baseline_<stamp> --requested-cases 12 --scan-budget 600000 --batch-size 2 --batch-pause-ms 0 --readout-max-cases 12 --max-weak-question-cases 0`
- Record baseline metrics:
  - decision accuracy, false-memory rate, abstain precision, routine over-recall, citation hit, retrieval hit, latency.

## PR A: Episode Promotion + Query Alignment

### Scope
- Improve episode promotion quality:
  - Promote only concrete event-shaped cards (person/place/thing/action/time).
  - Demote low-information emotional fragments.
- Improve query alignment:
  - Rewrite weak retrieval cues into concrete event cues before lookup.
- Remove remaining overfit hints and keep scoring data-driven.

### Required tests
- Targeted: episode builder + live eval + oneclick integration tests.
- Full suite: `python3 -m pytest -q`.
- Oneclick run on `.runtime/imports/atoms.sqlite3`.

### PR A pass criteria
- `false_memory_rate` stays `0.0`.
- `abstain_precision` stays `1.0`.
- `routine_over_recall_rate` stays `0.0`.
- `citation_hit_rate` and `retrieval_hit_rate` improve or hold (no regression > 0.03).
- weak/garbled question rate reduced vs baseline.

## PR B: Citation Ranking + Acceptance Gate

### Scope
- Rank citations for “best proof of this exact claim.”
- Require at least one direct-support citation for memory-backed answers.
- Add explicit acceptance gate thresholds to oneclick signoff.

### Required tests
- Targeted: citation selection + live eval metrics + oneclick signoff tests.
- Full suite: `python3 -m pytest -q`.
- Oneclick run on `.runtime/imports/atoms.sqlite3` and refined source comparison.

### PR B pass criteria
- Safety metrics unchanged from PR A.
- Citation/retrieval quality above configured gate thresholds.
- Latency remains within current conversational budget.
- acceptance gate blocks merge if weak-question rate or over-recall exceeds threshold.

## PR C: Human-Quality Contract Hardening (mandatory)

### Scope
- Enforce dual-verdict policy:
  - `safety_verdict`
  - `human_quality_verdict`
- Harden eval integrity:
  - supported non-routine cases must require direct expected anchor alignment.
  - remove pass-by-default retrieval success for supported families.
- Harden question quality detection:
  - catch malformed recall grammar,
  - catch clipped correction options,
  - catch instruction-like routine probes.
- Harden response quality:
  - remove question-echo wrapper response formats,
  - remove routine echo template,
  - suppress unrelated related-context inserts.
- Add retrieval-breadth quality controls:
  - monitor and gate on avg/p95 retrieved atoms.

### Required code targets
- `engine/runtime/live_eval.py`
- `engine/runtime/session.py`
- `tools/validate_truthset_questions.py`
- `tools/build_human_eval_readout.py`
- `tools/run_oneclick_eval.py`
- tests:
  - `tests/unit/test_live_eval.py`
  - `tests/unit/test_run_oneclick_eval.py`
  - `tests/integration/test_oneclick_human_readout_tools.py`
  - `tests/integration/test_episode_latency_and_question_quality_tools.py`

### Required tests
- Targeted:
  - quality validator catches malformed/clipped/stilted prompts.
  - eval fails supported case when direct expected alignment is missing.
  - response formatter avoids parrot/echo templates.
  - unrelated related-context insertion is blocked.
- Full suite: `python3 -m pytest -q`.
- Oneclick runs on both corpora with manual Q/A audit.

### PR C pass criteria
- Safety metrics unchanged:
  - `false_memory_rate=0.0`
  - `abstain_precision=1.0`
  - routine over-recall bounded.
- Human-quality metrics pass configured thresholds.
- `safety_verdict=PASS` and `human_quality_verdict=PASS` in same run.
- No critical defects in rendered question/answer audit.
- No "PASS" status claims based only on safety gate output.

## Checkpoint protocol (mandatory)
- Write checkpoint at:
  1. PR A start
  2. PR A post-green tests
  3. PR A open
  4. PR A merge
  5. PR B start
  6. PR B post-green tests
  7. PR B open
  8. PR B merge
  9. PR C start
  10. PR C post-green tests
  11. PR C open
  12. PR C merge
- Command:
  - `python3 tools/context_checkpoint.py --repo-root . snapshot --step "<step>" --note "<note>" --next-cmd "<next command>" --label "<tag>"`
