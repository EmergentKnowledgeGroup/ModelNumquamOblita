# MCP Payload Optimization Execution Spec

Date: 2026-02-21  
Status: Approved for implementation  
Scope: exploration/chat/wizard MCP response dieting with no memory-safety regression.

## 1) Objective

Reduce context/token burn during memory exploration without reducing trust, citation quality, or memory routing safety.

Primary outcomes:
- Lean payloads by default.
- Rich payloads only when explicitly requested.
- Better cold-start orientation in one call.
- Fewer multi-call orchestration overheads.

## 2) Non-Negotiable Contracts

1. Safety behavior does not degrade (`false_memory_rate=0`, abstain/citation policies unchanged).  
2. Tool outputs remain bounded and deterministic.  
3. All new “compact” defaults remain reversible with `mode=full`.  
4. Any “SUPPORTED” response must still be evidence-anchored.

## 3) Build Workflow Contract (Required Per Phase)

For every phase below:
1. **Checkpoint start** (`LATEST.md` + `LATEST.json`) with phase name + next command.
2. **Pass A implementation** (functional correctness).
3. **Targeted regression tests** for touched tools/flows.
4. **Pass B refinement** (payload size, determinism, edge handling).
5. **Re-run targeted tests**.
6. **Checkpoint post-green** with validation summary + next phase command.

If a regression appears:
- Fix root cause first.
- Re-run same gate before moving forward.
- Record failure + fix in checkpoint note.

## 4) Phase Plan

## Phase 0 — Baseline & Metrics Lock
Goal:
- Lock baseline payload/latency metrics for current exploration-heavy workflows.

Implement:
- Record baseline response-size and latency snapshots for:
  - `explore.start_here`
  - `explore.expand_anchor`
  - `explore.peek`
  - `memory.get_atom`
  - `chat.route_preview`

Regression gate:
- Baseline file captured and reproducible.

## Phase 1 — Compact/Full Contract
Goal:
- Introduce explicit output mode controls with compact default.

Implement:
- Add `mode=compact|full` to:
  - `explore.expand_anchor`
  - `explore.peek`
  - `memory.get_atom`
- Default mode is `compact`.

Regression gate:
- Existing callers still work with omitted mode.
- Full mode retains previous rich detail behavior.

## Phase 2 — Exploration Payload Diet
Goal:
- Remove obvious duplicate payload and noisy hop spam.

Implement:
- `explore.peek` compact: return snippet-oriented rows; raw excerpt only in full.
- `explore.expand_anchor` compact: return bounded connected atom cards.
- Deduplicate `next_hops` by logical anchor identity and keep best-scoring representative.

Regression gate:
- No duplicate next-hop anchors.
- Compact output materially smaller than full.

## Phase 3 — `memory.get_atom` Graph Usability
Goal:
- Replace “opaque ID dump” with actionable compact neighbors.

Implement:
- Compact mode returns top neighbor summaries (small bounded set).
- Full mode keeps full graph identifier arrays and extended metadata.

Regression gate:
- Compact mode is directly usable without N follow-up calls.
- Full mode remains available for debug/operator workflows.

## Phase 4 — One-Call Orientation & Mid-Granularity Brief
Goal:
- Let a freshly started agent orient memory in one call.

Implement:
- Add `explore.orient`:
  - what matters now,
  - key people/projects/topics,
  - unresolved items,
  - recent focus thread.
- Add `explore.anchor_brief`:
  - one-paragraph anchor summary,
  - top evidence anchors/citations,
  - bounded confidence signals.

Regression gate:
- Cold-start orientation works in one call with bounded payload.
- Anchor brief returns useful middle-ground output (not too thin, not too heavy).

## Phase 5 — Route Budget Metadata
Goal:
- Expose likely cost class before full chat execution.

Implement:
- Extend `chat.route_preview` output with budget metadata:
  - `estimated_route_cost_class`,
  - `expected_memory_touch`,
  - optional bounded token-band hints.

Regression gate:
- Route preview remains lightweight.
- Budget metadata is stable and deterministic for same input.

## Phase 6 — Organizer Batch Wrapper
Goal:
- Reduce multi-step wizard token burn.

Implement:
- Add `wizard.organizer_run` orchestration wrapper:
  - inventory -> dedupe -> conflicts -> package -> apply(optional) -> verify.
- Default return: compact summary.
- Optional debug switch: include stage payloads.

Regression gate:
- End-to-end organizer pipeline can run in one call.
- Compact summary is sufficient for normal flow.

## Phase 7 — Final Validation & Hardening
Goal:
- Confirm diet gains with no trust regression.

Implement:
- End-to-end regression runs covering exploration, chat preview, and organizer workflows.
- Before/after metrics report:
  - payload size,
  - latency,
  - quality/safety guardrails.

Regression gate:
- Safety unchanged.
- Payload reduction achieved on target calls.
- No regression in citation resolution or clarify behavior.

## 5) Acceptance Criteria

This block is complete only when all are true:
1. Compact defaults are active on targeted tools.
2. Full modes preserve rich/debug behavior.
3. Orientation and anchor-brief calls exist and are usable.
4. Organizer batch wrapper exists and returns compact summary by default.
5. Route preview exposes usable budget metadata.
6. Regressions pass and safety contract remains intact.

## 6) Rollout Notes

- Keep compatibility: existing clients with no new args must continue to function.
- Prefer additive fields/tools over breaking schema changes.
- If any compact output causes confidence inflation or false SUPPORT risk, revert that sub-change and keep CLARIFY-first behavior.
