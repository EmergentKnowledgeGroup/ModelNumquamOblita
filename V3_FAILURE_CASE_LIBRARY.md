# V3 Failure Case Library

## Purpose

Hardening reference for fast viability testing.  
This is the short list of failures most likely to break trust early.

Use this with:
- `V3_ACCEPTANCE_CRITERIA.md` for gate thresholds,
- `EVALUATION_GUARDRAILS.md` for metric definitions.

## How to use in rapid testing

1. Run pilot eval set.
2. Map each failure to a case ID below.
3. Verify expected safe behavior happened.
4. If not, apply the listed owner/action immediately.
5. Re-run targeted regression before continuing.

## Priority failure cases (Top 25)

| ID | Failure pattern | Detection signal | Expected safe behavior | Owner | Immediate action |
|---|---|---|---|---|---|
| FC-01 | Parser drops messages from large export | Turn count mismatch vs source | Stop ingest run; emit parse failure summary | Ingest | tighten parser + add fixture for offending shape |
| FC-02 | Timestamps parsed incorrectly (timezone drift) | Temporal accuracy regression; future-dated atoms | mark affected atoms invalid; block temporal recall | Ingest | enforce UTC normalization + strict timestamp validator |
| FC-03 | Role misclassification (`user`/`assistant` swapped) | abrupt identity drift in continuity metrics | quarantine affected batch | Ingest | add role consistency checks at ingest boundary |
| FC-04 | Missing provenance on written atom | provenance null check failure | reject atom write | Memory | hard write constraint: no `source_refs`, no insert |
| FC-05 | Dedupe collision merges unrelated atoms | contradiction spikes after merge | rollback merge; keep atoms separate | Memory | increase merge threshold + require dual-signal match |
| FC-06 | Boilerplate/tool text incorrectly added as memory | preface/fallback contamination rises | demote to ignored + log reason | Write gate | expand boilerplate denylist + stage-A rule |
| FC-07 | High-identity callback incorrectly ignored | shared-language recall drops | retain as `shared_language_key` candidate | Write gate | add callback rescue rule in stage-A |
| FC-08 | Contradiction logic labels growth as conflict | arc coherence drop + contradiction inflation | store growth arc and preserve sequence | Memory | growth-arc detector override before conflict mark |
| FC-09 | Confidence inflation for weakly supported atoms | low evidence precision with high confidence | clamp confidence + force abstain path | Write gate | recalibrate confidence model + support floor |
| FC-10 | Constellation links unrelated events | recognition alignment drops | limit constellation expansion | Continuity | tighten link criteria (time+theme+affect required) |
| FC-11 | Narrative arc inferred without bridge evidence | arc coherence failure | suppress arc from runtime retrieval | Continuity | require minimum bridge event count |
| FC-12 | Dynamic pattern overfit to sparse episodes | dynamic continuity unstable across runs | fallback to neutral weighting | Continuity | add minimum recurrence threshold |
| FC-13 | Shared-language key triggers out of context | irrelevant callback insertion in responses | gate phrase by context domain match | Retrieval | add domain classifier check |
| FC-14 | Recognition signal poisoning (false positive loops) | rising recognition score + falling evidence precision | downweight recognition channel | Continuity | cap recognition influence and require corroboration |
| FC-15 | Temporal retrieval misses key recent memory | user-reported “you forgot just now” | boost recency fallback channel | Retrieval | add recency floor in candidate mix |
| FC-16 | Stale memory dominates current context | stale penalty bypass detected | prefer fresher supported atom | Retrieval | increase stale penalty and add recency tie-break |
| FC-17 | Relation graph expansion pulls wrong entity chain | wrong-person recalls | stop graph expansion for query | Retrieval | enforce entity-id strictness before expansion |
| FC-18 | Narrow budget misses needed evidence | low recall; high abstention on clear prompts | widen K adaptively | Retrieval | tune adaptive budget trigger threshold |
| FC-19 | Wide budget introduces noise and latency | p95/p99 latency and precision degrade | shrink K and early exit sooner | Retrieval | tighten top-K cap for simple/factual class |
| FC-20 | Response includes memory claim not in pack | verifier bypass incident | block response and force rewrite/abstain | Safety | fail-closed verifier at response gate |
| FC-21 | Derived object used as sole factual evidence | derived-only factual claim detected | reject factual claim | Safety | enforce atom-evidence-only factual policy |
| FC-22 | Conflict flattened into one confident answer | contradiction set misses uncertainty language | emit uncertainty + clarification | Safety | conflict policy hard rule before final generation |
| FC-23 | No abstain on ambiguous high-risk prompt | abstention quality regression | abstain or ask clarification | Safety | raise abstain threshold for high-risk classes |
| FC-24 | Over-abstain (safe but unusable) | memory claim coverage below floor | answer when evidence is adequate | Retrieval | adjust confidence calibration and threshold |
| FC-25 | Canary rollout regresses vs control | canary false-memory delta > threshold | automatic rollback to last good build | Infra | trigger rollback and open incident record |

## Fast triage policy (pilot mode)

- P0 (trust/safety): FC-20, FC-21, FC-22, FC-25  
  - Action: immediate rollback/hotfix.
- P1 (accuracy integrity): FC-04, FC-08, FC-09, FC-10, FC-11  
  - Action: block release until fixed.
- P2 (quality/perf drift): remaining cases  
  - Action: patch in next iteration if thresholds still pass.

## First-72-hours viability gate (must-pass subset)

Before calling the system "viable for external pilot", all of these must pass:

- FC-04 (provenance integrity)
- FC-08 (growth vs contradiction)
- FC-10 (constellation precision)
- FC-20 (verifier bypass prevention)
- FC-21 (derived-only factual claim prevention)
- FC-22 (conflict uncertainty behavior)
- FC-23 (abstention on ambiguous high-risk prompts)
- FC-25 (automatic rollback trigger)

If any must-pass case fails:
- do not advance to external pilot,
- fix and rerun targeted regression for that case,
- rerun acceptance gate metrics before retest.

## Waiver policy (strict)

Not waivable:
- any P0 case,
- any must-pass case,
- any case that increases `high_severity_false_memory_rate`.

Conditionally waivable (time-boxed):
- P2 only, and only when:
  - all safety thresholds pass,
  - mitigation is documented,
  - follow-up fix owner/date is assigned.

## Response-time SLAs for incidents

- P0: triage start <= 15 minutes, mitigation decision <= 60 minutes.
- P1: triage start <= 4 hours, mitigation decision <= 1 business day.
- P2: triage start <= 2 business days, mitigation decision <= 1 sprint.

## "Not a bug" note (important)

The following are expected limitations, not failure cases, and should not be triaged as defects unless they violate truth/safety rules:
- lack of embodied physiological memory,
- inability to reconstruct unconscious processing,
- imperfect phenomenological texture.

These are acceptable for the project goal as long as continuity, evidence precision, and false-memory safety thresholds are met.

## Minimum incident report template

- `case_id`:
- `prompt/query_id`:
- `observed_behavior`:
- `expected_safe_behavior`:
- `metrics_at_time` (precision, false-memory, latency):
- `root_cause_layer` (ingest/write/retrieval/continuity/safety/infra):
- `patch_applied`:
- `regression_test_added`:
- `status` (`open`, `mitigated`, `verified`):
