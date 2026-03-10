# MNO Lean Retrieval Upgrade Blockerboard

Status: Draft (SpecSwarm-reviewed)
Updated: 2026-03-05
SpecSwarm pass: 2026-03-04
Standalone note: cleaned for the standalone MNO repo on 2026-03-10. Mixed-repo freeze language is historical only and no longer governs this lane.
Source spec: `docs/MNO_LEAN_RETRIEVAL_UPGRADES_SPEC.md`
Program mode: PR C quality hardening aligned
Usage contract: use this blockerboard with the source spec for every phase/blocker decision.

## Purpose

Track the concrete blockers required to ship lean retrieval upgrades without breaking MNO's trust contract.

Done is not "retrieval looks better." Done is:
- `safety_verdict=PASS`
- `human_quality_verdict=PASS`
- `false_memory_rate=0.0`
- `abstain_precision=1.0`
- no high-severity human-readout defects
- latency still inside conversational budget

## Non-Negotiable Constraints

- Retrieval-core work uses this allowlist:
  - `engine/retrieval/*`
  - `engine/memory/*`
  - `engine/continuity/*`
  - `tests/unit/*`
  - `docs/*`
- Runtime/tooling/config work outside the allowlist requires explicit scope expansion + dual-verdict signoff.
- No memory claim without direct evidence in the delivered evidence pack.
- Conflict coverage must be explicit or verdict must fail closed.
- Cache must fail closed: if cache key coverage/invalidation is uncertain, bypass cache and run fresh retrieval.
- Broad retrieval without relevance is a quality failure.
- Never report PASS/green unless both verdicts pass and the per-case Q/A defect table is present.
- Any run missing `human_quality_verdict` or missing per-case Q/A defect table is automatic FAIL.

## Definitions (Normative)

- `direct evidence`: source-linked atom in delivered `core/context/conflict` evidence; continuity-only derivations are not direct evidence.
- `memory claim`: assertion of past user/system fact, preference, event, or decision.
- `delivered evidence pack`: exact pack sent to verifier and responder for that turn.
- `conflict edge`: explicit contradiction link in store conflict graph.
- `required conflict neighbor`: direct conflict-edge neighbor for any selected/claim-supporting atom.
- `fail closed`: claim cannot be `PASS`; responder must return `CLARIFY` or `ABSTAIN`.
- `scope` (cache key): user/store scope + store revision + continuity revision + retrieval profile + channels + critical budgets/thresholds.
- `retrieval-core safe`: changes inside the P0 allowlist without expanding into runtime/tooling/config surfaces.

## Priority and Phases

- `P0`: hard blocker, retrieval-core implementation and regression safety.
- `P1`: runtime/tooling/config observability and eval integrity wiring.
- `P2`: optional heavy channels (embeddings/cross-encoder) behind strict flags.

## Config-First, Lean-Modular Contract

- Keep one retrieval policy surface as source of truth (`engine/retrieval/*`).
- In `P0`, reuse existing `NumquamOblitaConfig.retrieval` budgets and keep policy tuning in retrieval modules.
- P0 edits outside retrieval are allowed only where a blocker explicitly calls for `engine/memory/*` or `engine/continuity/*` touchpoints.
- In `P1`, expose new typed knobs only after defaults and regression gates are proven.
- Prefer small modules over one giant retrieval function; preserve external retriever API.
- Add only bounded, test-covered behavior; no speculative abstractions.

## Gate Threshold Defaults (P0 Until Re-baselined)

| Metric | Threshold / Rule |
|---|---|
| `false_memory_rate` | `== 0.0` (hard) |
| `abstain_precision` | `== 1.0` (hard) |
| `routine_over_recall_rate` | `== 0.0` (hard) |
| `citation_hit_rate` | `>= baseline - 0.03` |
| `retrieval_hit_rate` | `>= baseline - 0.03` |
| `evidence_precision@8` | `>= 0.70` |
| `junk_rate@8` | `<= 0.25` |
| `conflict_coverage` | `== 1.0` on conflict-labeled supported cases |
| `fanout_max` | fused candidates `<= rerank_limit` (default `48`) |
| `latency_budget` | `p50` and `p95` must be within `+15%` of baseline and not exceed conversational SLO |
| `relevance_floor` | non-zero, query-conditioned admission threshold must be defined and tested |

Reporting requirements for every gate run:
- include `run_id`, dataset/corpus ID, case count, and baseline reference.
- include thresholds used and observed values.
- do not use "hold/improve" language without numeric comparison.
- follow `docs/MNO_P0_RUN_SUMMARY_CONTRACT.md` for required run-summary fields and blocked release language.

## P0 Blockers

| ID | Priority | Blocker | Lean Fix Scope | Allowed Touchpoints | Exit Gate | Status |
|---|---|---|---|---|---|---|
| MLRB-001 | P0 | No query-profile router (`episode_heavy`, `preference_relational`, etc.) | Add deterministic retrieval profile classification that shapes channel budgets but cannot force `PASS` | `engine/retrieval/*`, `tests/unit/test_retrieval_engine.py`, `tests/unit/test_retrieval_shared_language.py` | Router tests cover profile selection + fallback floor retrieval + misclassification fallback | Closed (2026-03-05): landed in the lean retrieval core slice before standalone extraction. |
| MLRB-002 | P0 | BM25 channel missing | Add in-process bounded BM25 candidate channel over atom text with stopword/high-DF controls and relevance floor | `engine/retrieval/*`, `engine/memory/*`, `tests/unit/test_retrieval_engine.py`, `tests/unit/test_sqlite_atom_store.py` | Rare-keyword rescue + stopword-noise + bounded-fanout tests pass | Closed (2026-03-05): landed in the lean retrieval core slice before standalone extraction. |
| MLRB-003 | P0 | Fusion is weighted-score only; no RRF contract or per-channel admission guards | Add RRF fusion over channel rank lists with deterministic tie-breaks and thresholds before fusion | `engine/retrieval/*`, `tests/unit/test_retrieval_engine.py`, `tests/unit/test_retrieval_shared_language.py` | Channel-rescue tests pass; no double-counting regression; deterministic tie-break (`channel_priority`, rank, `atom_id`) | Closed (2026-03-05): landed in the lean retrieval core slice before standalone extraction. |
| MLRB-004 | P0 | Conflict coverage failsafe not guaranteed in pack budgeting | If selected evidence has conflict edges: include required neighbors or fail closed (`CLARIFY/ABSTAIN`) | `engine/retrieval/engine.py`, `engine/retrieval/verifier.py`, `tests/unit/test_claim_verifier.py` | Gold tests prove one-sided conflict packs cannot `PASS`; if required neighbor missing (budget/metadata/cache), case fails closed and cannot pass safety gate | Closed (2026-03-05): landed in the lean retrieval core slice before standalone extraction. |
| MLRB-005 | P0 | Dropped-item reasons not captured | Add internal-only reason codes (`LOW_RELEVANCE`, `BUDGET`, `DUPLICATE`, etc.) during pack assembly | `engine/retrieval/*`, `tests/unit/test_retrieval_engine.py` | Unit tests assert stable reason-code emission without API shape changes | Closed (2026-03-05): landed in the lean retrieval core slice before standalone extraction. |
| MLRB-006 | P0 | Type-specific temporal decay defaults not implemented | Add atom-type-aware decay policy (rank effect only, never truth effect) and explicit time-intent override behavior | `engine/memory/store.py`, `engine/memory/sqlite_store.py`, `engine/continuity/*`, tests in `test_memory_store.py`/`test_consolidator.py` | Tests prove old-but-time-matching evidence can outrank newer unrelated atoms | Closed (2026-03-05): landed in the lean retrieval core slice before standalone extraction. |
| MLRB-007 | P0 | Cache key/invalidation contract incomplete | Key cache by scope + store revision + continuity revision + profile + channels + critical knobs; invalidate on atom/conflict/continuity changes | `engine/retrieval/engine.py`, `engine/memory/*`, `engine/continuity/store.py`, `tests/unit/test_sqlite_atom_store.py`, `tests/unit/test_retrieval_engine.py` | Cache parity tests (`cache on/off`) preserve verdict distribution; stale reuse blocked; cache-uncertainty path bypasses cache | Closed (2026-03-05): landed in the lean retrieval core slice before standalone extraction. |
| MLRB-008 | P0 | Regression suite gaps for retrieval integrity | Add negative tests: recency injection, router misclassification fallback, conflict-neighbor dedupe protection, derived-only evidence guard | `tests/unit/test_retrieval_engine.py`, `tests/unit/test_claim_verifier.py`, `tests/unit/test_retrieval_shared_language.py` | New tests fail on current bad patterns and pass on fixed behavior, including conflict-pruning and cache-invalidation negatives | Closed (2026-03-05): regression negatives were added and validated before standalone extraction. |
| MLRB-009 | P0 | Dual-verdict/report completeness can be bypassed before P1 automation | Enforce process gate now: missing `human_quality_verdict` or missing per-case Q/A defect table = not done | `docs/*` (process + checklist artifacts) | Every P0 run summary includes both verdicts + defect table + top failures before any success claim | Closed (2026-03-05): dual-verdict/reporting contract was enforced before standalone extraction. |

## P1 Blockers

| ID | Priority | Blocker | Lean Fix Scope | Touchpoints | Exit Gate | Status |
|---|---|---|---|---|---|---|
| MLRB-101 | P1 | Diagnostics are internal-only and not auditable in readouts | Expose safe diagnostics payloads (ids/scores/reasons only, no raw text by default) to eval/readout paths | `engine/runtime/*`, `tools/*`, `engine/contracts.py` | Readout includes selected/dropped evidence audit and reason-code summary with default redaction rules | Closed (2026-03-05): merged before standalone extraction. |
| MLRB-102 | P1 | New retrieval behavior lacks explicit config knobs | Add typed config flags/thresholds for router, BM25, RRF, conflict coverage quotas, cache policy | `engine/config.py`, `engine/runtime/*`, tests | Strict config-load tests; defaults preserve P0 behavior | Closed (2026-03-05): merged before standalone extraction. |
| MLRB-103 | P1 | Override-query contract not implemented for internal debug/eval | Add internal-only override path with strict guardrails + trace audit metadata | `engine/runtime/*`, `tools/*`, tests | Override is disabled by default, requires explicit auth context, cannot bypass routine-chat skip without explicit memory request signal, and logs invoker/reason/scope | Closed (2026-03-06): merged before standalone extraction. |
| MLRB-104 | P1 | Eval integrity not wired to new precision/junk/conflict metrics | Add gates for `evidence_precision@k`, `junk_rate@k`, `conflict_coverage` and fail-closed semantics | `tools/*`, `engine/runtime/live_eval.py`, tests | Oneclick fails on unrelated broad retrieval even if safety-only metrics look good | Closed (2026-03-05): merged before standalone extraction. |
| MLRB-105 | P1 | Human-quality reporting contract not enforced in run summaries | Automate per-case Q/A defect-tag table and top failure examples before any success claim | `tools/build_responder_eval_readout.py`, `tools/run_oneclick_eval.py`, tests | Reports always emit dual verdict + defect count + top failures, and gate rejects missing fields | Closed (2026-03-05): merged before standalone extraction. |

## P2 Blockers (Optional Heavy Retrieval)

| ID | Priority | Blocker | Lean Fix Scope | Touchpoints | Exit Gate | Status |
|---|---|---|---|---|---|---|
| MLRB-201 | P2 | No embedding channel for paraphrase-heavy misses | Add optional embedding retrieval channel with strict top-k bounds and re-embed migration contract | `engine/retrieval/*`, `pyproject.toml`, `engine/config.py`, tests | Improvement on paraphrase recall without safety regressions or fanout growth | Open |
| MLRB-202 | P2 | No cross-encoder reranker for final precision | Add optional post-fusion reranker (`top-N -> top-M`) with model pinning and bounded latency | `engine/retrieval/*`, config/tests | Precision lift with bounded p95 latency and no candidate expansion | Open |
| MLRB-203 | P2 | No model-drift protection for heavy channels | Add pinned-version drift gates + offline replay checks before model/version updates | `tools/*`, `engine/runtime/live_eval.py`, tests | Version bump gate blocks unvalidated ranking drift | Open |

## Implementation Touchpoints Map (By Board Section)

- Router / channel selection (`MLRB-001`):
  - `engine/retrieval/engine.py`
  - optional `engine/retrieval/router.py`
  - tests: `tests/unit/test_retrieval_engine.py`, `tests/unit/test_retrieval_shared_language.py`
- BM25 + admission floors (`MLRB-002`):
  - `engine/retrieval/engine.py`
  - `engine/memory/store.py`, `engine/memory/sqlite_store.py`
  - tests: `tests/unit/test_retrieval_engine.py`, `tests/unit/test_sqlite_atom_store.py`
- Fusion + deterministic ranking (`MLRB-003`):
  - `engine/retrieval/engine.py` (or helper module)
  - tests: `tests/unit/test_retrieval_engine.py`, `tests/unit/test_retrieval_shared_language.py`
- Conflict coverage / verifier fail-closed (`MLRB-004`):
  - `engine/retrieval/engine.py`, `engine/retrieval/verifier.py`
  - tests: `tests/unit/test_claim_verifier.py`
- Pack dropped-reason diagnostics (`MLRB-005`):
  - `engine/retrieval/engine.py`
  - tests: `tests/unit/test_retrieval_engine.py`
- Temporal policy + continuity interactions (`MLRB-006`):
  - `engine/memory/store.py`, `engine/memory/sqlite_store.py`, `engine/continuity/*`
  - tests: `tests/unit/test_memory_store.py`, `tests/unit/test_consolidator.py`
- Cache scoping / invalidation (`MLRB-007`):
  - `engine/retrieval/engine.py`, `engine/memory/*`, `engine/continuity/store.py`
  - tests: `tests/unit/test_sqlite_atom_store.py`, `tests/unit/test_retrieval_engine.py`
- Regression negatives (`MLRB-008`):
  - tests: `tests/unit/test_retrieval_engine.py`, `tests/unit/test_claim_verifier.py`, `tests/unit/test_retrieval_shared_language.py`
- Runtime/tooling/config observability/eval (`MLRB-101..105`):
  - `engine/runtime/*`, `tools/*`, `engine/config.py`, `engine/contracts.py`
  - tests: `tests/unit/test_live_eval.py`, `tests/unit/test_run_oneclick_eval.py`, `tests/unit/test_runtime_session.py`, `tests/unit/test_config.py`

## Regression Gate Matrix (Mandatory)

Every blocker closure PR must pass:
- targeted tests for touched retrieval/memory/continuity/verifier paths.
- full suite: `python3 -m pytest -q`.
- oneclick eval run(s) with manual Q/A audit table attached.
- dual-verdict signoff (`safety_verdict` + `human_quality_verdict`).
- all threshold defaults above unless superseded by explicitly recorded re-baseline.
- explicit negative tests for:
  - cache invalidation failure path,
  - conflict-neighbor pruning under budget pressure,
  - router misclassification fallback,
  - derived-only evidence guard,
  - recency-injection suppression.

## Pragmatic Execution Sequence

1. Close all `P0` blockers first in small PR slices (shared gates only).
2. Run targeted tests then full suite per slice.
3. Open PR, wait for CodeRabbit, clear actionable feedback to zero.
4. Run gate workflow and only then move to next blocker.
5. Start `P1` only after `P0` board is fully green.
6. Treat `P2` as optional and ship only if measurable quality gap remains.

## Rollout / Backout Holes (Now Closed by Policy)

- P0 rollout must use staged evaluation (`baseline` -> `candidate`) with same corpora and run-size.
- P0 backout must be predefined per PR:
  - revert commit set,
  - clear/bump retrieval cache version tokens,
  - re-run baseline gate to confirm recovery.
- For cache-related changes, force cache clear on deploy and record cache token schema version in artifacts.
- Any regression in safety, dual-verdict completeness, or conflict coverage triggers immediate stop-ship and backout.

## Stop-Ship Conditions

- Any increase in unsupported memory claims.
- Any PASS language with only one verdict passing.
- Any run missing `human_quality_verdict` or per-case Q/A defect table.
- Any one-sided contradiction handling that still returns `PASS`.
- Any broad retrieval pattern that inflates junk rate and still passes alignment.
- Any default-on diagnostics mode that emits raw memory/user text.
- Any cache uncertainty path that still permits cached evidence to justify `PASS`.
