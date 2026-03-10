# Auto-Organizer Wizard Spec (Assistant-Led Memory Structuring)

Status: Actionable Spec (implementation-ready)  
Owner: NumquamOblita Core  
Last Updated: 2026-02-19

## 1) Purpose

Provide a structured wizard that lets an assistant periodically organize its memory surface without altering factual truth.

Primary outcomes:
- identify probable entities and themes (people/projects/topics/events),
- reduce label noise and duplicate anchors,
- isolate contradictions and ambiguity for explicit review,
- produce reversible organization updates,
- improve retrieval quality and exploration clarity.

This wizard governs **organization quality**, not unrestricted fact editing.

---

## 2) Contract (non-negotiable)

1. **Proposal-first mutation**
- Wizard generates proposals before applying any organizational change.

2. **Reversible operations**
- Every applied action has rollback metadata and audit visibility.

3. **Confidence-aware routing**
- high confidence: can auto-propose safe classes,
- medium confidence: propose with caution flags,
- low confidence: route to review queue only.

4. **Evidence and provenance integrity**
- Raw evidence text and provenance links are immutable by default.

5. **Bounded execution**
- Hard limits on scan scope, operation count, and run duration.

6. **Portable behavior**
- Runs against any normalized memory store, not user-specific schemas.

---

## 3) High-Level Wizard Flow

```text
Wizard Start
  ↓
Inventory Snapshot
  ↓
Candidate Typing
  ↓
Cluster + Dedupe Proposals
  ↓
Contradiction / Ambiguity Queues
  ↓
Proposal Package + Risk Classing
  ↓
Safe Apply (with rollback checkpoint)
  ↓
Post-Run Verification Report
```

---

## 4) Operation Model

## 4.1 Safe-by-default proposal classes
- label normalization,
- alias consolidation,
- duplicate grouping,
- soft-priority tuning.

## 4.2 Review-required proposal classes
- conflicting claim handling,
- low-confidence type assignment,
- any action with potential semantic loss.

## 4.3 Prohibited automatic classes
- rewriting factual evidence,
- deleting provenance history,
- irreversible merges without rollback record.

---

## 5) Wizard Stages (functional contract)

## Stage A — Inventory Snapshot
Goal:
- map current topology (top entities, top themes, orphan clusters, contradiction hotspots).

Output:
- compact ranked inventory report.

## Stage B — Candidate Typing
Goal:
- assign provisional type per anchor cluster:
  - Person / Project / Topic / Event / Unknown.

Output:
- typed map with confidence band and review hints.

## Stage C — Cluster + Dedupe
Goal:
- detect near-duplicates and synonym anchors; propose canonical labels + aliases.

Output:
- dedupe proposal set with before/after counts.

## Stage D — Contradiction + Ambiguity
Goal:
- isolate conflicting claims and unstable label clusters.

Output:
- conflict queue + ambiguity queue, each with severity.

## Stage E — Proposal Package
Goal:
- assemble all candidate changes into one auditable package with risk classes.

Output:
- signed proposal manifest (safe, review-required, blocked).

## Stage F — Apply + Rollback
Goal:
- apply only safe class changes automatically after checkpoint creation.

Output:
- apply log + rollback pointer.

## Stage G — Post-Run Verification
Goal:
- validate quality improvement and safety preservation after apply.

Output:
- pass/fail report + next-run recommendations.

---

## 6) Phase Plan (execution order)

## Phase 0 — Contract Lock
Goal:
- freeze proposal classes, confidence policy, rollback rules, and success metrics.

Exit criteria:
- signed contract with no unresolved policy points.

## Phase 1 — Inventory + Typing (dry-run)
Goal:
- implement Stage A and Stage B output only.

Exit criteria:
- useful typed inventory produced with confidence bands.

## Phase 2 — Dedupe + Alias Proposals
Goal:
- implement Stage C as reversible proposal generation.

Exit criteria:
- measurable duplicate reduction potential shown in report.

## Phase 3 — Conflict/Ambiguity Queues
Goal:
- implement Stage D routing and severity labeling.

Exit criteria:
- no hidden conflicts; all unstable clusters surfaced.

## Phase 4 — Proposal Package + Safe Apply
Goal:
- implement Stage E/F with checkpointed apply and rollback path.

Exit criteria:
- safe operations apply cleanly; rollback validated.

## Phase 5 — Verification and Quality Delta
Goal:
- implement Stage G verification summary and trend tracking.

Exit criteria:
- quality improves while safety remains intact.

## Phase 6 — Assistant Self-Run Surface
Goal:
- expose wizard for assistant-led runs (runtime first, optional MCP parity).

Exit criteria:
- assistant can execute bounded wizard run end-to-end.

---

## 7) Regression SOP (required every phase)

For each codebase change in this roadmap:

**Pass 1: targeted validation**
- verify changed stage behavior,
- verify proposal integrity and risk classification,
- verify rollback checkpoint generation.

**Pass 2: affected regression**
- run affected suites end-to-end,
- verify no safety regressions,
- verify no latency blowout,
- verify no provenance integrity break.

Completion rule:
- no phase closes unless Pass 1 and Pass 2 are both green.

---

## 8) Acceptance Gates

1. Wizard can run from zero context and produce actionable inventory.
2. Typing and dedupe materially reduce label/anchor noise.
3. Contradictions and ambiguities are surfaced, never hidden.
4. Safe apply operations are reversible and fully auditable.
5. Exploration start-here quality improves post-wizard.
6. Safety and citation contracts stay unchanged.

---

## 9) Metrics (minimum reporting)

Per run report must include:
- duplicate-anchor reduction ratio,
- canonical-label coverage ratio,
- unresolved-conflict queue size and trend,
- ambiguity queue trend,
- retrieval quality delta (before/after),
- safety metrics and latency impact.

---

## 10) Coupling with Exploration Mode

The wizard is the preparation layer for exploration mode:
- improves first-hop anchor quality,
- removes duplicate graph clutter,
- improves confidence calibration on peek cards,
- reduces dead-end hops during assistant exploration.

---

## 11) Risks and Mitigations

Risk: over-aggressive dedupe merges distinct concepts.  
Mitigation: conservative thresholds + review-required classing.

Risk: hidden contradictions degrade trust.  
Mitigation: mandatory contradiction queue with severity gates.

Risk: apply errors cause structural drift.  
Mitigation: pre-apply checkpoint + tested rollback path.

Risk: wizard bloat increases runtime cost.  
Mitigation: bounded scan/apply budget and phase-specific limits.

---

## 12) Out of Scope (this spec)

- Fully autonomous fact rewriting without review.
- Multi-tenant enterprise governance policy packs.
- Visual polish beyond core wizard workflow and reports.
