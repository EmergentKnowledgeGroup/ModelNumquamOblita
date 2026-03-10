# Episodic Memory Card Build Spec

Status: Proposed (implementation-ready)  
Owner: Runtime/Memory Pipeline  
Last Updated: 2026-02-11

## 1. Problem Statement

Current retrieval is strong for truthful lookup, but some recalled prompts still anchor on short lines instead of full event memories.  
We need to convert raw conversation exports into **actual episodic memory cards** up front, then retrieve cards first and expand to surrounding evidence at response time.

## 2. Target Outcome

From a full `conversations.json` import:
- Build an **episode-first memory layer** automatically.
- Keep snippet/fact memory as a lower tier.
- Route “what happened” requests to episode cards, not isolated statements.
- Preserve current trust properties:
  - no fabricated memory (`false_memory_rate = 0` target),
  - no over-recall on routine chat (`routine_over_recall_rate = 0` target),
  - citation-backed recall only.

## 3. Design Principles

1. **Event over quote**: a memory must represent a scene or change, not a single filler line.  
2. **Evidence required**: every promoted episode card must have multi-turn provenance.  
3. **Card first, context second**: search compact cards first; expand raw context only after selection.  
4. **Deterministic core**: no mandatory LLM dependency in critical extraction path.  
5. **Latency-aware**: keep average latency flat/improved; bound deep-recall tail.  

## 4. Memory Model (New/Refined)

### 4.1 Card Classes
- `episode_card` (new primary): event-level memory with timeline and outcome.
- `fact_card` (existing/compat): concise statement memory.
- `snippet_card` (demoted utility): low-depth fragments, never preferred for episodic recall.

### 4.2 Episode Card Required Fields
- `episode_id`
- `title` (short event label)
- `summary` (2-5 lines)
- `actors` (who was involved)
- `event_window` (before / core / after pointers)
- `salience_score`
- `evidence_strength`
- `citations[]` (source references)
- `atom_ids[]` (linked atomic memory points)
- `topic_tags[]`
- `timestamp_start`, `timestamp_end`

### 4.3 Promotion Thresholds (initial)
- Minimum linked turns: `>= 3`
- Minimum meaningful token count across window: `>= 30`
- Must include at least one:
  - explicit action/change,
  - emotional shift,
  - decision/outcome.
- Reject low-information acknowledgments (`ok/sure/thanks` style) as episode roots.

## 5. Extraction Pipeline (Offline Build)

## 5.1 Stage A: Conversation Segmentation
- Segment by conversation boundary, time gap, topic shift, and speaker transition.
- Produce candidate windows (`before/core/after`).

## 5.2 Stage B: Event Candidate Generation
- Build candidates from adjacent windows with continuity signals:
  - same actors,
  - causal language,
  - follow-up references.

## 5.3 Stage C: Event Scoring
- Score each candidate:
  - `structure_score` (has setup-action-outcome),
  - `signal_score` (meaningful density),
  - `evidence_score` (citation depth),
  - `continuity_score` (cross-turn coherence).
- Keep top candidates per conversation; demote borderline candidates to fact/snippet tiers.

## 5.4 Stage D: Card Synthesis
- Create `episode_card` object from candidate.
- Store compact summary + source pointers; no heavy payload duplication.

## 5.5 Stage E: Validation Gate
- Block episode publish if:
  - low-information root text,
  - insufficient turn depth,
  - poor citation linkage.
- Emit diagnostics file with reject reasons.

## 6. Retrieval Path (Runtime)

## 6.1 Routing Policy
- Routine chat -> none/STM fast lane.
- Factual quick ask -> fact/snippet lane.
- “What happened / remember when / walk me through” -> episode-first lane.

## 6.2 Retrieval Order
1. Query episode cards (semantic + lexical hybrid).
2. Rank by relevance + evidence strength + recency/salience.
3. Expand top cards with bounded context window.
4. Return memory packet: card summary + citations + optional expanded context.

## 6.3 Safety Rules
- No citation -> no confident memory claim.
- If confidence below threshold -> abstain/clarify.
- Never promote unsupported guesses to memory output.

## 7. Metrics and Acceptance

## 7.1 Quality
- `false_memory_rate = 0.0` target.
- `routine_over_recall_rate = 0.0` target.
- `weak_episode_prompt_rate <= 2%` in generated eval set.
- Episode card depth median: `>= 3` linked turns.

## 7.2 Performance
- Keep current mean latency at or below baseline.
- Keep episodic p95 increase within controlled bound (`<= +20ms` vs baseline run target).
- No unbounded scan growth with larger stores.

## 7.3 Human QA
- Auto-generate readout showing:
  - question,
  - selected episode card,
  - cited evidence,
  - model context packet.
- Spot-check set must be event-level, not short-line anchors.

## 8. Implementation Plan (Phased)

### Phase 1: Episode Data Contracts
- Add/lock schemas for `episode_card` and promotion/reject diagnostics.
- Add migration/version guardrails.
- Tests: schema round-trip + backward compatibility.

### Phase 2: Segmentation + Candidate Builder
- Implement timeline segmentation and event candidate generation.
- Add deterministic fixtures covering edge cases (short chatter, tool blobs, abrupt topic jumps).
- Tests: segmentation and candidate correctness.

### Phase 3: Scoring + Promotion Gate
- Implement scoring model and thresholds.
- Add hard reject rules for low-information roots.
- Tests: promotion pass/fail matrix.

### Phase 4: Offline Card Build Command
- Build cards directly from imported store/export pipeline.
- Persist cards + diagnostics artifacts.
- Tests: command integration and artifact integrity.

### Phase 5: Episode-First Retrieval Integration
- Route episodic queries to card-first retrieval.
- Add bounded context expansion from pointers.
- Tests: route correctness + trust guarantees.

### Phase 6: Eval and QA Upgrades
- Add episode-specific eval fixtures and weak-prompt detection.
- Extend human readout for episode packet inspection.
- Tests: full eval and readout regression.

### Phase 7: Latency + Scale Polish
- Profile p95 tails; tune retrieval fanout and expansion bounds.
- Validate on full export and larger stores.
- Tests: benchmark gating + stability checks.

## 9. PR Block Strategy

One PR per phase (7 PRs total), each with:
- phase-specific tests green,
- full regression green before merge,
- PR feedback collector run and addressed,
- checkpoint snapshot before and after merge workflow.

## 10. Out of Scope (This Spec)

- UI redesign for card editing/curation.
- Mandatory LLM judge in extraction critical path.
- Cross-user federation or cloud sync.

## 11. Risks and Mitigations

- Risk: over-strict promotion drops meaningful memories.  
  Mitigation: diagnostics + threshold tuning loop with fixture-backed checks.

- Risk: episode extraction adds latency.  
  Mitigation: offline build; runtime only does card search + bounded expansion.

- Risk: semantically relevant but sparse memories get missed.  
  Mitigation: keep fact/snippet fallback tier and explicit clarification behavior.

