# Plan: MNO v0.2.2 Temporal Agency and Prospective Memory

**Generated**: 2026-07-18
**Estimated Complexity**: High
**Release target**: `v0.2.2`
**Implementation posture**: DEV-first in `Z:\modelNumquamOblita`; `Z:\numquamoblita-clean` remains the clean publication/staging mirror only.

## Overview

MNO v0.2.2 should give an integrated agent a durable, trustworthy relationship with time without weakening MNO's evidence contract. The release combines four related capabilities:

1. A fresh temporal envelope on every ordinary context build: current local time, timezone, known prior-turn timestamps, and elapsed durations.
2. Prospective provisional memory: source-backed notes about future events or reminders with a temporal horizon.
3. Time-aware maintenance and retrieval: future-dated memories do not decay before they become relevant; due memories surface automatically and dormant memories remain available through bounded cue-aware recall.
4. An explicit future heartbeat seam: hosts may poll due memories, while v0.2.2 itself introduces no background daemon or unsolicited external action.

This is not a calendar replacement and does not make model-generated text canonical. Temporal state changes availability; it never creates evidence, increases evidentiary maturity, or mutates human-reviewed truth.

## Locked Terms and State Axes

The implementation and documentation must keep these dimensions independent:

| Dimension | States | Meaning |
|---|---|---|
| Authority | `human_reviewed_canonical`, `evidence_atom`, `provisional_consolidated`, `provisional_observed` | Who/what may be trusted as truth |
| Evidentiary maturity | `observed`, `reinforced`, `consolidated` | Amount of independent support |
| Memory lifecycle | `active`, `dormant`, `archived` | Ordinary retrieval availability |
| Persisted temporal disposition | `none`, `scheduled`, `acknowledged`, `snoozed`, `cancelled`, `expired` | Explicit temporal command state |

`due`, `pending`, `overdue`, and `upcoming` are read-only computed eligibility labels, not persisted states. The locked specification at `docs/MNO_V0_2_2_TEMPORAL_AGENCY_SPEC_2026-07-18.md` is normative wherever this planning document is less specific.

Retrieval, rendering, due delivery, acknowledgement, snoozing, and clock passage are never independent evidence. A newly observed user/tool/external confirmation may reinforce and reactivate memory through the existing signed evidence path.

## Scope

### In scope

- Fresh per-context local clock data and elapsed-turn context.
- Explicit IANA timezone configuration with a safe system-local fallback and visible effective-policy diagnostics.
- Durable, content-minimal turn-clock events for elapsed-time continuity across process restarts.
- Structured future-event/reminder creation in provisional space.
- Preservation of the original temporal expression, parsing/resolution audit, precision, and timezone.
- Decay protection through the due horizon and a bounded grace period.
- Automatic bounded injection of due provisional memories into normal context packages, even without a lexical memory cue.
- Penalized, cue-aware dormant fallback without making dormant memory an ordinary high-priority result.
- Explicit acknowledge, snooze, cancel, inspect, and due-list operations.
- HTTP/MCP/built-in runtime parity.
- `mno-report` temporal diagnostics, public docs, LLM docs, flowcharts, release notes, migration, packaging, and portability proof.

### Deferred

- A resident background daemon that wakes an inactive model.
- Calendar/email/message integrations or any unsolicited external side effect.
- Recurring reminders beyond a deliberately small, separately specified extension.
- Semantic LLM date parsing inside the storage layer.
- Automatic conversion of arbitrary historical imports into reminders.
- Automatic human-reviewed publication.

## Non-Negotiable Invariants

- `context.build`, search, due-list, and diagnostics remain read-only.
- The server clock controls `now`, elapsed duration, due eligibility, maintenance, and decay. Callers cannot override production time.
- Local time is the model-facing representation, but persisted ordering uses UTC plus the originating IANA timezone.
- Timezone is configured; it is never inferred from IP address, geolocation, or private user data.
- Due delivery never increments support or maturity and never reactivates a record as evidence.
- Delivery telemetry is separate from evidence and does not modify `last_independent_support_at`.
- A pending temporal memory cannot become dormant or archived before its protected horizon.
- When protection ends, decay age starts from the effective decay anchor; the record must not instantly age by the entire pre-due waiting period.
- Source references, temporal events, and archived records are retained; maintenance does not delete them.
- Human-reviewed canonical truth continues to outrank every provisional record.
- Context injection is not authorization to contact a user or execute an external action.
- Every list/injection path is bounded, scope-isolated, secret-safe, and deterministic under an injected test clock.

## Prerequisites

- Reconcile the DEV implementation base against released CLEAN `v0.2.1` (`190e056`) before temporal code is written. Current DEV HEAD is behind the public merge and contains broad unrelated dirty state; no whole-file copy or reset is acceptable.
- Preserve every unrelated DEV change and every existing checkpoint track.
- Lock a v0.2.2 spec, execution checklist, blockerboard, migration plan, and test map before implementation.
- Confirm Windows, Linux, and macOS timezone data behavior. If the Python runtime cannot guarantee IANA data, add the lightweight `tzdata` package and prove packaged installs.
- Use injected clocks in tests; do not use sleeps or the model's claimed current time.

## Sprint 0: Baseline, Reconciliation, and Spec Lock

**Goal**: Establish a safe v0.2.1 DEV baseline and freeze the exact v0.2.2 contract before implementation.

**Demo/Validation**:

- Show a file-level reconciliation ledger for every temporal touchpoint.
- Run the released v0.2.1 provisional, integration-contract, runtime-context, MCP, migration, and packaging gates from the reconciled DEV base.
- Review the locked spec for authority drift, self-echo, daemon creep, and context-write violations.

### Task 0.1: Reconcile DEV to the released v0.2.1 base

- **Location**: `engine/memory/**`, `engine/runtime/session.py`, `engine/runtime/server.py`, `engine/mcp/server.py`, `engine/config.py`, `engine/contracts.py`, relevant tests and docs
- **Description**: Use CLEAN `190e056` as release truth, preserve newer valid DEV work as reviewed hunks, and eliminate stale/regressed v0.2 memory behavior before adding temporal changes.
- **Complexity**: 8/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - DEV remains the working SSoT and CLEAN is unchanged.
  - No unrelated dirty work is discarded or overwritten.
  - Existing v0.2.1 behavior is test-green in DEV.
- **Validation**: Focused v0.2.1 suites, `git diff --check`, reconciliation report, checkpoint snapshot.

### Task 0.2: Lock the temporal-agency specification package

- **Location**: `docs/MNO_V0_2_2_TEMPORAL_AGENCY_SPEC_2026-07-18.md`, matching execution checklist, blockerboard, and test map
- **Description**: Convert this plan into normative contracts, state machines, request/response examples, no-touch boundaries, and release gates.
- **Complexity**: 6/10
- **Dependencies**: Task 0.1 behavior map
- **Acceptance Criteria**:
  - Explicitly answers ambiguous dates, approximate dates, timezone changes, DST, overdue items, acknowledgement, snooze, cancellation, expiry, and missing observation callbacks.
  - Explicitly defers the heartbeat daemon while retaining a polling seam.
  - Contains no placeholder or contradictory authority language.
- **Validation**: Independent spec review plus invariant/placeholder scans.

## Sprint 1: Trustworthy Clock and Durable Turn-Time Envelope

**Goal**: Every ordinary context package tells the agent what time it is and, when known, how long it has been since the previous user and assistant turns.

**Demo/Validation**:

- Build a context package, advance an injected clock by two days, rebuild it, and show correct local timestamps and elapsed durations.
- Restart the runtime and show that prior-turn timing survives without persisting message content in the temporal ledger.

### Task 1.1: Add clock and timezone contracts

- **Location**: `engine/config.py`, `engine/contracts.py`, new `engine/runtime/temporal.py`
- **Description**: Add an injectable clock, validated IANA timezone policy, local rendering, UTC persistence helpers, precision types, clock-anomaly handling, and a typed `TemporalContextContract`.
- **Complexity**: 6/10
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - Default configuration resolves a visible effective timezone without geolocation.
  - Invalid zones fail preflight with a useful error.
  - DST folds/gaps, leap days, and backward clock movement have deterministic behavior.
- **Validation**: Unit tests for timezone resolution, DST, clock rollback, and serialization.

### Task 1.2: Persist content-minimal turn-clock events

- **Location**: content-minimal temporal tables in provisional schema v4; `engine/runtime/session.py`; integration observation path
- **Description**: Persist scoped opaque turn/session IDs, role, event time, principal/runtime/store identity, and completion state without duplicating conversation content.
- **Complexity**: 7/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Previous user/assistant timestamps survive restart.
  - Cross-principal, cross-store, and cross-runtime leakage is impossible; optional session attribution retains integrity but is not an authorization boundary.
  - Retention and caps are validated and observable.
  - `context.build` performs no write; built-in completion and explicit observation record turn events.
- **Validation**: Restart, isolation, retention, and read-only-context integration tests.

### Task 1.3: Add the temporal envelope to every normal context surface

- **Location**: `engine/runtime/session.py`, `engine/runtime/server.py`, `engine/mcp/server.py`, responder prompt construction, context schemas
- **Description**: Return structured `temporal_context` in context v1/v2 and integration envelopes, and render a compact model-facing header with now-local, timezone, previous-turn times, and elapsed duration.
- **Complexity**: 6/10
- **Dependencies**: Tasks 1.1-1.2
- **Acceptance Criteria**:
  - Current local time is always present.
  - Prior-turn and elapsed fields are present only when supported and otherwise carry an explicit unavailable reason.
  - Guidance treats gaps as awareness, not automatic emotional inference.
- **Validation**: Contract snapshots, built-in chat test, HTTP/MCP parity, token-budget assertion.

## Sprint 2: Prospective Provisional Memory

**Goal**: An agent can create a source-backed future event or in-context reminder that remains provisional but is durable until its relevant horizon.

**Demo/Validation**:

- Schedule “check on the new job in six months” using a signed source registration.
- Inspect the record and show its original phrase, resolved local/UTC time, precision, source, authority, maturity, lifecycle, and temporal state.

### Task 2.1: Add schema v4 temporal fields and event tables

- **Location**: `engine/memory/provisional_store.py`, backup/migration paths
- **Description**: Add first-class temporal fields and separate delivery/state-event storage. Minimum fields include immutable owner scope, temporal kind, persisted disposition, due-window start/end UTC, timezone, original local expression, precision, decay-not-before/grace anchors, snooze time, revision, idempotency, and resolution metadata.
- **Complexity**: 8/10
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Existing v3 rows migrate transactionally to `temporal_kind=none` without semantic change.
  - Delivery/access events cannot change evidence counts, timestamps, maturity, or authority.
  - Backup, restore, move, rollback, and repeated migration are safe.
- **Validation**: Fresh install, v3 upgrade, rollback injection, backup/restore, and secret scans.

### Task 2.2: Add explicit temporal-memory operations

- **Location**: `engine/runtime/session.py`, `engine/runtime/server.py`, `engine/mcp/server.py`, API contracts
- **Description**: Add create/schedule, inspect, list-due, acknowledge, snooze, cancel, and expire operations with HTTP/MCP parity. Use server time to resolve relative durations and preserve the original source wording.
- **Complexity**: 8/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Agent-autonomous scheduling creates provisional helper memory, never canonical truth.
  - User-requested reminders do not require repeated evidence merely to survive until due.
  - Ambiguous input remains approximate or requires clarification; it is never silently given false precision.
  - Operations are authenticated, scoped, quota-bounded, idempotent, and content-safe.
- **Validation**: API/MCP parity, authorization, replay, ambiguity, quota, and principal-isolation tests.

### Task 2.3: Teach observation and extraction about temporal intent

- **Location**: ingest/extractor and runtime observation paths
- **Description**: Preserve timestamps on ordinary observations and allow a model to attach a structured, source-backed temporal proposal. Avoid broad natural-language scheduling from raw imports.
- **Complexity**: 7/10
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Explicit “remember/check this later” live turns use the temporal write path.
  - Raw conversation-shaped imports remain evidence ingest, not executable reminders.
  - Retrieved or assistant-derived text cannot schedule or reinforce itself without a valid signed source path.
- **Validation**: Live-writeback vs raw-import integration tests and anti-echo tests.

## Sprint 3: Time-Aware Maintenance and Reversible Forgetting

**Goal**: Future relevance protects a provisional memory without falsely increasing its evidentiary support.

**Demo/Validation**:

- Advance the clock past the ordinary 90-day dormancy threshold but before a six-month due date; the record remains eligible and scheduled.
- Advance past due plus grace; normal decay begins from the effective decay anchor rather than the original six-month-old support timestamp.

### Task 3.1: Add temporal protection to maintenance

- **Location**: `engine/memory/provisional_maintenance.py`, policy config and diagnostics
- **Description**: Skip dormancy/archive transitions while `now < decay_not_before`. After the protected horizon, compute decay from `max(last_independent_support_at, decay_not_before)`.
- **Complexity**: 6/10
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Scheduled memories cannot decay before their horizon.
  - Snoozing adjusts availability/protection but not evidence.
  - Cancelled/expired/acknowledged memories return to documented lifecycle behavior.
  - Maintenance remains explicit, deterministic, bounded, durable, and idempotent.
- **Validation**: Injected-clock boundary matrix and maintenance replay tests.

### Task 3.2: Preserve reactivation semantics

- **Location**: provisional store/observation/maintenance paths
- **Description**: Keep delivery and recall separate from evidentiary reactivation. Only new signed independent support may reinforce/reactivate as evidence; temporal due state may make a record available without rewriting its maturity.
- **Complexity**: 5/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Due delivery leaves support counts unchanged.
  - User confirmation through a new evidence unit reactivates and may reinforce.
  - Replay, quotation, and model summary remain zero-support.
- **Validation**: Anti-self-echo and new-evidence reactivation regression tests.

## Sprint 4: Due Injection and Cue-Aware Dormant Recall

**Goal**: Relevant temporal memory reaches the model when it matters, while dormant memory remains safely recallable rather than functionally invisible.

**Demo/Validation**:

- On the due date, an unrelated normal context build receives a bounded `temporal_due` item.
- A strong six-month-old cue retrieves a dormant record with a visible penalty/label but does not reinforce it.

### Task 4.1: Build bounded due-memory selection

- **Location**: provisional store queries, runtime context assembly, retrieval receipts
- **Description**: Select due records by scope/time independently of lexical routing, rank overdue/due windows deterministically, cap items/tokens, and include provisional labels/citations.
- **Complexity**: 8/10
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Due items can appear even when the ordinary LTM router would skip retrieval.
  - Human-reviewed conflicts remain visible and authoritative.
  - Signed receipts carry due-record delivery IDs so the later explicit observation may record non-evidentiary delivery telemetry.
  - Missing observation callbacks may cause safe repeated delivery but never hidden state mutation.
- **Validation**: No-cue due injection, caps, ordering, conflict, receipt, restart, and read-only-context tests.

### Task 4.2: Add penalized dormant fallback

- **Location**: `engine/memory/provisional_store.py`, `engine/runtime/session.py`, retrieval diagnostics
- **Description**: Replace categorical dormant exclusion with a bounded fallback triggered by explicit recall, strong entity/date/phrase cues, or inadequate active results. Archived records remain explicit deep/history only.
- **Complexity**: 7/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Dormant results carry lifecycle labels and a configurable penalty.
  - Dormant fallback cannot crowd out stronger active/canonical evidence.
  - Search/access remains read-only and non-reinforcing.
- **Validation**: Strong-cue hit, weak-cue miss, active dominance, archived exclusion, and token-budget tests.

### Task 4.3: Add acknowledgement and reminder backoff behavior

- **Location**: temporal state/event APIs and runtime due selection
- **Description**: Suppress acknowledged/cancelled items, honor snooze, and apply bounded redelivery intervals using explicit post-turn delivery telemetry rather than writes during context reads.
- **Complexity**: 6/10
- **Dependencies**: Tasks 4.1-4.2
- **Acceptance Criteria**:
  - Acknowledged/cancelled reminders stop appearing.
  - Snoozed reminders return at the new horizon.
  - Failure to record delivery degrades to bounded repetition, not silent loss.
- **Validation**: State transition, idempotency, backoff, and crash/retry tests.

## Sprint 5: Integrator Experience, Reporting, and Heartbeat Seam

**Goal**: An integrating agent understands and can operate temporal memory without bespoke Lux/Hermes code.

**Demo/Validation**:

- Follow one LLM-facing quickstart to read the clock, schedule a provisional reminder, list due items, acknowledge it, and submit a diagnostic report.

### Task 5.1: Provide integration bundles and examples

- **Location**: `docs/AGENT_INTEGRATION.md`, `docs/API.md`, `docs/MCP_INTEGRATION.md`, integration-bundle tools/resources
- **Description**: Add stable request/response examples, capability discovery, compatibility fallbacks, and a complete temporal-memory round trip.
- **Complexity**: 5/10
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Generic HTTP/MCP clients require no vendor-specific executable.
  - Unsupported v0.2.1 clients continue to function without temporal fields.
  - Temporal features are capability-discoverable and additive.
- **Validation**: Blind integration fixture and packaged-bundle smoke.

### Task 5.2: Extend `mno-report` diagnostics

- **Location**: `tools/report_issue.py`, `docs/SUPPORT_TICKETS_FOR_AGENTS.md`, report tests
- **Description**: Capture redacted timezone/effective-clock policy, temporal schema version, due counts by state, maintenance protection diagnostics, and recent reason codes—never memory content or secrets by default.
- **Complexity**: 4/10
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - A report can distinguish parsing, timezone, decay, due-selection, delivery, and integration-callback failures.
  - Logs remain portable and privacy-safe.
- **Validation**: Snapshot, redaction, absent-runtime, and cross-platform report tests.

### Task 5.3: Add a heartbeat-ready read seam without a daemon

- **Location**: due-list/poll contract and capability metadata
- **Description**: Expose a bounded read-only “what is due now?” operation suitable for a future host heartbeat. Document that v0.2.2 does not wake inactive models or perform external actions.
- **Complexity**: 3/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Polling is idempotent and read-only.
  - No timer thread, daemon, recursive loop, or unsolicited network action ships.
- **Validation**: Repeated poll equality and idle-process tests.

## Sprint 6: Documentation, Flowcharts, and Model Comprehension

**Goal**: Humans and LLMs can correctly explain temporal agency, including its limitations and trust boundaries.

**Demo/Validation**:

- A blind LLM can answer what now-local means, how a reminder survives decay, when a due memory appears, why recall is not reinforcement, and what the heartbeat seam cannot do.

### Task 6.1: Update canonical and public documentation

- **Location**: `README.md`, `LLMS.md`, `docs/public/ARCHITECTURE.md`, `docs/QUICKSTART.md`, `docs/CONFIGURATION.md`, `docs/SECURITY_AND_PRIVACY.md`, `docs/TROUBLESHOOTING.md`, `DISTRIBUTION.md`
- **Description**: Explain temporal envelope, prospective memory, local-time presentation/UTC plumbing, lifecycle behavior, due injection, cue-aware dormancy, acknowledgement, and external-action boundaries.
- **Complexity**: 5/10
- **Dependencies**: Sprints 1-5
- **Acceptance Criteria**:
  - `LLMS.md` contains a direct “If you are an LLM” temporal operation guide.
  - No doc implies due delivery is canonical truth or an external notification.
  - Examples use local time and show approximate-date handling honestly.
- **Validation**: Link/schema/example scans and blind-LLM comprehension gate.

### Task 6.2: Correct and extend flowcharts

- **Location**: `docs/visuals/*.drawio`, visual specs, PNG/SVG exports, visual README/index
- **Description**: Visually show the four independent axes, temporal envelope per turn, scheduled-to-due flow, decay hold, due injection, dormant fallback, new-evidence reactivation, and deferred heartbeat boundary.
- **Complexity**: 6/10
- **Dependencies**: Locked final behavior
- **Acceptance Criteria**:
  - Both engineering and caveman-readable diagrams visibly include lifecycle and temporal states.
  - Source diagrams and exported assets agree.
  - Canonical review remains visually above provisional memory.
- **Validation**: Export script, asset existence/hash checks, desktop/mobile visual inspection.

## Sprint 7: Portability, Release, and Publication

**Goal**: Publish a reproducible v0.2.2 release from the clean mirror only after DEV is fully green.

**Demo/Validation**:

- Install the wheel/sdist in fresh Windows, Linux, and macOS environments; build context across a simulated two-day gap; schedule a six-month memory; cross dormancy thresholds; surface it when due; and verify zero authority/reinforcement drift.

### Task 7.1: Run the full temporal and regression matrix

- **Location**: all affected tests and CI workflows
- **Description**: Run unit, integration, migration, packaging, desktop, security, blind-LLM, performance, and cross-platform timezone tests.
- **Complexity**: 7/10
- **Dependencies**: Sprints 1-6
- **Acceptance Criteria**:
  - Full Python and desktop suites are green.
  - Windows/macOS/Linux setup and timezone cases are green.
  - Context-token and retrieval-latency budgets remain within locked limits.
  - No canonical/review/publish mutation occurs in temporal tests.
- **Validation**: CI matrix and durable release evidence.

### Task 7.2: Stage the reviewed DEV slice into CLEAN

- **Location**: `Z:\numquamoblita-clean`
- **Description**: Copy only reviewed release files/hunks after DEV completion, prove scope equivalence, update version metadata and `docs/RELEASE_NOTES_v0.2.2.md`, and leave DEV as the development SSoT.
- **Complexity**: 6/10
- **Dependencies**: Task 7.1
- **Acceptance Criteria**:
  - CLEAN begins clean and contains only release-ready files.
  - No DEV runtime data, checkpoints, secrets, personal datasets, or raw logs cross the boundary.
  - Source/version/package/docs consistency checks pass.
- **Validation**: Diff-scope audit, secret scan, build artifacts, install smoke.

### Task 7.3: PR review, CI loop, merge, tag, and release

- **Location**: GitHub PR/release surfaces
- **Description**: Run `pr-review-ci-loop`, resolve actionable review and CI findings, merge, tag `v0.2.2`, publish artifacts and human-readable changelog, then verify the public repo from a fresh clone.
- **Complexity**: 6/10
- **Dependencies**: Task 7.2
- **Acceptance Criteria**:
  - Required checks and review threads are green/resolved.
  - Tag, release, wheel, sdist, version metadata, docs, and hashes agree.
  - Public fresh-clone temporal smoke passes.
- **Validation**: GitHub release verification and post-merge checkpoint.

## Required End-to-End Scenarios

1. **Three-day conversation gap**: the next context contains now-local and elapsed time; the agent is aware but is not instructed to infer distress.
2. **Six-month autonomous note**: model-created provisional reminder survives the 90-day dormancy window and surfaces when due.
3. **Explicit user reminder**: the user asks to remember a future event; the live temporal write path is used rather than raw import or canonical publication.
4. **Due without lexical cue**: a due item is injected even when the new message contains no matching terms.
5. **Dormant cue recall**: a strong cue retrieves a dormant record with a penalty and visible lifecycle label.
6. **No self-reinforcement**: delivery, quotation, replay, and assistant repetition change no evidence counts.
7. **Confirmation reactivation**: new signed user confirmation reactivates/reinforces through ordinary evidence rules.
8. **Timezone/DST**: a local-time reminder retains intended meaning across DST and restart.
9. **Approximate date**: “in about six months” remains approximate and is not rendered as a fabricated exact appointment.
10. **Read-only context**: repeated context builds and due polls produce no state mutation.
11. **Acknowledgement/snooze/cancel**: explicit state writes alter delivery behavior but not maturity or authority.
12. **No scheduler overclaim**: an inactive model is not claimed to have been awakened; a host poll demonstrates the future heartbeat seam.

## Testing Strategy

- TDD for every schema/state transition and retrieval boundary.
- One injectable clock shared by runtime, maintenance, temporal resolution, and tests.
- Transactional migration and crash-injection tests.
- Property/boundary tests for temporal ordering and non-negative elapsed durations.
- Cross-platform IANA timezone/DST matrix.
- API/MCP parity tests from one contract source.
- Scope, authorization, quota, content-safety, and secret-redaction tests.
- Blind-LLM comprehension tests against `LLMS.md` and integration examples.
- Performance gates for due-query indexes, dormant fallback, context tokens, and startup.
- Full existing authority, provisional consolidation, writeback, review, publish, WSS, retrieval, desktop, packaging, and report regressions.

## Potential Risks and Mitigations

- **Context writes violate INV-010**: record turn/delivery events only during explicit built-in completion or observation writes; keep context/due reads pure.
- **Reminder spam/context flooding**: per-scope creation limits, due caps, token budgets, explicit acknowledgement, snooze, and delivery backoff.
- **False date precision**: preserve original expression and precision; require clarification or an approximate window when resolution is ambiguous.
- **DST/timezone drift**: persist UTC instant plus IANA zone and local expression; specify fixed-zone semantics and require explicit rescheduling for changed intent.
- **Self-echo reinforcement**: delivery IDs ride signed receipts; access telemetry is separate; only new signed source evidence changes support.
- **Future memory instantly decays after due**: compute age from the effective decay anchor, not only the ancient support timestamp.
- **Dormant fallback overwhelms authority**: strict trigger, lower score, small cap, visible lifecycle, and canonical dominance.
- **Cross-platform timezone failure**: preflight IANA availability and package `tzdata` if required.
- **Heartbeat scope creep**: ship only the read-only poll seam in v0.2.2.
- **Dirty DEV/CLEAN confusion**: mandatory baseline reconciliation and release-scope ledger before implementation or staging.

## Rollback Plan

- Make temporal fields additive and preserve v3-compatible defaults (`temporal_kind=none`).
- Gate temporal envelope rendering, prospective scheduling, due injection, and dormant fallback with separate validated feature flags.
- A rollback disables new behavior without deleting temporal rows or source lineage.
- Schema downgrade is not performed in place; restore from the pre-migration consistent backup when rollback requires the earlier binary.
- Never roll back by deleting provisional events, evidence units, canonical data, or review history.

## Release Definition of Done

v0.2.2 is complete only when:

- every normal context package provides trustworthy current local time;
- elapsed conversation time survives restart when completed-turn observations exist;
- future provisional memories survive until their relevant horizon;
- due memories can enter context automatically and boundedly;
- dormant records are cue-recallable but penalized;
- retrieval/delivery never reinforces evidence;
- new independent evidence can reactivate/reinforce;
- human-reviewed canonical truth remains authoritative and untouched;
- generic HTTP/MCP integrations, `mno-report`, LLM guidance, flowcharts, migrations, packaging, and cross-platform CI are green;
- DEV-to-CLEAN scope is proven; and
- PR review, merge, tag, published artifacts, public docs, and fresh-clone smoke are complete.
