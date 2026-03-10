# MCP Payload Diet Note (Quick Local)

Date: 2026-02-21  
Scope: quick action note only (not full spec) for exploration-call token reduction.

## Why this note exists

During live Claude use, exploration calls were useful but too heavy for context budget.  
Goal: keep the same memory quality while defaulting to lean payloads.

## Confirmed pain points

1) `explore.expand_anchor` returns useful connected atoms, but next-hops can be repetitive/noisy.  
2) `explore.peek` returns both `snippet` and `raw_excerpt` by default (duplicative payload).  
3) `memory.list_atoms` can be too verbose for definition-style queries (e.g., “what is dyad?”).  
4) Deep exploration chains consume context too quickly due to response size, not retrieval quality.

## Immediate adjustments to implement

### P0 (default behavior changes)

1. Add response mode control:
   - `mode=compact|full` on `explore.expand_anchor` and `explore.peek`.
   - Default is `compact`.

2. Compact payload rules:
   - `explore.peek`: return `snippet` only; `raw_excerpt` only in `full`.
   - `explore.expand_anchor`: return smaller connected atom payload in compact; keep richer fields in full.

3. Next-hop dedupe:
   - Deduplicate `next_hops` by `(anchor_type, anchor_id)` before final return.
   - Keep best-scoring row per dedupe key.

### P1 (quality-of-life follow-ups)

4. Add one mid-granularity tool:
   - `explore.anchor_brief`
   - Output: one-paragraph summary + top anchors/citations + confidence.
   - Purpose: “tell me what this anchor is” without large snippet arrays.

5. Add optional payload toggles:
   - `include_raw_excerpt` (default false)
   - `include_next_hops` (default true, but bounded)

6. Add definition-oriented query path:
   - lightweight anchor-definition response path for terms like `dyad`.

## Success criteria

1) Exploration sessions keep core signal quality while reducing response token size materially.  
2) Repeated anchor expansion no longer returns obvious duplicate next-hops.  
3) Claude can run multi-hop exploration without context exhaustion from payload overhead.  
4) No safety regressions (citations/clarify behavior unchanged).

## Cloudflare Code Mode fit (decision now)

- Code Mode is promising for broader MCP orchestration and tool-context shaping.
- For current NO bottleneck, payload diet is the faster, lower-risk win.
- Decision: do payload diet first; evaluate Code Mode integration after payload baseline is stabilized.

---

## Additional pain points (Claude batch 2)

### 1) `memory.get_atom` graph neighbor IDs are not directly usable

Problem:
- Returning large flat lists of opaque neighbor IDs creates token cost without immediate utility.

Adjustment:
- Add `mode=compact|full` to `memory.get_atom`.
- In `compact`:
  - return top-N neighbors with one-line summaries + confidence + relation kind,
  - optionally omit raw ID lists.
- Keep full neighbor ID arrays in `full` for tooling/debug use.

### 2) Chat route cost/budget visibility

Observation:
- `chat.route_preview` already exists and is compact enough for route-only decisions.

Gap:
- caller still cannot estimate likely response payload cost before running full `chat.turn`.

Adjustment:
- Add lightweight budget metadata to `chat.route_preview`, e.g.:
  - `estimated_route_cost_class` (`low|medium|high`),
  - `expected_memory_touch` (`none|stm|ltm_light|ltm_deep`),
  - optional rough token bands for request/response envelopes.

### 3) Wizard organizer pipeline causes sequential payload bloat

Problem:
- Running organizer as 6+ explicit calls can consume context due to repeated payloads.

Adjustment:
- Add `wizard.organizer_run` (batch orchestration wrapper):
  - executes inventory -> dedupe -> conflicts -> package -> apply(optional) -> verify,
  - returns one compact summary object by default,
  - expose `include_stage_payloads=true` for debugging only.

### 4) Cold-start orientation should be one call

Problem:
- New/just-woke model needs multiple calls (`start_here` -> `expand` -> `peek`) to orient.

Adjustment:
- Add `explore.orient` (aka memory wake-up call):
  - “top 5 what matters now,”
  - key people/projects,
  - last active thread / recent focus,
  - unresolved items,
  - all compact and bounded.

## Priority update after batch 2

P0:
1. compact/full modes on `explore.peek`, `explore.expand_anchor`, `memory.get_atom`
2. next-hop dedupe in `explore.expand_anchor`
3. `explore.orient` single-call wake-up view

P1:
4. `explore.anchor_brief`
5. `wizard.organizer_run` compact batch wrapper
6. route-preview budget metadata

## Pragmatic pushback note

- Do not overfit around one client’s context window by removing full payloads entirely.
- Keep rich payload paths (`mode=full`) for operator/debug flows.
- Default should be lean; richness should be explicit opt-in.
