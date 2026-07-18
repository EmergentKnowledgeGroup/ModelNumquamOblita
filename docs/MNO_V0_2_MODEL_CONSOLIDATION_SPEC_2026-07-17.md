# MNO v0.2 Model-Consolidated Memory Specification

Status: **LOCKED for implementation**
Release target: `v0.2.0`
Date: 2026-07-17

SpecSwarm complexity: **5/5 — hard**. The release crosses storage schemas, evidence semantics, runtime/API/MCP/desktop wiring, security-sensitive evidence mutation, compatibility, documentation, packaging, and real public release proof.

## 1. Decision

MNO may autonomously mature evidence-backed provisional observations into labeled, revisable model-consolidated memory, but consolidation never creates canonical truth, never supplies its own evidence, and never outranks human-reviewed memory.

This release restores the original biological-memory direction without weakening MNO's evidence contract. Repeated independent evidence may make a provisional memory more stable and more retrievable. It may not let a model manufacture authority by repeating, recalling, or summarizing its own output.

## 2. Why v0.2 exists

The v0.1 implementation contains a useful provisional-memory foundation, but the shipped behavior and public integration contract stop short of the intended system:

- provisional capture and retrieval ship disabled;
- the stock runtime launcher cannot load the provisional-memory configuration;
- an external model can retrieve context but cannot report a completed turn through a stable public observation API;
- repeated text increments reinforcement even when it reuses the same evidence;
- there is no distinct model-consolidated tier;
- there is no bounded consolidation/decay pass;
- public writeback approval does not apply an approved mutation to the durable evidence-atom store;
- the durable evidence mutation-review queue is process-local, so pending and approved proposals disappear on restart;
- the primary external context contract neither retrieves provisional memory nor exposes its trust/conflict labels;
- public documentation makes the human-review path visible but does not clearly teach the autonomous provisional path.

The result is a gap between the source design and what an integrating model such as Lux can actually operate.

## 3. Source design recovered

The original MNO documents consistently require all of the following:

1. Memory claims remain evidence-backed.
2. The model owns a revisable helper-memory layer beneath reviewed truth.
3. Repeated episodic signals may mature into stable semantic memory.
4. Corrections, contradictions, and earlier states remain inspectable.
5. Forgetting reduces priority or archives helper memory; it does not erase evidence.
6. System time, not model intuition, controls reinforcement and decay.
7. Human review remains authoritative for canonical truth.

The March provisional-memory slice intentionally deferred decay, reinforcement policy, and consolidation. v0.2 implements that deferred maturation layer. It does not implement autonomous publication.

Research alignment:

- [CoALA](https://arxiv.org/abs/2309.02427) treats language agents as systems with explicit memory and learning actions around the language model, which supports making observation and consolidation first-class operations rather than hidden prompt behavior.
- Human-memory reconsolidation research ([review](https://pmc.ncbi.nlm.nih.gov/articles/PMC2992451/), [updating study](https://pmc.ncbi.nlm.nih.gov/articles/PMC4588064/), [false-memory study](https://pmc.ncbi.nlm.nih.gov/articles/PMC3411412/)) shows that recall can update and distort memory, which supports immutable source lineage and contradiction visibility.
- [TrustMem](https://arxiv.org/abs/2606.25161) demonstrates that autonomous memory transitions can create persistent omission, corruption, and hallucination failures, which supports deterministic transition checks and inspectable provenance.

## 4. Non-negotiable invariants

### INV-001 — Evidence before memory

Every provisional observation and every consolidated artifact must retain source references. A consolidated artifact's generated wording is never evidence for itself or its inputs.

### INV-002 — Authority is not maturity

Canonical authority, provisional maturity, and lifecycle status are separate dimensions. More reinforcement may increase provisional maturity. It never changes authority to canonical.

### INV-003 — Human-reviewed published truth wins

When human-reviewed published memory and lower tiers conflict, published memory wins ranking authority. An explicitly approved writeback atom is durable evidence substrate, not a shortcut to published truth and not itself `human_reviewed`. The conflict and lower-authority evidence remain inspectable.

### INV-004 — No self-echo reinforcement

Retrieval, replay, quotation, model summary, and model-consolidated output do not create independent support. Reprocessing the same evidence unit is idempotent.

### INV-005 — Append-preserving lineage

Consolidation creates a derived object linked to its input observations. It does not overwrite those observations. Correction and supersession preserve both ends of the transition.

### INV-006 — Contradiction remains visible

Unresolved incompatible evidence blocks consolidation in v0.2. Both sides remain visible; generated conflict-aware synthesis is deferred.

### INV-007 — Forgetting is reversible demotion

Decay may lower retrieval weight or move provisional objects to dormant or archived states. It may not delete source refs, event history, or canonical truth. New independent evidence may reactivate a dormant or archived provisional object.

### INV-008 — Bounded autonomous work

Observation and consolidation are deterministic, capped, feature-configurable, and auditable. No unbounded daemon or recursive model loop is introduced.

### INV-009 — Existing release gates remain intact

Provisional observation, reinforcement, consolidation, decay, and retrieval may not mutate `review_decisions`, publish state, activation state, or the live published pointer.

### INV-010 — Read operations do not write

`context.build`, retrieval, explanation, diagnostics, and history are read-only. They do not change memory, receipt, review, publish, activation, access, reinforcement, or decay state. Observation and maintenance require explicit write operations.

## 5. Memory model

### 5.1 Authority tiers

| Tier | Meaning | May support an answer? | May override canonical? |
|---|---|---:|---:|
| `human_reviewed_canonical` | Human-reviewed, published memory produced by the normal build/review/publish pipeline | Yes; highest authority | N/A |
| `evidence_atom` | Durable atom materialized after explicit reviewer apply; evidence substrate with `human_reviewed=false`, not published truth | Yes, with evidence provenance | No |
| `provisional_consolidated` | Derived synthesis with independent supporting evidence | Yes, with provisional label and underlying citations | No |
| `provisional_observed` | Direct evidence-backed observation | Yes, with provisional label | No |

`proposal_pending` is queue state, not authority. STM and WSS are scoped helper context, not evidence tiers; they may guide in-session work but cannot support a durable factual memory claim.

### 5.2 Maturity

`observed -> reinforced -> consolidated`

- `observed`: one independent evidence unit.
- `reinforced`: at least two independent evidence units or a stricter per-kind threshold.
- `consolidated`: a separate derived artifact created from eligible reinforced observations.

Maturity describes support and persistence, not factual certainty. Human approval of an evidence atom and human-reviewed publication are separate transitions.

### 5.3 Lifecycle

`active -> dormant -> archived`

Authority tier, maturity, lifecycle, conflict state, and supersession linkage are stored as separate fields. Orthogonal relationship states remain available:

- `superseded`
- `conflicted`

An object may be reactivated only by new independent evidence. Retrieval/access alone is not reactivation evidence.

### 5.4 Consolidated artifact

A consolidated artifact is a distinct provisional object with:

- deterministically selected/normalized `summary_text`; legacy `canonical_text` means normalized display wording, never authority;
- `authority_tier=provisional_consolidated`;
- `derived=true` and `human_reviewed=false`;
- input provisional record IDs;
- all supporting source references;
- distinct evidence and session counts plus authenticated actor/runtime audit identity;
- opposing/conflicting record IDs when applicable;
- derivation timestamp;
- policy version and reason codes;
- maturity/lifecycle state;
- score components;
- deterministic consolidator/runtime/policy identifiers.

The implementation must preserve its input observations and reject an artifact with no surviving external evidence.

Self-claims may mature provisionally but cannot enter the direct provisional-to-evidence bridge in v0.2. They require the normal higher-friction review/build path.

## 6. Independent evidence

### 6.1 Evidence-unit identity

The deterministic evidence fingerprint is derived from:

```text
store_namespace | source_id | message_id | span_start | span_end |
source_role | normalized_content_digest
```

`session_id` is recorded but is not sufficient by itself to make replayed evidence independent. Every store persists a stable random store UUID. Actor/runtime identity is derived from the authenticated principal/runtime configuration, not arbitrary payload fields. Missing message IDs use a stable conservative fallback that may identify a first support unit but can never create additional independent support. Caller IDs without a server-issued signed source-registration handle are provenance labels, not independent-support authority and return support delta `0`. Reusing one registered source/message/span identity with different content returns `409 EVIDENCE_IDENTITY_CONFLICT` and writes nothing.

Source registration is stateless and signed with the same runtime control key as retrieval receipts:

- built-in chat registers its server-owned turn internally;
- `context.build` automatically returns a user `source_registration` bound to its sanitized input message, server-issued/stable source and message IDs, content digest, authenticated principal/runtime, session/run, store UUID, role, issue/expiry, and policy version;
- `POST /api/integration/v1/memory/source/register` registers a sanitized user/tool/external-source span without capturing or reinforcing memory and returns the same signed handle shape;
- MCP parity is `integration.memory.source.register`;
- `memory.observe.messages[]` carries `source_registration` for user/tool/external evidence; MNO verifies role, content digest, principal/runtime, session/run, store, expiry, and policy binding after restart;
- assistant text is bound to the observed turn and receipt rules, not the user/tool registration endpoint.

### 6.2 Counting rules

- The first unseen evidence fingerprint creates one independent support unit.
- Replaying the same fingerprint changes no independent-support count.
- Same-session repetition with a genuinely new source/message may be recorded, but consolidation requires the configured distinct-session floor.
- `context.build` returns a stateless signed `retrieval_receipt`. `memory.observe` references that receipt, and MNO verifies and resolves the actual retrieved evidence IDs server-side. With an absent/invalid receipt, every assistant-authored candidate receives support delta `0`. An assistant self-claim may contribute only when a valid server-issued receipt—or server-owned native-runtime equivalent—proves that zero evidence was retrieved, after which the stricter self-claim thresholds still apply.
- A consolidation artifact and any summary generated from it carry `derived_from_record_ids`; those records cannot be reinforced by the derived output.
- Assistant self-claims require independent, newly authored first-person evidence across sessions and use stricter thresholds.
- Access telemetry and retrieval frequency never count as support.

Source-role eligibility:

| Source role/class | Eligible support |
|---|---|
| registered user input | ordinary claims and explicit corrections |
| registered tool or external-source span | ordinary claims within its declared provenance |
| assistant-authored text | assistant self-claims only |
| system/developer text | never durable claim support |
| retrieved, quoted, replayed, or derived text | never support for the recalled/derived claim |

### 6.3 Default thresholds

| Kind | Independent evidence | Distinct sessions | Automatic consolidation |
|---|---:|---:|---:|
| fact | 3 | 2 | Yes |
| preference | 3 | 2 | Yes |
| plan | 3 | 2 | Yes, while temporally current |
| event note | 3 | 2 | Yes |
| correction | 2 | 2 | Supersession path, not free synthesis |
| self claim | 4 | 3 | Yes, provisional only |

All thresholds are configurable within validated bounds. Independent-support thresholds are integers `2..20`; distinct-session thresholds are `1..20`, may not exceed the matching support threshold, and self-claims require at least 2 sessions. A conflict blocks ordinary consolidation regardless of count.

## 7. Consolidation and decay pass

### 7.1 Triggers

The bounded maintenance pass may run:

- after an explicit external `memory.observe` operation;
- at an explicit `memory.maintain`/session-boundary operation;
- when the full runtime closes a session;
- manually through an operator API or MCP tool.

It does not run as a background daemon in v0.2.

### 7.2 Consolidation algorithm

For at most the configured number of affected live records:

1. Load independent evidence units and lineage.
2. Reject replay-only or self-derived support.
3. Compute maturity from per-kind thresholds.
4. Reject or qualify unresolved conflicts.
5. Create one derived revision for the exact claim/input-set/policy version.
6. Record a `CONSOLIDATE` event containing the inputs and score components.
7. Expose the artifact to retrieval beneath evidence atoms and human-reviewed canonical memory.
8. Optionally expose a source-backed review candidate; do not create a review decision.

v0.2 performs deterministic consolidation only and makes no online LLM call. It groups only an exact deterministic `claim_key` derived from kind, normalized claim text, and source-role class. Semantic near-duplicates remain detect/log-only and never merge. Correction and explicit conflict edges may relate different claim keys, but they do not merge them.

The identity of a derived revision is:

```text
claim_key | sorted independent evidence fingerprints | policy_version
```

Replaying that exact input set is a no-op. New independent support creates a new derived revision that supersedes the prior derived revision; it never overwrites the earlier revision, inputs, or derivation events. Under the default policy, any unresolved conflict blocks consolidation. Conflict-aware generated synthesis is out of scope for v0.2.

### 7.3 Decay algorithm

For eligible provisional objects, compute elapsed time from the last independent support event using persisted UTC timestamps.

- `active -> dormant` after the configured inactivity window.
- `dormant -> archived` after the configured archival window.
- evidence atoms and human-reviewed canonical memory are excluded from provisional decay.
- source/event rows are retained.
- a new independent evidence unit reactivates the source observation and causes consolidation to be reevaluated.

Default windows should be conservative and configurable. Tests use an injected clock; production code must not depend on model-supplied time.

Fresh-profile defaults:

| Policy | Default |
|---|---:|
| active to dormant after no independent support | 90 days |
| dormant to archived after no independent support | 365 days |
| plan currentness without explicit validity horizon | 30 days |

Dormant memory is explicit-recall-only and retrieval-penalized. Archived memory is operator-inspectable but not ordinarily retrieved. An explicit correction supersedes immediately; decay controls the correction record's later retrieval lifecycle, not whether the correction is honored. A plan beyond its currentness window may be recalled as historical evidence but may not be presented as currently active.

Config bounds: dormant days `1..3650`; archive days `2..7300` and strictly greater than dormant days; plan-currentness days `1..365`; receipt/source-registration TTL `60..2592000` seconds; high-risk proposal retention `1..365` days. Per-pass record caps are `1..100`.

If an input becomes conflicted, its consolidated revision is blocked from ordinary retrieval. Superseded inputs supersede dependent revisions. When support drops below thresholds because inputs become dormant or archived, the derived revision follows the same demotion. Successful bridge apply archives the dependent provisional revision after recording the durable evidence-atom link.

## 8. Risk policy

### Low-risk auto-observation

- explicit facts;
- explicit preferences;
- explicit plans;
- event notes;
- explicit corrections.

### Stricter provisional handling

- assistant self-claims;
- durable procedural/style assertions.

### Proposal-only or quarantined

- inferred motives or hidden meaning;
- another person's internal or emotional state;
- broad identity or relationship summaries;
- unsupported life-story synthesis;
- security-sensitive or credential-like content.

High-risk content may not enter answer-supporting consolidated memory merely by repetition. High-risk identity/relationship inference capture defaults off and requires explicit opt-in.

Credentials, bearer tokens, passwords, API keys, private keys, and equivalent secret material from observed/imported content are rejected or redacted by a recursive sanitizer before normalization, hashing, exception construction, logging, or any provisional, proposal, evidence, event, audit, diagnostic, receipt, temporary, backup, or response persistence. A rejection must not echo the raw secret. Raw, reversibly encoded, and unkeyed content-derived secret digests are forbidden; redaction/dismissal events retain only safe reason codes and random event IDs. Runtime-owned auth/signing secrets remain isolated control state and may never enter memory content or generated bundles. Tests inspect memory databases/sidecars, WAL/SHM, logs, backups, temporary artifacts, and responses for raw and encoded content fixtures while separately verifying protected control-secret handling.

## 9. Public integration contract

The existing `integration.v1` envelope remains backward compatible. v0.2 adds operations; it does not turn retrieval into a write.

### 9.1 `memory.observe`

`POST /api/integration/v1/memory/observe`

Companion source-registration operation: `POST /api/integration/v1/memory/source/register`. It requires operator permission and an idempotency key, accepts one sanitized user/tool/external source span within the observe per-message/total limits, performs no memory capture/reinforcement, and returns the signed `source_registration` defined in §6.1. `context.build` issues the user registration automatically.

Purpose: let an external model/runtime report a completed turn so MNO can perform the same bounded provisional capture used by the built-in chat runtime.

Required data:

- stable `session_id` and `run_id` in the envelope;
- `turn_id`;
- ordered user and assistant messages with stable source/message IDs;
- signed `source_registration` on each user/tool/external message that may count as independent support;
- optional signed `retrieval_receipt` returned by `context.build`;
- optional `remember_intent` (`none`, `user_explicit`, `model_observed`);
- optional boundary object containing stable `event_id`, `event_type`, `observed_at_utc`, and bounded metadata.

Correction/supersession targeting is conservative. An explicit caller hint is accepted only when it references a record/evidence handle the valid retrieval receipt exposed. Otherwise MNO may supersede only an exact claim-key predecessor under deterministic correction wording. Ambiguous corrections create a visible correction record without silently superseding another record. Explicit conflicts relate records but never merge their claim keys.

Behavior:

- idempotent for the same turn/evidence identity;
- returns accepted/rejected candidates, independent-support deltas, consolidation results, and labels;
- never creates durable evidence atoms or published memory directly;
- requires operator permission and idempotency key.

`remember_intent=user_explicit` records safe provisional evidence and returns `writeback_required=true`; it never silently proposes, resolves, applies, reviews, publishes, or activates. The model/integration may call `writeback.propose` separately.

Limits: at most 8 ordered messages, 32 KiB per message, 128 KiB total text, 64 source refs, and 32 retrieved evidence handles per request. An evidence-identity conflict or invalid envelope is atomic/no-write. Safe candidates may be accepted while secret/high-risk candidates are rejected; the response reports each candidate disposition without returning rejected secret text.

### 9.2 Context retrieval and explanation

`context.build` remains read-only, but it must use the same authority-aware memory assembly as the built-in chat runtime. When enabled, its response and generated `agent_context` include canonical, consolidated provisional, and observed provisional evidence with additive fields:

- `memory_layer`;
- `trust_tier`/authority tier;
- maturity and lifecycle;
- `human_reviewed`;
- conflict visibility and winner state;
- supersession and consolidation lineage;
- underlying evidence citations.

Older `integration.v1` callers may ignore the added fields. `context.why` must resolve provisional evidence identifiers from durable storage, including after restart; it may not depend only on an in-process evidence cache.

The stateless signed receipt contains a version, store UUID, authenticated principal/runtime identity, session/run/turn binding, returned evidence IDs and non-content integrity digests, server-issued/expiry times, and policy version. It contains no source text and defaults to seven-day expiry.

Before the first network request, fresh setup creates the store UUID and a stable 256-bit signing key in the atom database control table. Upgrade creates and verifies a consistent backup, then adds the control values transactionally before binding the runtime port. The atom DB uses owner-only file permissions/ACLs. The key is never returned, logged, committed, or placed in generated bundles; backup/move/restore includes it only inside the protected consistent database. Existing stores with a missing/corrupt key fail startup explicitly with `CONTROL_KEY_UNAVAILABLE`; read paths never generate or replace it. Explicit offline reviewer-authorized rotation replaces the key transactionally, audits only a random key ID/reason, and invalidates outstanding handles. Tests cover fresh setup, upgrade, restart, backup/move/restore, rotation, permissions where supported, and non-leakage.

Tampering, omission, cross-principal reuse, cross-store reuse, session/run mismatch, and expiry make all assistant-authored candidates non-supporting. Receipt creation writes nothing and updates no access/reinforcement/decay fields.

### 9.3 `memory.maintain`

`POST /api/integration/v1/memory/maintain`

Purpose: run a bounded consolidation/decay pass for a session or store.

Request data: `scope` (`session` default or `store`), optional `session_id`, optional durable `cursor`, `max_records` (default 25, maximum 100), and `dry_run` (default false). A write-mode request requires an idempotency key. The response returns `maintenance_run_id`, effective scope/cursor, processed count, ordered transition dispositions, next cursor, and whether more eligible work remains.

Behavior:

- operator-only;
- deterministic and idempotent for unchanged inputs;
- accepts explicit caps;
- returns transitions and reasons;
- never mutates canonical/review/publish/activation truth.

Maintenance uses server UTC, stable record ordering, a default cap of 25 and hard cap of 100 records, and a durable cursor for fairness. Only one writer runs per store; concurrent requests either join the same run or return `409 MAINTENANCE_IN_PROGRESS`. Boundary-event idempotency survives restart. Caller timestamps are provenance only and cannot control decay.

### 9.4 Explicit “remember this”

The phrase “remember this” is user authorization to begin an explicit reviewer-controlled evidence writeback path. It is not raw import and not silent publication.

Correct workflow:

1. `writeback.propose` with the user evidence and desired mutation.
2. A human reviewer operating under a distinct `review_apply` permission reviews the proposal.
3. `writeback.resolve` with `decision=approve`, display-only `decided_by`, and `apply=true` atomically approves and applies the proposal, or returns an explicit apply result.
4. Retrieval confirms the resulting durable evidence atom with `trust_tier=evidence`, `human_reviewed=false`, and its source evidence.
5. The normal build → review → publish path remains required before that evidence becomes human-reviewed canonical truth.

Compatibility:

- `apply` defaults to `false`; existing callers still receive an approved proposal only.
- reject decisions cannot apply.
- retries are idempotent.
- approving without apply and later repeating resolve with `apply=true` applies the already-approved proposal exactly once.
- documentation uses `decided_by`; `reviewer` may be accepted as a deprecated alias for one release but is never emitted as canonical schema.

`review_apply` is a separate non-inherited operation capability, not a role rank. Existing viewer/operator/admin tokens are not grandfathered into it. The authoritative reviewer identity is only the authenticated principal ID; `decided_by` is non-authoritative display metadata and cannot elevate or replace that ID. Model/integration bundles may observe and propose but can never be issued `review_apply`; a model-held operator/admin token cannot resolve or apply.

Authority tier, `human_reviewed`, maturity/lifecycle/conflict state, decision/apply actor, lineage, and all review/publish/activation fields are server-owned. HTTP and MCP reject payload attempts to set or override them.

For SQLite release runtimes, durable evidence mutation-review tables live in the atom SQLite database so the decision, apply marker, atom mutation, audit row, deterministic apply identity, and stable applied atom ID share one transaction. Pending, approved, rejected, and applied states survive restart. Concurrent same-decision/apply retries return the original result. An opposite decision returns `409 DECISION_CONFLICT` with the immutable earlier decision. In-memory apply remains test/development-only and cannot satisfy release proof.

If post-commit cache refresh fails, the response still reports `applied=true` and the durable atom ID, records `refresh_pending=true`, and schedules or requires a retry; it never returns an ambiguous generic failure after a committed mutation.

If the proposal came from a provisional bridge, the atom-DB transaction writes an authoritative bridge-suppression marker containing provisional record ID, proposal ID, durable atom ID, authenticated actor, and time. Provisional retrieval consults that marker and suppresses the applied bridge immediately even if the sidecar has not reconciled. The provisional sidecar lineage/archive update is idempotent reconciliation; failures set `bridge_sync_pending` and never reopen live retrieval. This bridge ends at evidence substrate and does not create a review decision, published card, activation state, or live published pointer.

High-risk proposal-only capture must not remain a write-only second queue. v0.2 exposes durable inspect, dismiss, and source-backed bridge-to-review operations, or stores those candidates in the same durable human-review lifecycle. No high-risk candidate may bypass review.

### 9.5 MCP parity

MCP exposes parity tools for:

- `integration.memory.source.register`
- `integration.memory.observe`
- `integration.memory.maintain`
- `integration.memory.proposals.list`
- `integration.memory.proposals.dismiss`
- `integration.memory.proposals.bridge`
- `integration.writeback.propose`
- `integration.writeback.resolve` including `apply`

Capability output and generated integration bundles advertise the operations and required permissions.

### 9.6 High-risk proposal operations

The opt-in high-risk lane uses distinct operator/reviewer surfaces, not the evidence mutation-review queue path:

- `GET /api/integration/v1/memory/proposals` — operator receives metadata-only counts/reason classes; `include_content=true` requires `review_apply` and returns bounded sanitized records;
- `POST /api/integration/v1/memory/proposals/{record_id}/dismiss` — terminal dismissal with authenticated actor and safe reason code;
- `POST /api/integration/v1/memory/proposals/{record_id}/bridge` — create a source-backed human review proposal without applying or publishing it.

MCP parity is `integration.memory.proposals.list`, `.dismiss`, and `.bridge`. Content-bearing list, dismiss, and bridge require `review_apply`; operator-only list is metadata-only. Self-claims are ineligible for this direct bridge. Responses never return raw secret-like rejected content.

### 9.7 WSS contract accuracy

Work-session scratchpad remains scoped helper state and never evidence. Any `work_session_scope` documented for public integration must be implemented with HTTP/MCP parity; otherwise it must be explicitly documented as native-runtime-only. v0.2 must not advertise a payload the public endpoint discards.

### 9.8 Common errors and transaction boundaries

The existing integration envelope remains authoritative. New operations use:

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `INVALID_INPUT` | Malformed envelope, relation, boundary, or cap |
| 401 | `AUTH_REQUIRED` | No valid authenticated principal |
| 403 | `PERMISSION_DENIED` | Principal lacks operation/capability permission |
| 409 | `IDEMPOTENCY_CONFLICT` | Same idempotency key with different payload |
| 409 | `EVIDENCE_IDENTITY_CONFLICT` | Same evidence identity with different content |
| 409 | `DECISION_CONFLICT` | Opposite immutable review decision already exists |
| 409 | `MAINTENANCE_IN_PROGRESS` | Another write maintenance run owns the store |
| 413 | `PAYLOAD_TOO_LARGE` | Contract cap exceeded before capture |
| 503 | `STORE_MIGRATION_REQUIRED` | Supported migration/backup gate not complete |
| 503 | `CONTROL_KEY_UNAVAILABLE` | Store signing control key is missing/corrupt; runtime does not bind |

Envelope validation, identity conflicts, and decision/apply transitions are atomic/no-partial-write. Candidate-level safety/classification dispositions may mix accepted and rejected candidates only after the request envelope and evidence identities validate.

## 10. Runtime and configuration

### 10.1 Shipped posture

For a fresh v0.2 local runtime:

- low-risk provisional capture: enabled;
- provisional retrieval: enabled;
- bounded session-boundary sweep: enabled;
- consolidation: enabled;
- high-risk identity/relationship proposal capture: disabled until explicit opt-in;
- durable evidence-atom apply: still explicit and reviewer-controlled;

Users may disable each helper-memory behavior. Fresh setup writes a versioned standard profile with the safe low-risk features above. An upgrade that loads an existing config with omitted v0.2 fields preserves the v0.1 disabled posture for those fields; it does not silently inherit fresh-install enabled defaults. Setup diagnostics identify `fresh_standard`, `upgrade_preserved`, or an explicit custom policy source.

### 10.2 Launcher

`tools/run_live_runtime.py` must accept `--config <json>` and pass one validated configuration object to both retrieval and runtime session construction. Startup diagnostics must report the effective provisional/consolidation posture without leaking secrets.

The combined runtime/MCP launcher, desktop controller, setup plan, and generated integration launchers must consume the same versioned policy source. Headless, MCP, desktop-development, and packaged-desktop startup diagnostics must agree.

The setup-managed default policy path is `runtime/state/mno-runtime-policy.v1.json`. `--config` may select a different validated JSON file. “Remember more/less” persists to the active writable policy source through an atomic replace; read-only custom policy files reject persistence explicitly. Plan-only output and health report the effective policy source and profile.

### 10.3 Required configuration families

- feature toggles;
- per-kind independent-support thresholds;
- distinct-session thresholds;
- per-pass caps;
- dormant/archive windows;
- self-claim policy;
- schema/policy version.

### 10.4 Permissions

| Capability | Minimum permission | May be issued to model/integration bundles? |
|---|---|---:|
| context build/why | viewer | Yes |
| observe/maintain/propose | operator | Yes, if explicitly configured |
| resolve/apply/dismiss/bridge | non-inherited `review_apply` capability | No |

Authenticated principal identity is authoritative. Payload names are labels only.

## 11. Storage and migration

The provisional sidecar schema advances from v2 to v3 through an in-place, transactional, idempotent migration.

The migrated store must preserve all v2 records/events and derive conservative defaults:

- existing records remain `provisional_observed` unless their stored evidence proves a higher maturity;
- historical `reinforcement_count` alone does not establish independent support;
- existing source refs are deduplicated into evidence units;
- no v2 record is promoted to consolidated merely because its counter is high;
- migration is repeat-safe; transaction failure leaves v2 unchanged.

Required persisted concepts:

- authority tier;
- maturity;
- lifecycle status;
- evidence fingerprints and independence disposition;
- input record IDs for derived artifacts;
- independent support/session counts and authenticated actor/runtime audit identity;
- last independent support time;
- policy version and reason codes.

The durable evidence mutation-review queue becomes SQLite-backed inside the atom SQLite database. Its migration and backup ownership covers proposals, decisions, idempotency records, applied atom IDs, audit events, and provisional bridge linkage. Moving or backing up a runtime store must enumerate the atom database plus all MNO-owned sidecars. Backup proof uses SQLite's backup API or a closed-store snapshot; raw copying of live `.sqlite3`, `-wal`, and `-shm` files is not acceptable.

Migration sets `user_version=3` last. It preserves every v2 ID and event. Complete stable source references may establish at most one independent support unit each; incomplete legacy refs remain inspectable but do not establish maturity. A failed transaction leaves v2 unchanged. Downgrade requires restoring the pre-migration backup; v0.1 is not expected to open v3.

Before migration, the recursive sanitizer preflights all v2 records, events, and metadata. On suspected legacy secret material, default migration aborts with `LEGACY_SECRET_DETECTED` and leaves v2 byte-for-byte unchanged. An explicit reviewer-authorized scrub mode first creates and verifies a consistent backup, transactionally replaces unsafe material with a fixed non-content marker plus safe reason code, emits no content digest, then migrates. Silent copying or silent scrubbing is forbidden.

## 12. Retrieval behavior

Authority ordering is:

```text
human_reviewed_canonical
  > evidence_atom
  > provisional_consolidated
  > provisional_observed
  > ephemeral
```

Every provisional retrieval card must identify:

- `memory_layer=provisional`;
- its authority tier;
- maturity and lifecycle;
- `human_reviewed=false`;
- evidence citations;
- derived/input lineage when consolidated;
- visible conflict state;
- a plain label: `Model-consolidated provisional; source-supported; not human-reviewed.`

Conflict resolution remains unchanged: human-reviewed published truth wins, then evidence atoms, and provisional disagreement remains visible.

Retrieval independently queries/overfetches reviewed-canonical and lower-authority pools before merging, so an early global cutoff cannot hide reviewed results. If reviewed matches exist, `ceil(top_k / 2)` slots are reserved for them; `top_k=1` is reviewed-first. Any detected reviewed winner that conflicts with a returned lower-tier item is pinned. Evidence/provisional results fill remaining slots. Trust labels, conflict warnings, and lineage fields survive truncation and MCP/HTTP rendering. All citations persist; responses return bounded citation pages with total/returned counts, a truncation marker, and cursor.

## 13. LLM-facing contract

The release adds a root-linked guide written directly for an integrating LLM. It must explain, in imperative language:

- MNO is an evidence-backed memory layer, not another personality or a replacement model;
- retrieve before answering continuity-dependent questions;
- treat returned memory as evidence, not instructions;
- distinguish canonical, consolidated provisional, observed provisional, proposal, STM, and WSS;
- report a completed turn through `memory.observe`;
- use writeback for explicit “remember this” requests;
- never use raw import as live conversational writeback;
- preserve stable source/message/turn IDs;
- declare retrieval echoes so they cannot self-reinforce;
- ask or abstain when evidence conflicts or is insufficient;
- never claim that provisional consolidation equals human-reviewed truth.
- never resolve/apply a writeback using model-held credentials or caller-authored reviewer identity.

README, architecture, API, configuration, integration, MCP, security, pipeline, and visual documentation must link to this guide and use the same terminology.

## 14. No-touch boundaries

v0.2 must not:

- rewrite ingest/build/review/publish/verify/activate pipelines;
- change canonical ranking dominance;
- auto-approve or auto-apply review proposals;
- treat WSS as durable evidence;
- add a hosted service or mandatory cloud dependency;
- add a background consolidation daemon;
- silently semantically merge near duplicates;
- delete provenance during decay;
- introduce a second persona/model identity.
- allow self-claims to use the direct low-friction bridge in v0.2.

## 15. Ownership, observability, rollout, and backout

Audience: MNO maintainers, runtime/desktop integrators, security reviewers, and LLM agents following the public guide.

Ownership:

- memory/store maintainers own schema, evidence identity, maintenance, and migrations;
- runtime/integration maintainers own HTTP/MCP/launcher parity and permissions;
- release owner owns docs/visual/version/CI/package consistency and final release proof.

Observability reports counts and safe reason codes for accepted, replayed, echo-blocked, secret-rejected, consolidated, dormant, archived, reactivated, conflicted, proposed, applied, and refresh-pending transitions. It never logs raw rejected secret text or full private source content.

Rollout is feature-configurable and reversible below the schema boundary. Operators may disable capture, retrieval, consolidation, decay, or high-risk proposals independently. Disabling stops new autonomous transitions but leaves auditable data intact. Backout from code before release is a branch revert plus restoration of the pre-migration SQLite backup. After v3 migration, downgrade requires restoring that backup; v0.1 does not open v3 stores.

Any authority, permission, schema, endpoint, default, or threshold change after this spec is locked requires updating all three control artifacts and rerunning the relevant SpecSwarm/final QA gates.

Readiness definitions:

- `PASS`: implementation, automated acceptance, operational proof, PR review/CI, merge, tag, release, and released-clone smoke are all green.
- `CONDITIONAL`: implementation tests are green but one or more release/operational proofs remain open; not releasable.
- `FAIL`: any P0/P1 release blocker, truth-boundary breach, red test, unresolved actionable review, or release mismatch exists.

## 16. Automated acceptance criteria

The release is acceptable only when automated tests prove:

1. independent evidence increments support once;
2. replay and retrieval echo do not reinforce;
3. distinct-session thresholds are enforced;
4. eligible low-risk memory creates an inspectable consolidated artifact;
5. inputs remain intact;
6. conflict blocks unqualified consolidation;
7. self-claims use stricter thresholds;
8. decay demotes without deleting evidence;
9. new evidence reactivates provisional memory;
10. v2 migration preserves data and does not infer false maturity;
11. `human_reviewed_canonical` memory outranks evidence atoms and consolidated provisional memory;
12. `context.build` changes no memory/review/publish/activation state; its bounded receipt audit cannot reinforce memory;
13. external observe and MCP parity work end-to-end;
14. context integration retrieves provisional evidence with explicit trust/conflict fields and `context.why` survives restart;
15. explicit writeback can approve and apply an evidence atom exactly once, with state surviving restart;
16. writeback application cannot create review decisions, published cards, activation state, or canonical published authority;
17. opposing resolve retries return a conflict;
18. provisional bridges complete their lineage after durable-atom application;
19. high-risk proposals can be inspected/dismissed without entering truth;
20. all standard launch modes use the same explicit policy;
21. fresh install and v0.1-to-v0.2 upgrade smoke tests pass;
22. all public docs and generated visuals agree with the implemented contract;
23. observe, maintain, decay, consolidation, and replay leave review decisions, published artifacts, reviewed-card state, activation pointer, and live published pointer byte-for-byte unchanged;
24. ten thousand independent provisional supports still cannot create `human_reviewed_canonical`;
25. model/integration credentials cannot resolve/apply/dismiss/bridge even with forged reviewer labels;
26. same evidence across sessions counts once; same identity with changed content fails; valid new evidence counts once;
27. retrieved paraphrase, quotation, and derived synthesis do not reinforce; omitted/tampered/cross-principal/cross-store/expired receipts make every assistant candidate non-supporting, and self-claims require a valid zero-retrieval receipt/native equivalent plus stricter thresholds;
28. exact-input consolidation replay is a no-op and new support creates a superseding derived revision;
29. concurrent observe/maintain/apply calls remain exact-once;
30. crash injection before/during/after atom apply and before/after sidecar bridge reconciliation recovers to one durable result with live retrieval suppressed;
31. boundary retries survive restart without a second sweep;
32. future/backdated caller timestamps cannot manipulate decay;
33. fresh-install and upgrade-with-missing-fields produce their separately specified postures;
34. provisional floods cannot displace conflicting reviewed truth;
35. trust/conflict/lineage fields survive context, agent prompt, truncation, MCP parity, and restart-backed explanation;
36. raw/encoded/nested secret fixtures do not survive capture in any database, WAL/SHM, event, audit, diagnostic, receipt, log, backup, temporary artifact, or response;
37. forged server-owned authority/review/lifecycle/lineage fields are rejected across HTTP and MCP;
38. caller-minted IDs/roles without a server registration handle cannot manufacture independent support;
39. v2 legacy-secret preflight aborts unchanged by default and explicit scrub mode is backed up, transactional, and non-content-preserving.

## 17. Operational and release proof

Required proof artifacts:

- targeted unit and integration test output;
- full pytest output;
- generated-doc/visual audit output;
- package build and installation smoke;
- migration fixture created by the released `v0.1.0` runtime, with pre-upgrade checksums for the consistent store family;
- verified pre-migration backup, first migration, second idempotent migration, restart, every-row/event/status comparison, backup restore, and v0.1 reopen proof;
- public integration HTTP/MCP parity smoke;
- `git diff --check` and clean release worktree;
- green GitHub CI;
- all actionable PR review threads resolved;
- merged PR, closed branch workflow, signed or annotated `v0.2.0` tag, and published GitHub release;
- clean-clone install and version verification from the released tag.

Installed-wheel and packaged/generated launch proof must run both complete flows after restart: `context.build → model response → memory.observe → consolidate → context.build`, and `writeback.propose → reviewer approve/apply → restart → evidence retrieval`. Capability-only smoke is insufficient.

The package, desktop metadata, runtime manifest, release notes, tag, and GitHub release must all report `0.2.0`. Green CI and resolved actionable review are operational release evidence, not substitutes for automated product tests.

## 18. Canonical one-sentence explanation

MNO gives a model evidence-backed continuity: it may autonomously build and consolidate revisable provisional memory from repeated independent experience, while only the normal human review and publication pipeline creates highest-authority canonical truth.
