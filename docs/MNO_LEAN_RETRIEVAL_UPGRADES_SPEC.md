# MNO Lean Retrieval + Verification Upgrades (Borrowed From HippocampAI)

Version: 2026-03-04 (design-only)
Status: Draft
Standalone note: imported into the standalone MNO repo on 2026-03-10. Historical mixed-repo freeze language is superseded by the standalone boundary rule below.
Execution companion: `docs/MNO_LEAN_RETRIEVAL_BLOCKERBOARD.md` (phase/blocker tracker)

## 0. What This Is

This is a build/design spec (high-level only) for upgrading **NumquamOblita (MNO)** using a few proven ideas seen in HippocampAI, while keeping MNO:
- lean (few moving parts),
- bounded (predictable latency),
- verifiable (no evidence, no claim),
- near-perfect on false recall (target: 0 hallucinated *memories*).

This spec does **not** include implementation details (no function-level code plans). Codex will do the “how and where” later.

## 0.1 Definitions (Normative Terms)

These terms are used in a strict way in this spec:
- Memory claim: a statement that asserts recall about the past (preferences, events, facts) as true.
- Evidence item: one atom (or episode card) included in the delivered evidence pack for a turn.
- Delivered evidence pack: the exact evidence list the responder is allowed to use and the verifier will check against.
- Aligned evidence: evidence items that are actually about the query’s topic/entities/time intent (not just vaguely related).
- Contradiction: two atoms that are explicitly linked as conflicting (conflict edge/graph), not an LLM “guess”.
- Contradiction neighbor: an atom that is directly connected to another atom via a conflict edge.
- Routine chat: turn that should not use long-term memory retrieval (smalltalk/banter, no memory request).
- Explicit memory request signal: a user turn that clearly asks for “remember/recall/previously/last time/what did we decide”.
- Store revision token: a value that changes whenever the store state changes in a way that affects retrieval.

## 0.2 Standalone Boundary Rule (No Cross-Plumbing Reintroduction)

This standalone repo already excludes the removed document-research/add-on lane. Lean retrieval work should stay inside the MNO retrieval/memory/continuity/runtime surfaces that remain in this repo.

### 0.2.1 Retrieval-Core Safe File Zones

Retrieval-core work is allowed to modify only:
- `engine/retrieval/*`
- `engine/memory/*`
- `engine/continuity/*`
- `engine/write_gate/*` (only if needed for safety regressions; otherwise avoid)
- `tests/unit/*` (MNO-focused unit tests only)
- `docs/*` (this spec + related docs)

### 0.2.2 Standalone Boundary Constraints

To keep the standalone lane clean:
- Do not add new dependencies or optional deps (no `pyproject.toml` edits).
- Do not add new API fields or response shapes (no adapters/server edits).
- Do not add new top-level config knobs (no `engine/config.py` edits).
- Do not change shared dataclass contracts used across runtime boundaries (no `engine/contracts.py` edits).
- Keep diagnostics internal-only until the runtime/tooling phase explicitly needs them.

## 1. Background (Why Upgrade)

MNO’s core advantage is the *trust contract*:
- evidence-first atoms,
- bounded retrieval,
- `PASS|CLARIFY|ABSTAIN|NO_MEMORY` verdicts,
- verifier + reply contract enforcement.

MNO’s current baseline retrieval is intentionally simple and deterministic (lexical + char n-gram proxy + temporal + graph/continuity signals). This is safe, but retrieval quality (especially paraphrase matching and “needle in haystack” recall) can be improved without changing the trust contract.

HippocampAI already implements a strong modern retrieval stack:
- BM25 keyword retrieval,
- embedding retrieval into a vector DB,
- Reciprocal Rank Fusion (RRF) to fuse channels,
- optional cross-encoder reranking,
- context assembly with token budgeting and dropped-item reasons.

We want the **benefits**, without importing HippocampAI’s large platform footprint or weakening MNO’s proof rules.

## 2. Goals / Non-Goals

### Hard goals (must hold)
- **No memory claim without evidence** remains absolute.
- Retrieval remains **budget-bounded** (top-K per channel, fixed rerank limits).
- Service verdict remains authoritative and **fail-closed**.
- Conflicts remain preserved (no “newest wins” deletion by default).
- Changes must not create a path where unrelated retrieval can pass the gates.
- Phase 0 implementations must respect the standalone boundary rule in section 0.2.

### Soft goals (strongly preferred)
- Better recall under paraphrase and noisy queries.
- Less “junk retrieval” (higher precision at k).
- Better operator debuggability (why picked, why dropped).
- Minimal new dependencies by default; heavier features gated behind flags/extras.

### Non-goals (explicitly out of scope)
- Building a full SaaS platform (Redis/Celery/Postgres/Qdrant clusters).
- Automatic conflict resolution that deletes history.
- LLM-based “auto-merge” that becomes truth.
- Changing the write-gate policy (beyond small scoring/half-life tuning).
- Mixing in “archivist/document research” features.

## 3. Design Pillars (Do Not Break These)

1. **Evidence is authority**: ranking can be fancy; evidence must remain source-linked.
2. **Retrieval helps find evidence; it does not justify claims.** Only the verifier/verdict can do that.
3. **Small packs beat big packs**: if we can answer with 6–12 items, do not send 40.
4. **If unsure, ask or abstain**: better to be safe than “smart”.

## 4. Proposed Upgrades (Big Wins, Low Complexity)

### 4.1 Query Router (Search Fewer Piles)

**Idea borrowed:** HippocampAI routes queries to different collections (facts vs prefs). We do the same conceptually.

**High-level behavior**
- Given a user turn (and optionally a retrieval override query), classify into a retrieval profile:
  - `episode_heavy` (remember-when / what happened),
  - `preference_relational` (likes, dislikes, relationships),
  - `procedural` (how-to, steps),
  - `factual` (stable facts),
  - `mixed`.
- Router outputs:
  - which atom types to prioritize,
  - which retrieval channels to run (see 4.2–4.3),
  - channel budgets (top-Ks),
  - Phase 0: only shapes retrieval once LTM retrieval is already invoked (no runtime gating changes),
  - Runtime/tooling: may influence “do we even query LTM” decisions (still respecting routine-chat skip rules).

**Safety constraints**
- Router can only reduce/shape search; it cannot force `PASS`.
- Any routing that reduces search must preserve a safe “failsafe floor”:
  - it means “still run a minimal relevance-gated baseline retrieval (lexical/BM25),”
  - it does not mean “inject something so the pack is non-empty,”
  - the minimal baseline retrieval may return empty, and that is acceptable.
- Retrieval override query semantics (runtime/tooling; optional) must be strict:
  - override query MUST NOT be user-provided text,
  - override query is accepted only via internal debug/eval interfaces behind a flag,
  - override query MUST NOT change routine-chat skip behavior unless an explicit memory request signal is present,
  - override usage must be auditable in traces (who/what set it; may require runtime trace plumbing).
- Phase 0: do not expose or rely on any override query interface (no runtime/tools changes). Keep it disabled.

**Why it helps**
- Less irrelevant retrieval = fewer chances to accidentally support the wrong thing.
- Lower cost/latency by avoiding unnecessary channels.

**Phase 0 (retrieval-core safe) note**
- Do not modify `engine/runtime/*`. Implement routing as an internal retrieval profile inside `engine/retrieval/*`.
- Any routing behavior that requires runtime/server/adapters/tooling support is runtime/tooling.

### 4.1.1 Conflict Coverage Failsafe (Do Not Hide Contradictions)

Routing and filtering can accidentally “hide” contradictions if they are too aggressive.

**Hard rule**
- Trigger: if any selected candidate/evidence item has an explicit conflict edge, conflict coverage is required.
- Required behavior:
  - the pack builder must reserve slots to include up to N directly-conflicting atoms, or
  - the service verdict must fail closed (`CLARIFY`/`ABSTAIN`) if required conflict coverage cannot fit budget.
- Do not infer contradictions via LLM semantics in this phase; use explicit conflict graph/edges only.

This rule exists to prevent “one-sided evidence packs” from producing confident memory claims.

### 4.2 Add a BM25 Keyword Retrieval Channel (Lean Version)

**Idea borrowed:** HippocampAI runs BM25 in parallel with embeddings.

**High-level behavior**
- Build a keyword index over atom `canonical_text` (and optionally light metadata like entities/topics).
- For each query, compute BM25 scores and return top-K candidate atom ids.

**Lean constraint**
- Must be in-process and bounded.
- Must have a clean invalidation story when the store changes.

**Phase 0 (retrieval-core safe) note**
- Do not introduce new config keys for BM25 during Phase 0 (no `engine/config.py` edits).
- Use existing retrieval budgets for initial constraints (top-k + rerank limits) and tune later runtime/tooling.

**Quality guardrails**
- Tokenization must downweight or ignore very common terms (stopwords / high document-frequency tokens).
- BM25 results should be query-conditioned and must include a minimum relevance floor (to avoid “junk by recency/common tokens”).
- If BM25 is built over multiple fields, field weighting must be conservative (text > metadata).

**Safety constraints**
- BM25 only proposes candidates; pack-building + verifier still gate final claims.

**Why it helps**
- Great for “exact-ish” user wording and rare keywords (names, inside terms).
- Complements semantic-ish channels; improves hit rate without requiring embeddings.

### 4.3 Fuse Channels With Reciprocal Rank Fusion (RRF)

**Idea borrowed:** HippocampAI uses RRF to fuse rankings from multiple retrieval signals.

**High-level behavior**
- Each channel produces a ranked list (query-conditioned):
  - existing lexical,
  - existing n-gram semantic proxy,
  - graph/continuity expansion (bounded),
  - new BM25,
  - (later: embeddings).
- Temporal relevance is not a standalone “global recency channel”:
  - it may rerank already-relevant candidates,
  - it must not inject unrelated “most recent” items into fusion.
- RRF fuses these ranked lists into one final ranked candidate list, before pack-building.

**Safety constraints**
- Keep top-K per channel small.
- Keep fused candidate list capped (existing rerank limit still applies).
- Add fusion guardrails:
  - per-channel admission thresholds (filter before ranking; don’t fuse garbage),
  - downweight low-precision channels (continuity expansions) vs high-precision (lexical/BM25),
  - RRF is rank-based: do not mix raw channel score scales into fusion without an explicit, tested normalization rule,
  - deterministic tie-breaking so evals remain reproducible.

**Spec note (avoid double-weighting)**
- The repo already has a weighted scoring formula for candidates. Implementers must avoid “double counting” (e.g., RRF + reapplying the same weights again) unless explicitly validated in evals.

**Why it helps**
- Prevents one channel from dominating.
- Increases robustness: if one channel fails, another can rescue recall.

### 4.4 Context Pack Budgeting + Dropped-Item Reasons (Debuggability)

**Idea borrowed:** HippocampAI’s context assembly tracks what was selected vs dropped and why.

**High-level behavior**
- When building the `MemoryPack` / evidence list:
  - keep a strict budget (items + rough token budget),
  - track dropped candidates with reason codes:
    - `LOW_RELEVANCE`, `DUPLICATE`, `BUDGET`, `EXPIRED/ARCHIVED`, `FILTERED_BY_TYPE`, `CONFLICT_REQUIRED_BUT_DROPPED`, etc.
- Expose these in diagnostics (not user-facing by default):
  - runtime telemetry,
  - “Why this answer?” payload,
  - eval artifacts.

**Phase 0 (retrieval-core safe) note**
- Do not add new API payload fields or “Why this answer?” endpoints during Phase 0 (no server/adapters edits).
- Do not update readout tooling during Phase 0 (no `tools/*` edits).
- Diagnostics may exist only as internal debug data (e.g., in-memory for unit tests) until runtime/tooling.

**Safety constraints**
- This is observability only. No new path to “PASS”.
- If pack budgeting or filtering would drop required support or required conflict coverage, the system must fail closed:
  - do not proceed to `PASS` with a partial/one-sided pack,
  - instead return `CLARIFY` or `ABSTAIN`.

**Diagnostics safety constraints**
- By default, diagnostics must not log raw memory text (`canonical_text`) or raw user text.
- Default diagnostics should log atom ids, section, scores, and reason codes.
- Any “include text in artifacts” mode must be explicit opt-in and must document PII handling expectations.
- De-duplication must be conservative:
  - never dedupe across distinct atoms solely by canonical text/topic similarity,
  - only drop true duplicates (same atom id / explicit equivalence),
  - never drop conflict neighbors as “duplicates”.

**Why it helps**
- Makes retrieval tuning measurable and auditable.
- Prevents “broad retrieval” from quietly passing gates.

### 4.5 Type-Specific Temporal Decay Defaults

**Idea borrowed:** HippocampAI uses different half-lives by memory type.

**High-level behavior**
- Tune default half-life policy by `AtomType` (example idea, not final):
  - `EPISODE`: shorter (events go stale faster),
  - `ATOMIC_FACT`: medium,
  - `RELATIONAL`: medium,
  - `AFFECTIVE`: longer (identity/emotion may stay salient),
  - `PROCEDURAL_STYLE`: long.

**Safety constraints**
- Decay affects rank, not truth.
- Conflicted atoms should not be “decayed away” into invisibility when they matter for uncertainty.
- Explicit time intent (e.g., dates/years/time ranges in the query) must override default recency bias so older-but-relevant evidence is still retrievable.

**Why it helps**
- Reduces stale answers and makes “current preferences” win naturally.

### 4.6 Small Caches (Speed Without New Infra)

**Idea borrowed:** HippocampAI caches reranker scores; we keep it lighter.

**High-level behavior**
- Cache the expensive/duplicative parts:
  - query tokenization,
  - BM25 index structures,
  - recent retrieval results per (query, store_revision, profile).
- Cache must invalidate safely when store contents change.

**Phase 0 (retrieval-core safe) note**
- Keep caches fully in-process and MNO-only.
- Avoid introducing new config keys for cache sizing/TTL during Phase 0; use conservative internal defaults and validate with unit tests.

**Safety constraints**
- Cache must never return results for the wrong user/store scope.
- Cache must not persist across incompatible store versions without invalidation.
- Cache key contract must include:
  - user/store scope,
  - store revision token,
  - retrieval profile and enabled channels,
  - key configuration knobs (budgets/thresholds),
  - (if enabled) embedding model / reranker model version identifiers.
- Evals should run with caches disabled (or with a dedicated test proving cache scoping and invalidation correctness).
- Store revision token semantics must be explicit:
  - revision MUST change on atom insert/update/delete,
  - revision MUST change on conflict-edge updates,
  - revision MUST change on any continuity/graph snapshot change that affects retrieval,
  - if atom-store and continuity-store have different revision domains, cache keys must include both.

## 5. “Steal Later” Upgrades (Optional, Keep Behind Flags)

These can improve recall but add dependencies and complexity. Only do them after core phases are complete and measurable quality gaps still remain.

### 5.1 Embedding-Based Retrieval (Optional Channel)

**Idea borrowed:** HippocampAI uses sentence-transformers + Qdrant.

**High-level behavior**
- Add an embedding channel that:
  - computes embeddings for atoms at ingest/write time,
  - computes query embedding at read time,
  - returns top-K nearest neighbor candidates.
- Fuse with RRF like other channels.

**Lean guardrails**
- Must be optional (config flag / optional dependency).
- Must have strict budgets (top-K small, rerank limit unchanged).
- Prefer local/in-process storage for MVP (avoid introducing a mandatory vector DB).
- Must define a re-embed / migration plan when the embedding model changes, otherwise eval integrity becomes unstable.

**Phase 0 (retrieval-core safe) note**
- This section is explicitly runtime/tooling because it requires dependency work (`pyproject.toml`) and likely new config knobs.

**Safety constraints**
- Embeddings only help candidate discovery; evidence requirements unchanged.

### 5.2 Cross-Encoder Reranking (Optional Post-Fusion)

**Idea borrowed:** HippocampAI uses a cross-encoder to rerank candidates.

**High-level behavior**
- After RRF fusion, apply a cross-encoder reranker to top-N candidates.
- Keep only top-M for pack-building.

**Lean guardrails**
- Optional, cached, bounded (top-N small).
- Must not increase retrieval fanout. It reorders, it does not expand.
- Must pin model versions in config and document how changes are validated (to avoid silent ranking drift).

**Phase 0 (retrieval-core safe) note**
- This section is explicitly runtime/tooling because it typically requires dependency/config work and introduces ranking drift risk if not tightly pinned and evaluated.

**Safety constraints**
- Reranker does not count as evidence; it is ranking only.

## 6. Safety Model (Near-Perfect False Recall)

This upgrade path is designed so *better retrieval cannot create hallucinated memory claims*.

Key invariants:
- Final claims still must map to **direct atom evidence** (core/context/conflict), not derived continuity objects.
- If the verifier cannot support a claim, service verdict must become `ABSTAIN` or `CLARIFY`.
- Conflicts are preserved and surfaced as uncertainty.
- “Evidence” in this system means: source-linked atoms included in the delivered evidence pack (not latent retrieval candidates).

## 7. Eval / Test Strategy (High-Level)

### 7.1 Must-not-regress checks
- `false_memory_rate` must remain 0 for memory claims (fail closed).
- `abstain_precision` must remain 1 (no “fake abstain” that still claims memory).
- Routing must keep routine chat routine (no memory spam).
- Retrieval must stay bounded (fanout thresholds enforced).
- Evals must be strict about alignment: supported non-routine cases cannot pass with unrelated evidence.

### 7.2 Must-improve checks (measurable)
- Retrieval hit-rate / recall@k on paraphrase-heavy prompts improves.
- Reduction in irrelevant evidence items in top packs.
- Fewer “ABSTAIN because retrieval missed obvious support” cases.

### 7.2.1 New integrity metrics (recommended)
- `evidence_precision@k`: fraction of evidence items that are actually relevant to the query.
- `junk_rate@k`: fraction of top-k evidence items that are unrelated/noisy (inverse of precision).
- `conflict_coverage`: when contradictions exist for the topic, both sides appear in pack or verdict fails closed.
- Anti-gaming coverage: enforce a floor on “memory-claim coverage” only on eval cases where support is known to exist. This metric is an eval-only guardrail and MUST NOT be used to justify relaxing verifier thresholds.

### 7.3 New tests to add (conceptual)
- Router classification unit tests (per profile).
- BM25 behavior tests (rare keyword rescue, stopword noise).
- RRF fusion tests (channel rescue behavior).
- Diagnostics tests (dropped reason codes stable and present).
- “Derived-only evidence” guard remains intact.
- Cache scoping tests (no cross-user/store mixing; correct invalidation).
- Negative tests for recency injection (generic prompts must not retrieve/cite recent unrelated atoms).
- Conflict-coverage gold tests (if a selected item has conflict edges, include both sides or fail closed).
- Router fallback tests (misclassification must not produce `PASS` without evidence).
- Cache parity tests (caches off vs on should not change verdict distributions; no stale evidence reuse).

## 8. Rollout Strategy (Don’t Break Production)

Phase approach (recommended):
1. Phase 0 (retrieval-core safe): retrieval-only changes inside allowed zones (0.2.2).
2. Runtime/tooling: surface observability (diagnostics payloads + readouts + stable “why” output) if desired.
3. Runtime/tooling: add new config knobs if needed (budgets/thresholds/feature flags).
4. Runtime/tooling: optional embeddings channel.
5. Runtime/tooling: optional cross-encoder reranker.

Each phase ships behind flags and is gated by the existing acceptance harness and human-quality readouts.
- Never declare “green” unless both `safety_verdict` and `human_quality_verdict` pass.
- P0 run summaries must follow `docs/MNO_P0_RUN_SUMMARY_CONTRACT.md` before any done/green language.

### 8.1 Rollout stop conditions (examples)
- Any increase in unsupported memory claims (safety regression).
- Evidence precision drop (more junk in packs).
- Contradiction handling regression (one-sided packs allowed to `PASS`).
- Latency budget regression beyond conversational target.
- Any configuration that enables “include text in diagnostics” in production by default (stop-ship; must be opt-in).

## 9. Risks + Mitigations

Risk: Better retrieval increases “temptation” to answer more.
- Mitigation: verifier/verdict stays authoritative; keep strict direct-citation gate.

Risk: Over-broad retrieval passes “alignment” by accident.
- Mitigation: dropped-reason diagnostics + strict per-case evidence alignment checks in evals.

Risk: More semantic matching increases false positives in verifier (if verifier remains overlap-based).
- Mitigation: keep verifier conservative; accept more abstains over wrong claims; consider future semantic entailment check only if needed.

Risk: Dependency bloat (BM25/embeddings/rerank).
- Mitigation: keep core path dependency-free; make heavier features optional.

## Appendix A: Implementation Touchpoints (Phase Map)

This appendix is a “where it likely plugs in” map to speed implementation later. It is not a design requirement and does not prescribe exact code structure.

### Appendix A.1 Phase 0 (retrieval-core safe) Touchpoints (Allowed)

Allowed zones are defined in 0.2.2. The intent is: retrieval improvements are implemented without touching runtime server/adapters, tooling, shared contracts/config, or dependencies.

0–3 (Docs)
- `docs/MNO_LEAN_RETRIEVAL_UPGRADES_SPEC.md`
- `docs/NEAR_PERFECT_GOAL.md`
- `RETRIEVAL_AND_SCORING.md`

4.1 Query Router
- Preferred: `engine/retrieval/engine.py` (internal profile/routing logic)
- Related tests: `tests/unit/test_retrieval_engine.py`

4.2 BM25 Keyword Channel
- Primary: `engine/retrieval/engine.py`
- Secondary: `engine/memory/sqlite_store.py`, `engine/memory/store.py`
- Related tests: `tests/unit/test_retrieval_engine.py`

4.3 RRF Fusion
- Primary: `engine/retrieval/engine.py`
- Related tests: `tests/unit/test_retrieval_engine.py`, `tests/unit/test_retrieval_shared_language.py`

4.4 Pack Budgeting + Dropped Reasons (Internal-only in Phase 0)
- Primary: `engine/retrieval/engine.py`
- Related tests: `tests/unit/test_retrieval_engine.py`, `tests/unit/test_claim_verifier.py`

4.5 Type-Specific Temporal Decay Defaults
- Primary: `engine/memory/store.py`, `engine/continuity/consolidator.py`, `engine/continuity/store.py`
- Secondary: `engine/memory/sqlite_store.py`
- Related tests: `tests/unit/test_consolidator.py`, `tests/unit/test_memory_store.py`

4.6 Small Caches
- Primary: `engine/retrieval/engine.py`
- Secondary: `engine/memory/sqlite_store.py` (cache invalidation tokens), `engine/continuity/store.py`
- Related tests: `tests/unit/test_sqlite_atom_store.py`, `tests/unit/test_retrieval_engine.py`

6 Safety Model (Verifier + Gates)
- Primary: `engine/retrieval/verifier.py`, `engine/retrieval/engine.py`
- Related tests: `tests/unit/test_claim_verifier.py`

### Appendix A.2 Runtime/tooling Touchpoints (Frozen in Phase 0)

These files are valid touchpoints for later phases, but are explicitly frozen during the standalone lane (0.2.1):
- `engine/runtime/*` (API payloads, adapters, UI, runtime session, prior mixed-repo incremental surface)
- removed document-research/add-on surfaces
- `tools/*` (readouts, gates, runners)
- `engine/contracts.py` (shared contracts)
- `engine/config.py` (shared config knobs)
- `pyproject.toml` (dependencies)

Optional features that typically require these frozen touchpoints:
- Diagnostics surfacing (“Why this answer?” payloads, stable readouts).
- New config knobs and feature flags.
- Embedding retrieval channel.
- Cross-encoder reranking.
