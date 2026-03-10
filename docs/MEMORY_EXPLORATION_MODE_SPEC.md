# Memory Exploration Mode Spec (Zero-Seed, Low-Token, Assistant-First)

Status: Actionable Spec (implementation-ready)  
Owner: NumquamOblita Core  
Last Updated: 2026-02-19

## 1) Purpose

Add a built-in exploration mode that lets an assistant discover and traverse its own memory graph **without needing a starting keyword**.

Target outcomes:
- reveal what exists first (people, projects, themes, timelines, unresolved clusters),
- support fast branch-to-branch navigation with minimal tokens,
- keep deep evidence available on demand (but never default-heavy),
- let the assistant express retrieval preferences without mutating core facts.

This capability is base-runtime first, with optional MCP parity.

---

## 2) Contract (non-negotiable)

1. **Zero-seed entry**
- Assistant can start from an empty exploration prompt.

2. **Low-token envelope**
- Default payload is compact and scan-oriented.
- Deep evidence is opt-in only.

3. **Non-destructive behavior**
- Exploration actions can adjust ranking hints only.
- Raw evidence and provenance never get silently rewritten.

4. **Fail-closed summaries**
- Exploration output cannot assert unsupported facts.
- If support is weak, output must abstain/flag ambiguity.

5. **Portable store compatibility**
- Behavior works on any normalized store (small or large).

6. **Bounded traversal**
- Hard limits for hops, fanout, token volume, and elapsed time.

---

## 3) High-Level User Flow

```text
Open Exploration
  ↓
Start-Here Snapshot
  (people / projects / topics / arcs / unresolved)
  ↓
Select Anchor
  ↓
Guided Hop List
  (next-most-useful related anchors)
  ↓
Peek Cards
  (tiny summary + confidence + source handle)
  ↓
Choose:
  [open detail] [next hop] [mark preference] [stop]
```

---

## 4) Response Envelope

Default exploration response must be concise:
- anchor identifier,
- display label,
- one-line summary,
- confidence band,
- one lightweight source handle.

Not included by default:
- full quote blocks,
- expanded citation windows,
- verbose reasoning narratives.

Explicit deep-open may return richer evidence, but still bounded.

---

## 5) Functional Modules

1. **Snapshot Builder**
- Produces zero-seed “Start Here” groups and ranking.

2. **Anchor Explorer**
- Returns related anchors and shortest useful next hops.

3. **Peek Renderer**
- Produces tiny cards optimized for rapid scanning.

4. **Preference Profiler**
- Captures `more`, `less`, `ignore`, `pin` signals.
- Applies only to ranking behavior.

5. **Budget Controller**
- Enforces token/time/fanout/hop ceilings per exploration session.

6. **Safety Guard Layer**
- Enforces abstain/ambiguity behavior for weak support.

---

## 6) Phase Plan (execution order)

## Phase 0 — Contract Lock
Goal:
- Lock envelope size, traversal limits, preference semantics, and acceptance metrics.

Deliverables:
- frozen contract table,
- phase-level gate checklist.

Exit criteria:
- contract signed off with no open ambiguity.

## Phase 1 — Zero-Seed Snapshot
Goal:
- Return usable “Start Here” map with no topic input.

Deliverables:
- grouped snapshot output (people/projects/topics/arcs/unresolved),
- deterministic ranking policy for first-hop anchors.

Exit criteria:
- assistant can start from empty prompt and receive useful anchors.

## Phase 2 — Guided Hop Expansion
Goal:
- Support connected-anchor traversal with shallow-first strategy.

Deliverables:
- ranked next-hop list,
- hop-depth controls and hard limits.

Exit criteria:
- assistant can traverse 3+ hops without response bloat.

## Phase 3 — Lightweight Peek
Goal:
- Provide tiny exploratory cards with confidence and source handle.

Deliverables:
- compact peek payload profile,
- deep-open path for detailed evidence.

Exit criteria:
- repeated exploration remains low-token and stable.

## Phase 4 — Preference Signals
Goal:
- Persist assistant preference actions and apply them to ranking.

Deliverables:
- preference action model (`more/less/ignore/pin`),
- ranking influence policy with safety limits.

Exit criteria:
- measurable reranking impact without factual drift.

## Phase 5 — Safety and Drift Guards
Goal:
- Prove preferences and traversal do not degrade trust behavior.

Deliverables:
- guardrails for over-recall prevention,
- ambiguity/abstain behavior under weak evidence.

Exit criteria:
- safety contract remains unchanged from baseline.

## Phase 6 — Runtime UX + MCP Parity
Goal:
- Expose same exploration behavior in runtime flow and MCP tools.

Deliverables:
- base runtime exploration entry,
- MCP parity behavior contract.

Exit criteria:
- equivalent semantics across surfaces, with same bounds.

---

## 7) Regression SOP (required every phase)

For each codebase change in this roadmap, run both passes before advancing:

**Pass 1: targeted validation**
- verify changed phase behavior,
- verify payload-size contract,
- verify bounded traversal controls.

**Pass 2: affected regression**
- run affected suites end-to-end,
- verify no safety regressions,
- verify no routine-chat over-recall drift,
- verify latency remains in conversational budget.

Release rule:
- no phase closes unless Pass 1 and Pass 2 are both green.

---

## 8) Acceptance Gates

1. Zero-seed exploration works from empty prompt.
2. Default payload stays compact across repeated hops.
3. Connected exploration supports multi-hop traversal cleanly.
4. Preference actions change ranking outcomes measurably.
5. Safety behavior remains fail-closed under weak evidence.
6. Performance remains stable on both small and large stores.

---

## 9) Metrics (minimum reporting)

Per phase report must include:
- start-here usefulness hit rate,
- average payload size per exploration step,
- average hop count before user/assistant stop,
- preference impact delta (before/after rank),
- safety metrics (false-memory, abstain precision),
- p95 latency under representative load.

---

## 10) Risks and Mitigations

Risk: exploration becomes verbose and expensive.  
Mitigation: strict envelope caps + deep-open on demand only.

Risk: preference signals bias retrieval too aggressively.  
Mitigation: capped influence weight + safety guard overrides.

Risk: large stores degrade first-hop quality.  
Mitigation: snapshot ranking normalization + large-store gates.

Risk: MCP and runtime drift apart.  
Mitigation: single behavior contract and parity regression checks.

---

## 11) Out of Scope (this spec)

- Full visual graph editor polish.
- Autonomous fact rewriting from exploration actions.
- Enterprise governance layers beyond baseline preference controls.
