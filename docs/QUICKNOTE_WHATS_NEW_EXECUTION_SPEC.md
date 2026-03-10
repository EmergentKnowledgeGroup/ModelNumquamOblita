# Quicknote + Whats-New Execution Spec

Date: 2026-02-22  
Status: Locked for implementation  
Scope: low-friction day-to-day memory writes and continuity diffs for agent workflows.

## 1) Goal

Replace heavy archive import loops for normal daily usage with a clean, low-token memory flow:
- Agent can say “remember this” without complex payload construction.
- Agent can wake up and immediately see “what changed since last time.”
- Safety and evidence discipline remain intact.

## 2) Product Contract

1. Daily memory capture must be one-call simple.  
2. Changes-since-last-visit must be one-call simple.  
3. Default responses must be compact and bounded.  
4. Writes must remain policy-controlled (no blind direct memory injection).  
5. Existing safety posture stays unchanged (no unsupported memory claims).

## 3) New Surfaces

## 3.1 `memory.quicknote.propose`
Purpose:
- Submit a short “this mattered” memory note with minimal arguments.

Input (minimal):
- `text` (required)
- optional: `importance`, `tags`, `session_id`

Behavior:
- Server auto-attaches provenance/session metadata.
- Server auto-creates evidence envelope internally.
- Returns pending proposal summary (or policy-applied result when auto-apply is enabled by policy).

## 3.2 `memory.quicknote.propose_batch`
Purpose:
- Submit multiple notes in one request with shared metadata and dedupe checks.

Behavior:
- Bounded list size.
- Per-item validation and dedupe.
- One compact aggregate result.

## 3.3 `memory.quicknote.flush`
Purpose:
- Flush buffered pending notes for current assistant/session scope.

Behavior:
- Idempotent.
- No-op on empty buffer.
- Returns compact summary.

## 3.4 `memory.quicknote.status`
Purpose:
- Show current quicknote state without writing.

Output:
- pending buffer count,
- per-session cap used/remaining,
- last flush time,
- recommended next action.

## 3.5 `explore.whats_new`
Purpose:
- Return compact memory diff since last check-in.

Output:
- added/updated/resolved counts,
- top changed anchors/atoms,
- optional unresolved highlights,
- cursor metadata.

## 3.6 `system.usage_guide`
Purpose:
- One compact guidance object for low-token best-practice usage.

Intent:
- Avoid repeated high-cost “how should I use memory tools?” calls.

## 4) Cursor and Continuity Rules (`explore.whats_new`)

## 4.1 Server-side cursoring (required)
- Store `last_seen` cursor server-side per assistant identity.
- Optional session-scoped overlay allowed, but assistant identity is the primary continuity key.

## 4.2 Auto-advance behavior
- Normal call auto-advances cursor after successful response.
- `peek_only=true` returns diff without advancing cursor.

## 4.3 Cursor invalidation
- If memory store is rebuilt/reimported, mark cursor invalid and start fresh baseline.
- Response must indicate baseline reset occurred.

## 5) Quicknote Batching + Cap Policy

## 5.1 Per-session cap tracking
Track server-side by assistant+session:
- `notes_proposed`,
- `notes_applied`,
- `last_activity_at`,
- lightweight dedupe fingerprints.

## 5.2 Cap semantics
- Cap blocks new quicknote proposals when reached.
- Cap does not block status/read calls.
- Cap reset only on:
  - session rollover,
  - explicit operator reset,
  - configured hard session close policy.

## 5.3 Flush triggers (hybrid)
Primary:
- explicit `memory.quicknote.flush`

Fallbacks:
- non-empty inactivity timeout flush (default 60 minutes, operator-configurable),
- session rollover flush,
- cap-reached flush,
- optional client hint flush when `context_pressure=high`.

Rules:
- never flush empty buffer,
- inactivity flush does not reset cap,
- all flush outcomes are idempotent and compact.

## 6) Autonomy Modes

Configurable policy profile:
- `always_ask`: every quicknote proposal requires explicit user confirmation.
- `smart_ask` (recommended default): propose automatically only for high-novelty/high-importance candidates; otherwise ask.
- `trusted_auto`: auto-propose/auto-apply only in trusted environments with strict audit trail.

## 7) Guardrails and Risk Controls

1. Dedupe before proposal creation (avoid repetitive note spam).  
2. Per-session note cap + burst rate limit.  
3. Proposal-only default for write path unless policy explicitly allows apply.  
4. PII/sensitive-term policy hook before write proposal acceptance.  
5. Clear rejection reasons for blocked writes (`cap_reached`, `duplicate`, `policy_blocked`, etc.).

## 8) Token Budget Contract

Defaults:
- compact outputs everywhere for new tools.
- rich payloads only via explicit opt-in.

Requirements:
- `status`, `flush`, and `whats_new` are bounded and deterministic.
- no duplicate data blocks in default output.
- no unbounded history payloads.

## 9) Known Gaps (Post-Implementation)

1. If client does not expose context-pressure hints, compression-trigger flush is unavailable.  
2. Multi-client concurrent writers need conflict-safe cursor/cap handling.  
3. Poor-quality notes remain possible without quality scoring and policy tuning.

## 10) Phased Implementation Plan

## Phase 0 — State model and policy knobs
- Add quicknote state model (buffer, counters, last flush, cursors).
- Add operator config for inactivity timeout and caps.

Gate:
- State persists across process restarts and remains bounded.

## Phase 1 — Quicknote core endpoints
- Implement `memory.quicknote.propose`, `status`, and `flush`.

Gate:
- One-note flow works end-to-end with compact responses.

## Phase 2 — Batch + cap + dedupe
- Implement `propose_batch`.
- Enforce per-session caps and dedupe.

Gate:
- Cap behavior deterministic and test-covered.

## Phase 3 — Whats-new diff engine
- Implement `explore.whats_new`.
- Add server-side cursor auto-advance and `peek_only`.

Gate:
- Diff output stable; cursor behavior correct.

## Phase 4 — Hybrid trigger automation
- Add inactivity (non-empty only), rollover, and cap-trigger flush logic.
- Add optional `context_pressure=high` flush hook.

Gate:
- Triggers fire correctly; no empty flushes.

## Phase 5 — Usage guide + polish
- Add `system.usage_guide` compact guidance payload.
- Final payload tuning and deterministic ordering.

Gate:
- New-agent bootstrap requires minimal calls.

## Phase 6 — Regression + trust validation
- Full regression pass across read/write/explore flows.
- Safety checks for unsupported-memory behavior and citation discipline.

Gate:
- No safety regressions; compact payload targets met.

## 11) Acceptance Criteria

Complete only when:
1. Agent can persist daily notes without archive export loops.  
2. Agent can retrieve “what changed since last time” in one call with server-managed cursoring.  
3. Hybrid flush behavior works without explicit end-of-session signals.  
4. Token budget improvements are measurable and stable.  
5. Safety, abstain, and evidence trust constraints remain intact.
