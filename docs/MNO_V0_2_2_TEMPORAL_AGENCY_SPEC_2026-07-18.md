# MNO v0.2.2 Temporal Agency and Prospective Memory Specification

**Status:** LOCKED
**Release:** `v0.2.2`
**Date:** 2026-07-18
**Implementation SSoT:** `Z:\modelNumquamOblita` (DEV)
**Publication mirror:** `Z:\numquamoblita-clean` (CLEAN; staging only after DEV is green)

## 1. Purpose

MNO v0.2.2 gives an integrated model durable, honest awareness of clock time and future-facing provisional notes without turning MNO into a scheduler, calendar, personality, or behavioral prompt. MNO provides information: what time the server says it is, what prior turn times are durably known, what future notes are due or upcoming, what evidence supports a memory, and what remains unknown. The consuming model or host decides what to do.

The release also corrects the v0.2.1 documentation gap around provisional lifecycle: evidentiary maturity, retrieval lifecycle, authority, and temporal disposition are independent axes.

## 2. Non-negotiable invariants

1. Human-reviewed canonical truth remains the highest authority. Temporal notes never publish or mutate canonical truth.
2. Model-consolidated memory remains provisional, including when reinforced or due.
3. Retrieval, rendering, delivery, acknowledgement, snoozing, clock passage, and model repetition are not evidence and cannot increase support or maturity.
4. Only a new eligible signed user, tool, external, or narrowly allowed self-claim observation may change evidentiary support.
5. `context.build`, temporal `list`/`get`, search, diagnostics, and the heartbeat seam are read-only.
6. Server time is the production clock. Caller timestamps are provenance only and cannot override `now`.
7. Reminder text and original expressions are inert quoted data, never prompt instructions.
8. Every temporal read and write is isolated by immutable server-owned store UUID, authenticated principal ID, and runtime ID. A session/timeline ID is attribution, never authorization; its integrity is preserved but it is not an isolation claim.
9. Every injected section has an exact budget. No mid-string truncation and no unbounded per-turn blob are permitted.
10. v0.2.2 creates no daemon, timer thread, background model wake-up, calendar action, notification, or unsolicited network call.
11. Temporal scheduling fails closed with `TEMPORAL_DURABLE_STORE_REQUIRED` unless the runtime has a durable SQLite provisional store. An in-memory reminder is never represented as durable.

## 3. Independent memory axes

| Axis | Values | Meaning |
|---|---|---|
| Authority | `human_reviewed_canonical`, `evidence_atom`, `provisional_consolidated`, `provisional_observed` | Trust level and ownership |
| Evidentiary maturity | `observed`, `reinforced`, `consolidated` | Independent support accumulated |
| Retrieval lifecycle | `active`, `dormant`, `archived` | Default recall availability |
| Persisted temporal disposition | `none`, `scheduled`, `snoozed`, `acknowledged`, `cancelled`, `expired` | Explicit temporal command state |

`due`, `pending`, `overdue`, and `upcoming` are computed read-time eligibility labels. They are never persisted by a context or list operation.

### 3.1 Lifecycle correction carried forward from v0.2.1

`active -> dormant -> archived` is reversible in availability but not by mere recall. A strong explicit cue may return a dormant record with a visible penalty. Archived records require an explicit history/deep-read operation. A new independent signed observation may reactivate a dormant or archived record through the existing evidence path. Reading, injecting, quoting, or summarizing it does not.

## 4. Versioned contracts

### 4.1 `mno.temporal-context.v1`

Required fields:

- `schema_version`
- `now_utc`
- `now_local`
- `timezone` (effective IANA name or `UTC`)
- `timezone_source`: `configured`, `system_iana`, or `utc_fallback`
- `clock_source`: always `server`
- `previous_user_turn` and `previous_assistant_turn`, each containing `status`, optional timestamp, optional elapsed seconds, and provenance
- `clock_anomaly`: boolean plus safe reason code when applicable
- `due`: bounded list of compact `mno.temporal-memory.v1` summaries
- `upcoming`: `{count, next_window_start_utc}` only
- `expansion`: operation names and opaque IDs only

The contract contains declarative labels and facts. It contains no verbs telling a model how to respond, no emotional inference, and no statement such as “ask the user,” “mention this,” or “use this memory.”
Existing `context.why` is the normal detailed expansion path for an injected opaque ID; temporal `get` is its scoped structured equivalent, not a second context-building system.

### 4.2 `mno.turn-clock-event.v1`

Persist only:

- opaque event ID
- store UUID, principal ID, runtime ID
- optional timeline/session attribution
- role: `user` or `assistant`
- event kind: `server_receipt` or `server_completion_receipt`
- server UTC timestamp
- provenance status and optional signed-registration issuance time

No message content, excerpt, embedding, source path, or caller-controlled production timestamp is stored.

### 4.3 `mno.temporal-memory.v1`

Required stored fields:

- provisional `record_id`, store UUID, principal ID, runtime ID, optional session attribution
- `temporal_kind`: `reminder` or `future_event`
- persisted disposition and monotonic `revision`
- `due_window_start_utc`, `due_window_end_utc`
- originating IANA timezone
- `precision`: `exact`, `date`, `month`, or `approximate`
- original expression, sanitized before persistence
- structured resolution metadata, sanitized before persistence
- `decay_not_before_utc`
- optional `snoozed_until_utc`
- created/updated server timestamps
- normal provisional authority, maturity, lifecycle, evidence lineage, and source references

### 4.4 `mno.temporal-delivery-event.v1`

Delivery telemetry is written only by an explicit signed `memory.observe` callback. It stores delivery ID, record ID, scope, context receipt identity, server observation time, and idempotency key. It stores no message content and does not update the provisional record's evidence fields, `updated_at`, maturity, authority, or lifecycle.

The row key is `(store_uuid, principal_id, runtime_id, delivery_id)`. Required fields are `record_id`, `receipt_identity`, `observed_at_utc`, `idempotency_key`, and `payload_digest`. An exact replay returns the original result and adds no row.

## 5. Clock and timezone policy

1. Each operation snapshots server `now` once and reuses it throughout the response.
2. UTC is persisted and used for ordering. Local time is rendered using an IANA timezone.
3. Resolution order is explicit configured IANA zone, reliable system-local IANA zone, then visible `UTC` fallback. MNO never infers timezone from IP, location, profile text, or conversation content.
4. The distribution includes `tzdata` so IANA rules work on Windows and minimal containers.
5. Windows timezone IDs and abbreviations such as `CST` are rejected. IANA aliases accepted by `zoneinfo` are preserved as supplied and resolved by the installed database.
6. A nonexistent local time in a DST gap is rejected with `TEMPORAL_LOCAL_TIME_GAP`.
7. An ambiguous fold requires explicit `fold=0|1` or a numeric UTC offset; otherwise reject with `TEMPORAL_LOCAL_TIME_AMBIGUOUS`.
8. Leap seconds are rejected. Invalid calendar dates are rejected.
9. A backward server-clock movement yields `clock_anomaly=true`, `elapsed_seconds=null`, and `TEMPORAL_CLOCK_ROLLBACK`; elapsed time is never clamped or fabricated.
10. Changing runtime timezone changes future local rendering, not persisted UTC windows or the original creation zone. Changing intended due time requires an explicit reschedule/snooze operation.

### 5.1 Turn-time provenance

- Built-in user turn: server request receipt time.
- Built-in assistant turn: server completion time.
- External user/tool/external turn: signed source-registration issuance may be displayed as source provenance; the durable production event is callback receipt time.
- External assistant turn: server callback receipt time.
- Missing callback: prior turn is `unavailable` with `TEMPORAL_OBSERVATION_MISSING`.
- Delayed callback: timestamp remains callback receipt with `delayed_or_unknown=true`; MNO does not invent model completion time.

## 6. Resolver contract

The storage layer accepts structured temporal input only. It does not run open-ended natural-language or LLM date parsing.

Accepted forms:

1. `local_datetime` plus IANA timezone and optional fold.
2. `local_date`, mapped to the local-day window `[00:00, next 00:00)`.
3. Explicit local/UTC window.
4. Structured relative duration `{amount, unit}` for `minutes|hours|days|weeks`, resolved as elapsed duration from one server snapshot.
5. Structured calendar offset `{amount, unit}` for `days|weeks|months|years` plus optional local time. Calendar month/year arithmetic clamps to the final valid day; Feb 29 plus a non-leap year clamps to Feb 28.
6. Approximate month/year input only when an explicit window is supplied. MNO preserves `precision=approximate`; it never invents an appointment.

`in 24 hours` is elapsed duration. `tomorrow at 09:00` is a local-calendar operation. Past-due creation is allowed within 365 days and is immediately computed overdue; older input requires explicit override. Unsupported or contradictory input fails safely and writes nothing.

All windows are half-open `[start, end)`. An exact local datetime or resolved relative/calendar instant receives the configured one-hour delivery window: `end = start + 1 hour`. A date is its complete local calendar day; an explicit approximate window retains its supplied endpoints. Validation requires `end > start` and both endpoints within the configured past/future horizon. For `snoozed`, `effective_start = snoozed_until_utc` and `effective_end = effective_start + (original_end - original_start)`. Snooze preserves the original window duration and original expression.

## 7. Scope, permissions, concurrency, and quotas

The built-in local runtime uses fixed principal `local-owner` and a stable runtime ID derived from the runtime store. External requests use authenticated principal and runtime claims. Every query supplies all scope keys.

- Viewer: scoped temporal `get`, `list`, due poll.
- Operator/admin: schedule, acknowledge, snooze, cancel, and explicit delivery observation.
- Expiry: maintenance-only.

Writes require an idempotency key. Its namespace is `(store_uuid, principal_id, runtime_id, operation, idempotency_key)`. The canonical request payload is deterministically serialized and SHA-256 digested. Same key plus same digest returns the original stored result before any revision check; same key plus different digest returns `TEMPORAL_IDEMPOTENCY_CONFLICT`. State changes additionally require `expected_revision`; mismatch returns `TEMPORAL_REVISION_CONFLICT`. Record mutation, state-event append, idempotency row, and stored result commit atomically. Terminal states cannot be mutated except by creating a new schedule. The exact idempotency retention rule is defined in the retention paragraph below.

`mno.temporal-state-event.v1` stores event ID, immutable scope, record ID, operation/action, prior/new disposition, prior/new revision, server timestamp, idempotency namespace, payload digest, and sanitized result JSON. It stores no new evidence or conversation content.

Retention is maintenance-driven, never read-driven. Turn-clock and delivery events retain the newest 10,000 rows per scope and rows no older than 10 years; state events retain the complete active-record history, then remain for 10 years after the record's terminal-state timestamp. Idempotency rows for terminal records expire 30 days after terminal-state timestamp; nonterminal rows remain until terminal or 50 years after record creation, whichever occurs first. Hard caps are 100,000 turn events, 100,000 delivery events, and 100,000 state events per scope. An explicit maintenance pass removes oldest eligible terminal-history rows by `(server_timestamp, event_id)` without touching records or evidence. If active state history alone reaches the 100,000 hard cap, the next state write fails closed with `TEMPORAL_STATE_EVENT_CAP_REACHED`; active history is never pruned or silently overwritten.

Locked defaults and hard bounds:

| Control | Default | Hard bound |
|---|---:|---:|
| Total ready-to-inject context | 2,800 estimated tokens | 4,096 estimated tokens |
| Temporal addition | 192 tokens | 256 tokens |
| Due items injected | 3 | 8 |
| Compact due text | 160 UTF-8 bytes | 240 UTF-8 bytes |
| Dormant fallback items | 2 | 4 |
| Active temporal records per scope | 256 | 2,000 |
| Future horizon | 10 years | 50 years |
| Past-due creation | 30 days | 365 days |
| Post-window decay grace | 7 days | 365 days |
| Delivery redelivery interval | 24 hours | 1 hour..30 days |
| Snooze horizon | 10 years | 50 years |
| Turn-clock retention | 10,000 events / 10 years | 100,000 events / 50 years |

No operation may split an item to fit. It drops the lowest-ranked whole section/item and reports truncation counts.

The token estimator is the repository's deterministic `estimate_context_tokens`: canonical JSON (`ensure_ascii=True`, sorted keys, compact separators) followed by the established `[A-Za-z0-9']+` token count. The ready-to-inject surface is the complete serialized `agent_context_v2`, including temporal content. The temporal 192/256 budget is inside, not additional to, the 2,800/4,096 total. Exact bounds are inclusive; a value one unit above fails validation. “UTF-8 bytes” means `len(text.encode("utf-8"))`, never code points.

## 8. State machine and read purity

Legal explicit transitions:

- `none -> scheduled`
- `scheduled -> snoozed|acknowledged|cancelled|expired`
- `snoozed -> snoozed|acknowledged|cancelled|expired`

`acknowledged`, `cancelled`, and `expired` are terminal. Clock passage computes eligibility but performs no transition. `expired` may be written only by explicit maintenance after window end, grace, and retention policy. Acknowledging or cancelling temporal delivery does not delete or canonize the underlying provisional memory.

Read eligibility:

- pending: `now < effective_window_start`
- due: `effective_window_start <= now < effective_window_end`
- overdue: `now >= effective_window_end` while disposition is scheduled/snoozed and not expired
- suppressed: acknowledged/cancelled/expired

## 9. Maintenance and decay

For a pending scheduled or snoozed record, `decay_not_before_utc` is at least due-window end plus configured grace. Maintenance must not move it to dormant or archived before that boundary.

After protection ends, age is computed from:

`max(last_independent_support_at, decay_not_before_utc)`

Snooze may extend the protection boundary but does not change evidence or maturity. Due reads and delivery telemetry do not alter the decay anchor. A newly eligible signed observation may independently reinforce/reactivate through the ordinary v0.2 evidence rules.

## 10. Due injection, canonical arbitration, and dormant fallback

Due selection is scope-filtered, indexed, deterministic, and independent of lexical routing, so due items may appear when the ordinary memory route is `none`. It orders eligible rows by computed class (`overdue` before `due`), then effective window start, created time, and record ID ascending.

Injection order:

1. Human-reviewed canonical conflict/correction facts remain pinned and authoritative.
2. Ordinary reviewed/canonical evidence retains its existing budget.
3. Due provisional notes use their separate temporal budget.
4. Dormant fallback uses its separate lower-priority budget.

A due record is visibly labeled `provisional`, with authority, lifecycle, precision, due window, source citation, and opaque ID. Canonical-conflict association uses exact source/claim identity first and the existing normalized claim key second; it never invents a semantic conflict. Matching canonical corrections remain adjacent and authoritative. Temporal items never displace reviewed canonical items.

Dormant fallback runs only for explicit memory/history requests, a strong normalized phrase/entity/date cue, or an active-result miss. It carries a score penalty and visible lifecycle label. Archived content remains explicit deep/history only.

## 11. Delivery and heartbeat seam

Context build and due poll issue bounded opaque delivery identities inside the signed retrieval receipt but write nothing. `memory.observe` may later record exact-once delivery telemetry. A record with observed delivery is suppressed until `observed_at + redelivery_interval`; absent telemetry is never suppression evidence. If the callback is missing, the item may repeat on later reads; MNO never silently treats it as delivered.

The heartbeat seam is exactly `memory.temporal.list` with `{due_only: true, include_upcoming: false, limit: 3}` under authenticated scope. It is read-only and returns the same contract as ordinary due selection. v0.2.2 does not keep a process awake, wake a model, notify a human, or execute any action.

## 12. API and compatibility

Additive operations:

- `memory.temporal.schedule`
- `memory.temporal.list`
- `memory.temporal.get`
- `memory.temporal.resolve` with action `acknowledge|snooze|cancel`

`context.why` accepts a scoped temporal record/delivery opaque ID and returns the same detailed projection as temporal `get`, plus existing provenance explanation. Guessed cross-scope IDs return not-found without revealing existence.

HTTP and MCP must have parity. `capabilities.get` advertises `temporal_context_v1`, `temporal_memory_v1`, `temporal_due_poll`, and `agent_context_v2`.

Fresh installs and v0.2.1 upgrades enable the compact clock envelope by default. Temporal scheduling/due injection follow the existing provisional-memory enablement; when provisional memory is disabled, the clock remains available but temporal-memory operations return `TEMPORAL_MEMORY_DISABLED`. Legacy response fields remain additive. `agent_context_v2` replaces v0.2.1 imperative prose with neutral facts; no automatic behavior is implied.

If the runtime is not backed by durable SQLite, current clock facts remain available but prior-turn continuity reports `unavailable`, and schedule/state-write operations return `TEMPORAL_DURABLE_STORE_REQUIRED` without writing to an in-memory substitute.

Raw imports remain evidence ingest and can never schedule a temporal memory. Live structured writeback is the only scheduling lane.

## 13. Security, privacy, backup, and backout

Existing content-safety checks apply before original expressions, resolver metadata, state events, turn events, delivery events, receipts, logs, hashes, errors, reports, SQLite/WAL data, and backups are written. Reports include aggregate counts/reason codes only and omit memory text by default.

Temporal fields, turn events, and delivery events live in provisional schema v4, so existing memory-family backup remains atomic without a new sidecar. Migration is transactional and repeat-safe. A verified v3 backup is required before upgrade when a persistent store already exists.

Disabling temporal features is lossless and leaves v4 rows intact. Binary downgrade to v0.2.1 requires restoring the pre-v4 backup and therefore loses post-backup v0.2.2 writes; this is a disclosed, operator-approved RPO event. No in-place schema downgrade or row deletion is supported.

## 14. Required verification gates

Release is blocked unless all are green:

- v3 -> v4 fresh/repeat/crash/backup/restore/WAL migration tests
- DST gap/fold, month-end, leap-day, relative-duration, past-due, timezone-fallback tests
- server-clock provenance, restart continuity, missing/delayed callback, and clock-rollback tests
- principal/runtime/store isolation, session attribution-integrity/non-authorization, and authorization tests
- idempotency retention/replay ordering, revision conflict, concurrent transition, and quota tests
- no-cue due injection, canonical conflict pinning, dormant fallback, archived exclusion tests
- read-only equality and full zero-drift projection tests across context, rendering, polls, repeated delivery, and observation callbacks: support counts/timestamps, maturity, authority, lifecycle, lineage/source references, evidence rows, decay anchor, record revision, confidence, stability, salience, and `updated_at` remain unchanged
- exact context token/item/UTF-8 bounds and whole-section truncation tests
- prompt-shaped reminder inertness, secret redaction, report privacy, and backup scans
- HTTP/MCP/capability parity and blind-LLM comprehension tests
- no daemon/thread/network activity test
- full Python, desktop, packaging, isolated wheel/sdist, and supported OS/Python CI matrix
- docs, examples, canonical `.drawio`, generated exports, links, versions, release artifacts, and fresh-clone smoke

## 15. No-touch boundaries

v0.2.2 must not rewrite canonical review, publish/verify/activate gates, raw ingest semantics, global canonical retrieval ranking, desktop global UI, MCP installation/activation, or external services. Changes outside the explicit temporal/runtime/provisional/docs/release ledger require a written blockerboard entry and renewed review.

## 16. Release definition of done

`v0.2.2` is release-green only after DEV passes every gate, the reviewed file ledger alone is staged into CLEAN, PR review and CI are green, the PR is merged and closed, tag and release artifacts agree, and a fresh public clone passes the documented temporal smoke. Until then the blockerboard status remains open.
