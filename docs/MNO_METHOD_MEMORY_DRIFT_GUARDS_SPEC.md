# MNO Methodology Memory + Drift Guards Spec

Status: Implemented (phases 0-4 complete; phase 5 deferred by contract)  
Owner: ModelNO (MNO)  
Last Updated: 2026-02-24

## 1) Objective

Add a clean, additive “how I operate” memory layer for MNO, with safe self-improvement loops that do not degrade trust metrics.

Target outcomes:
- operational method knowledge becomes first-class memory (not ad-hoc notes),
- repeated user corrections become structured fix proposals,
- methodology changes use canary + rollback by default,
- maintenance triggers run on real conditions, not fixed schedule.

## 2) Priority decisions (locked)

Based on reviewed guidance, the execution order is locked:

1. **Methodology Memory + Canary/Rollback** (ship together)  
2. **Friction -> Candidate Fix** proposal generation  
3. **Condition-based maintenance triggers** (conservative thresholds first)  
4. **Anti-self-confirmation guards** (deferred until real failure patterns are observed)

## 3) Non-negotiable contracts

1. No safety/quality regression (`false_memory_rate=0`, fail-closed behavior unchanged).  
2. No autonomous methodology auto-apply; all methodology changes require human approval.  
3. Every methodology change is versioned, auditable, reversible.  
4. Changes remain additive; core retrieval/verifier contracts do not get rewritten.  
5. If methodology canary hurts quality, automatic rollback is mandatory.

## 4) Methodology memory contract (minimal schema)

Each methodology memory record must stay tight:
- `trigger_condition`
- `action`
- `rationale`
- `version`

Required supporting metadata:
- status (`draft`, `canary`, `active`, `retired`),
- provenance/evidence refs,
- created/updated timestamps,
- approval state.

No broad free-form schema expansion in v1.

## 5) Additive architecture contract

This block must plug into existing systems:
- existing proposal/review pipeline,
- existing approval controls,
- existing quality metrics and gate runner,
- existing audit trail.

No new parallel governance stack is allowed.

## 6) Phased implementation plan

### Phase 0 — Contract lock
Goal:
- lock schema, lifecycle states, quality gates, rollback rules.

Gate:
- all contracts approved and testable before implementation starts.

### Phase 1 — Methodology memory + canary/rollback
Goal:
- introduce first-class methodology records and safe activation lifecycle.

Deliver:
- create/edit/review flow for methodology records,
- `draft -> canary -> active -> retired` lifecycle,
- canary quality comparison against baseline,
- auto-rollback on quality drop.

Gate:
- versioned lifecycle works end-to-end,
- rollback path verified,
- no trust metric regression.

### Phase 2 — Friction -> candidate fix
Goal:
- convert repeated correction patterns into actionable proposals.

Deliver:
- correction-pattern detector with low threshold (default 2–3),
- proposal auto-generation into existing review queue,
- no auto-apply.

Gate:
- repeated correction clusters produce proposals reliably,
- no false auto-application path exists.

### Phase 3 — Condition-based maintenance triggers
Goal:
- trigger maintenance only when real signals indicate drift.

Initial trigger set:
- clarify-rate spike,
- contradiction accumulation growth,
- relevance/drift threshold breach.

Policy:
- start with conservative thresholds (intentionally high) and tune downward with evidence.

Gate:
- triggers fire when expected, avoid high false-positive churn,
- trigger actions are auditable and reversible.

### Phase 4 — Stability hardening + operator UX
Goal:
- make the system understandable and safe for routine operator use.

Deliver:
- concise operator readout (what changed, why, current canary state),
- per-change risk labels,
- one-click rollback confirmation path.

Gate:
- operator can diagnose and control methodology evolution without deep internals.

### Phase 5 (Deferred) — Anti-self-confirmation guardrails
Goal:
- reduce echo-chamber bias in methodology evolution.

Constraint:
- do not ship until real bias/failure examples are collected from prior phases.

Gate:
- guard design is evidence-driven, not speculative.

## 7) Regression gates (required each phase)

Each phase runs two passes:
1. Pass A: minimal implementation + targeted tests  
2. Pass B: hardening/refinement + full relevant regressions

Must report:
- safety verdict,
- human-quality verdict,
- rollback readiness,
- key failure examples (if any).

Any trust regression = phase not done.

## 8) Done definition

This block is complete only when:
- methodology memory is first-class, versioned, and review-gated,
- correction loops generate clean candidate fixes,
- canary + rollback protects quality,
- condition triggers are useful and not noisy,
- and core MNO trust metrics remain intact.
