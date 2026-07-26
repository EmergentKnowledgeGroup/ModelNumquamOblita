# MNO Hermes Automatic Turn Adapter Blockerboard

**Status:** LOCKED v1.0 — 2026-07-26
**Spec:** [MNO Hermes Automatic Turn Adapter Specification](MNO_HERMES_AUTOMATIC_TURN_ADAPTER_SPEC_2026-07-26.md)
**Checklist:** [MNO Hermes Automatic Turn Adapter Execution Checklist](MNO_HERMES_AUTOMATIC_TURN_ADAPTER_EXECUTION_CHECKLIST_2026-07-26.md)

## Design blockers resolved before lock

| ID | State | Resolution |
| --- | --- | --- |
| HERMES-DESIGN-01 | RESOLVED | Stable session identity is separate from unique per-turn `run_id`; no session-wide run identity. |
| HERMES-DESIGN-02 | RESOLVED | Missing `turn_id` makes the entire adapter a no-op; unsafe FIFO fallback removed. |
| HERMES-DESIGN-03 | RESOLVED | Post hook only enqueues; one background attempt, no ambiguous retry. |
| HERMES-DESIGN-04 | RESOLVED | Loopback-only v1 removes remote redirect/proxy/TLS scope. |
| HERMES-DESIGN-05 | RESOLVED | Dedicated principal is server-scoped to four operations and denied review/canonical authority. |
| HERMES-DESIGN-06 | RESOLVED | Exact 4,096-character normalization and JSON-safe length-framed wrapper specified. |
| HERMES-DESIGN-07 | RESOLVED | Hermes v0.19.0 and commit pinned; native Windows claim corrected; evidence controls PASS labels. |
| HERMES-DESIGN-08 | RESOLVED | Hermes `messages.api_content` persistence and later replay disclosed; adapter privacy stated narrowly. |
| HERMES-DESIGN-09 | RESOLVED | One installer engine, explicit home/ownership/hash/backup/prior-state semantics. |
| HERMES-DESIGN-10 | RESOLVED | Ordinary versus HCR draft-only bundle separation is mandatory. |
| HERMES-DESIGN-11 | RESOLVED | MCP/provider coexistence claims narrowed; no impossible global dedupe. |
| HERMES-DESIGN-12 | RESOLVED | Real installed root-turn lifecycle is mandatory; direct callbacks and “closest harness” rejected. |
| HERMES-DESIGN-13 | RESOLVED | Amendment 1 separates per-turn `on_session_end` cleanup from reset/finalize teardown so queued observations survive pinned Hermes hook ordering. |
| HERMES-DESIGN-14 | RESOLVED | Amendment 2 makes enqueue, dequeue, and reset/finalize filtering one synchronized queue transaction released before HTTP. |

## Release blockers

| ID | State | Owner | Unblock condition | Backout |
| --- | --- | --- | --- | --- |
| HERMES-B01 | RESOLVED | Plugin lane | Installed plugin automatically recalls and enqueues observation with exact per-turn correlation | Context-only/manual MCP remains |
| HERMES-B02 | RESOLVED | Auth lane | Dedicated token succeeds only on four operations and fails review/canonical probes | Disable adapter token |
| HERMES-B03 | RESOLVED | Worker lane | Slow/black-hole runtime proves hard pre bound and non-blocking post; one attempt/no retry | Disable observation, retain recall |
| HERMES-B04 | RESOLVED | Installer lane | Install/update/doctor/status/uninstall pass with ownership, containment, full rollback, and prior-state proof | Manual plugin copy, no one-command claim |
| HERMES-B05 | RESOLVED | Bundle lane | Ordinary bundles contain adapter; HCR draft-only export does not | Keep endpoint-hint-only bundle |
| HERMES-B06 | RESOLVED | Real QA | Pinned real Hermes lifecycle proves two turns, reinforcement, duplicate suppression, interrupts, and no truth mutation | Experimental only; do not merge release-ready |
| HERMES-B07 | RESOLVED | Compatibility QA | Standalone plugin import passes 3.11; supported MNO-integrated tests pass 3.12/3.13; only pinned Windows Hermes is labeled PASS | Mark unrun surface CONDITIONAL/UNVERIFIED |
| HERMES-B08 | RESOLVED | Package QA | Full suites, wheel/sdist, isolated install, distribution verifier, privacy scan, diff check green | Block PR |
| HERMES-B09 | RESOLVED | Docs/visuals | Every affected canonical text/visual matches shipped behavior and authority boundary | Block PR |
| HERMES-B10 | OPEN | Release | Focused CLEAN PR clears review/CI, merges, and public post-merge smoke passes | Keep CLEAN main unchanged |

## Watched implementation risks

| ID | State | Risk | Required control |
| --- | --- | --- | --- |
| HERMES-R01 | WATCH | Synchronous Hermes hook latency | Shared 2,500 ms cold-capability/context budget; post enqueue under 25 ms; no I/O under locks |
| HERMES-R02 | WATCH | Ambiguous/duplicate observation adds false reinforcement | Required turn ID, exact handles, consumed tombstones, no retry |
| HERMES-R03 | WATCH | Message/secret leakage | No content/token/handle logs; contained exceptions; artifact privacy scan; disclose Hermes sidecar |
| HERMES-R04 | WATCH | Installer mutates user state | Hash ownership, containment, atomic replace, one backup, prior enable-state restoration |
| HERMES-R05 | WATCH | Shared bundle generator changes HCR | Explicit export context and negative HCR artifact test |
| HERMES-R06 | WATCH | Token env rename hides review-capable credential | Server-side `allowed_operations` check plus negative authority probe |
| HERMES-R07 | WATCH | Broad platform claims outrun evidence | PASS only exact real surface; all others CONDITIONAL/UNVERIFIED |
| HERMES-R08 | WATCH | Existing memory provider/MCP overlap | Additive docs/tests; no exclusivity or global-dedup claim |
| HERMES-R09 | WATCH | Dirty DEV contaminates public PR | File-by-file stage from DEV; untouched CLEAN until release-ready |
| HERMES-R10 | WATCH | Session cleanup races another session's queue work | Shared queue transaction across enqueue/dequeue/filter plus concurrent cross-session proof |

## External dependencies

| ID | State | Evidence / condition |
| --- | --- | --- |
| HERMES-E01 | AVAILABLE | Pinned upstream clone at v0.19.0 commit `588b7059a8b57b0e3dea98b480048eb7199ce0b6` exposes required plugin hooks and turn IDs. |
| HERMES-E02 | AVAILABLE | Current MNO integration-v1 exposes health, capabilities, context build, memory observe, signed handles, and operation-scoped token metadata. |
| HERMES-E03 | WATCH | A runnable Hermes provider/gateway and platform-specific Python interpreters determine which surfaces can be labeled PASS. |
| HERMES-E04 | WATCH | GitHub/CI/reviewer availability is required for public merge; local success cannot substitute. |

## Deferred non-blockers

| ID | Item | Reason |
| --- | --- | --- |
| HERMES-N01 | Remote MNO transport | Requires a separate origin/proxy/TLS threat model. |
| HERMES-N02 | Persistent encrypted retry spool | Adds key management and privacy risk; at-most-once in-memory v1 is safer. |
| HERMES-N03 | Agent-owned provisional episode cards | Existing provisional observations solve automatic daily memory without changing canonical cards. |
| HERMES-N04 | Hermes memory-provider implementation | General hooks compose and avoid an exclusive provider slot. |
| HERMES-N05 | Persistent last-hook status/history | Would require a new daemon/data surface; status stays static plus live read-only probe. |
| HERMES-N06 | Broad visual redesign | Only adapter-affected topology is in scope. |
