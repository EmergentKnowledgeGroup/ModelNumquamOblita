# carsinOS Integration Requirements (Implementation Contract)

## 1) Purpose and Scope

This document is the binding implementation contract for integrating NumquamOblita with carsinOS.

It is decision-complete for:
- stable integration APIs and MCP tools,
- canonical payloads and envelopes,
- auth/security and risk controls,
- observability/audit expectations,
- performance/degrade behavior,
- test/signoff gates.

Any integration work is out of scope until this contract is implemented and validated.

## 2) System Boundaries

### Numquam-owned responsibilities
- Implement and maintain Integration Contract v1 (`/api/integration/v1/*` + `integration.*` MCP tools).
- Build and maintain context package creation and explainability outputs.
- Build and maintain writeback proposal and resolve operations.
- Enforce contract authn/authz on integration surfaces.
- Emit structured logs and append-only audit records required by this contract.
- Emit degrade/fail-safe contract responses to allow carsinOS fallback.

### carsinOS-owned responsibilities
- Session/run orchestration and model execution lifecycle.
- Tool approvals, channel orchestration, and operator UI.
- Provider selection/auth profile handling and fallback chain policy.
- Invocation timing of Numquam integration operations.
- Stateless model fallback path when memory dependency is degraded.

### Shared contract responsibilities
- Keep v1 contract stable and backward compatible for non-breaking changes.
- Preserve shared correlation IDs and error taxonomy end-to-end.
- Preserve evidence/provenance semantics end-to-end.
- Enforce deterministic HTTP/MCP parity after normalization.

## 3) Canonical Integration Contract (v1)

### Locked canonical decisions
- Canonical envelope style is `ok`-based (no top-level `status` field).
- Canonical `schema_version` value is `integration.v1` on requests and responses.
- `transports` in capabilities means interface-level contract transports only: `http`, `mcp`.
- `request_id_source` is a required response field.
- `already_resolved` is a required field on `writeback/resolve` responses.
- Authorization identity and roles come from token validation only; envelope `principal` is metadata.

### Versioning
- Contract path: v1 (`/api/integration/v1/*`, `integration.*` MCP namespace).
- Non-breaking changes: add optional fields only.
- Breaking changes: require new major path/namespace.

### Canonical request envelope

```json
{
  "schema_version": "integration.v1",
  "request_id": "req_01J9Z8Y4X4F9N5CW2PZ8Q0AA11",
  "session_id": "sess_abc123",
  "run_id": "run_def456",
  "principal": {
    "principal_id": "op-123",
    "display_name": "Operator Name",
    "role_hint": "operator"
  },
  "data": {}
}
```

Field rules:
- `schema_version`: required, must equal `integration.v1`.
- `request_id`: optional input. If supplied and valid, preserved.
- `session_id`: required for all except health/capabilities.
- `run_id`: required for `context/build`, `context/why`, `writeback/propose`; optional elsewhere.
- `principal`: optional metadata only; never used for authz.
- `data`: required object.

### Canonical response envelope

Success:
```json
{
  "schema_version": "integration.v1",
  "request_id": "req_01J9Z8Y4X4F9N5CW2PZ8Q0AA11",
  "request_id_source": "client",
  "operation": "context.build",
  "ok": true,
  "degrade_mode": false,
  "warnings": [],
  "data": {}
}
```

Failure:
```json
{
  "schema_version": "integration.v1",
  "request_id": "req_01J9Z8Y4X4F9N5CW2PZ8Q0AA11",
  "request_id_source": "server_generated",
  "operation": "writeback.propose",
  "ok": false,
  "degrade_mode": true,
  "warnings": [
    {
      "warning_code": "DEPENDENCY_TIMEOUT_SPIKE",
      "message": "retrieval backend degraded",
      "started_at_utc": "2026-02-19T01:10:00Z",
      "scope": "context"
    }
  ],
  "error": {
    "code": "TIMEOUT",
    "message": "context build timed out",
    "retryable": true,
    "operator_action": "retry_with_backoff"
  },
  "fallback_recommendation": "stateless_chat"
}
```

### Global limits
- Generic string max: 4096 chars.
- `context_text` max: 120000 chars.
- Generic arrays max: 100 items unless operation-specific bound is stricter.
- `warnings` max: 16.
- `evidence` max: 30.
- Maximum nested object depth: 6.

## 4) HTTP Surface (Integration v1)

All routes require bearer auth and are stable external integration routes.

### `POST /api/integration/v1/context/build`

Operation id: `context.build`

Request `data`:
- `message_window` (optional):
  - `max_messages` int, 1..200
  - `max_chars` int, 1024..200000
- `retrieval` (optional):
  - `top_k` int, 1..30
- `risk_signal` (optional enum): `low|medium|high`

Response `data`:
- `context_text` string
- `evidence` array
- `route` enum: `none|stm_only|ltm_light|ltm_deep`
- `confidence` float (0.0..1.0)
- `timings` object
- `truncation` object:
  - `truncated` bool
  - `original_size_bytes` int
  - `returned_size_bytes` int

### `POST /api/integration/v1/context/why`

Operation id: `context.why`

Request `data`:
- `evidence_ids` array of string, required, 1..30
- `expand_citations` bool, optional (default false)

Response `data`:
- `reasons` array
- `evidence` array
- `citation_expansion` object, optional

### `POST /api/integration/v1/writeback/propose`

Operation id: `writeback.propose`

Idempotency:
- Required header: `Idempotency-Key`
- Replay window: 24 hours
- Same key + same normalized payload: same `proposal_id`, `idempotent_replay=true`
- Same key + different payload: HTTP 409 + `INVALID_INPUT`

Request `data`:
- `mutation` object, required:
  - `intent` enum: `create|edit|delete|conflict`
  - `target_kind` string
  - `target_id` string, required for `edit|delete|conflict`
  - `body` object/string, required for `create|edit`
  - `tags` array, optional
  - for `intent=conflict` also required:
    - `conflict_reason`
    - `candidate_text`
    - `resolution_options` array with values from `keep_existing|replace|merge|defer`
- `evidence` array, required, each item requires:
  - `provenance_handle`
  - `source_kind`
  - `source_id`
  - `excerpt`
  - `citation` object (`type`, `ref` required)
  - `confidence` float (0.0..1.0)

Response `data`:
- `proposal_id` string
- `status` enum: `pending_review`
- `idempotent_replay` bool
- `audit_ref` string

### `POST /api/integration/v1/writeback/resolve`

Operation id: `writeback.resolve`

Request `data`:
- `proposal_id` string, required
- `decision` enum: `approve|reject`, required
- `decided_by` string, required
- `reason` string, optional

Response `data`:
- `proposal_id` string
- `status` enum: `approved|rejected`
- `already_resolved` bool (required)
- `resolved_at_utc` RFC3339 UTC
- `audit_ref` string

Repeat behavior:
- Repeated decision on already-finalized proposal returns success no-op with unchanged final status and `already_resolved=true`.

### `GET /api/integration/v1/health`

Operation id: `health.get`

Response `data`:
- `status` enum: `ok|degraded|down`
- `uptime_ms` int
- `dependencies` array

### `GET /api/integration/v1/capabilities`

Operation id: `capabilities.get`

Response `data` (required):
- `contract_version`
- `supported_schema_versions`
- `transports` (interface-level only): subset of `http|mcp`
- `mcp_runtime_transports` (optional runtime detail): subset of `stdio|streamable_http|sse`
- `operations` array of objects:
  - `name`
  - `enabled`
  - `requires_auth`
  - `required_roles`
  - `idempotent`
- `feature_flags` object
- `limits` object
- `deprecations` array of objects:
  - `operation`
  - `deprecated_at_utc`
  - `removal_not_before_utc`

## 5) MCP Surface (Parity Contract)

Tool mapping (1:1):
- `integration.context.build` <-> `POST /api/integration/v1/context/build`
- `integration.context.why` <-> `POST /api/integration/v1/context/why`
- `integration.writeback.propose` <-> `POST /api/integration/v1/writeback/propose`
- `integration.writeback.resolve` <-> `POST /api/integration/v1/writeback/resolve`
- `integration.capabilities.get` <-> `GET /api/integration/v1/capabilities`
- `integration.health.get` <-> `GET /api/integration/v1/health`

Parity rule:
- Same effective input + same config + same principal must produce equivalent canonical payloads after normalization.

Normalization rules:
- Ignore transport wrappers (HTTP status and JSON-RPC envelope).
- Compare canonical envelope + `data`/`error` only.
- Ignore object key ordering.
- Treat optional field `null` and field-absent as equivalent.
- Timestamps must be RFC3339 UTC.
- Numeric formatting must be canonical (no scientific notation in serialized fixtures).
- If truncated payloads are used, `truncation.truncated`, `original_size_bytes`, and `returned_size_bytes` must match.

MCP error handling:
- Domain errors are returned inside tool result payload (`ok=false`, contract `error` object).
- JSON-RPC error objects are reserved for protocol/transport failures only.

## 6) Error Taxonomy

Stable error codes (both transports):
- `INVALID_INPUT`
- `AUTH_REQUIRED`
- `AUTH_FORBIDDEN`
- `RATE_LIMITED`
- `DEPENDENCY_UNAVAILABLE`
- `TIMEOUT`
- `CONTRACT_VERSION_UNSUPPORTED`
- `INTERNAL_ERROR`

HTTP mapping:
- `INVALID_INPUT` -> 400
- `AUTH_REQUIRED` -> 401
- `AUTH_FORBIDDEN` -> 403
- `RATE_LIMITED` -> 429
- `DEPENDENCY_UNAVAILABLE` -> 503
- `TIMEOUT` -> 504
- `CONTRACT_VERSION_UNSUPPORTED` -> 426
- `INTERNAL_ERROR` -> 500

Retryability guidance:
- Retryable: `RATE_LIMITED`, `DEPENDENCY_UNAVAILABLE`, `TIMEOUT`
- Conditional retry: `INTERNAL_ERROR` (max one retry)
- Non-retryable: `INVALID_INPUT`, `AUTH_REQUIRED`, `AUTH_FORBIDDEN`, `CONTRACT_VERSION_UNSUPPORTED`

All error payloads must include `operator_action`.

## 7) Security and Auth Requirements

- Bearer auth required for all integration routes/tools.
- Accepted token forms: opaque bearer tokens and JWT.
- Mutation operations require role `operator` or `admin`.
- Missing/invalid roles are hard denied.
- Local-only bind is default.
- Remote exposure requires explicit enablement and hardened auth configuration.

Role-source precedence:
- JWT: parse roles from `roles` claim (string array). If `role` string is present and `roles` absent, treat as singleton list.
- Opaque tokens: roles from server-side token lookup.
- Envelope `principal` is metadata only and cannot grant rights.
- If token-derived identity conflicts with envelope `principal`, token identity wins and conflict is logged.

Token rotation requirements:
- Dual-token overlap window: 15 minutes.
- Auth cache TTL: 60 seconds.
- No-restart rotation support via runtime config/token hot-reload.

## 8) Observability and Audit Requirements

### Correlation IDs
- If client `request_id` matches `^req_[A-Za-z0-9_-]{16,64}$`, preserve exactly.
- If missing/invalid, generate `req_` + ULID.
- Response must include `request_id_source` enum: `client|server_generated`.

### Required structured log fields
- `timestamp_utc`
- `level`
- `component`
- `request_id`
- `transport`
- `operation`
- `latency_ms`
- `status`
- `error_code`
- `principal`
- `session_id`
- `run_id`
- `proposal_id`
- `retry_count`
- `degrade_mode`

### Redaction requirements
- Never log raw tokens/secrets.
- Hash PII identifiers (email/phone) before logging.
- Cap evidence excerpts in logs to 300 chars.
- Truncate large request/response blobs with explicit truncation markers.

### Audit ledger requirements
- All writeback proposal creates/resolves must generate audit entries.
- Audit records must include actor, action, timestamp, decision, affected IDs, and correlation IDs.
- Retention minimum: 365 days.
- Immutability: append-only historical records.

## 9) Performance/SLA Budgets

Latency budgets (local target):
- `health` and `capabilities` p95 < 150ms
- `context/build` p95 < 2000ms
- `writeback/propose` p95 < 1500ms

Hard timeouts:
- `context/build` <= 4000ms
- `writeback/propose` <= 3000ms
- `writeback/resolve` <= 2500ms

Timeout behavior:
- Return `TIMEOUT` (`retryable=true`).
- If degrade thresholds are crossed, return `degrade_mode=true` and fallback recommendation.

Nominal local dataset profile for SLA signoff:
- 2000 sessions
- 100000 messages
- 20000 notes
- 100000 embeddings/chunks

Load/signoff protocol:
- 60s warmup + 10m measured run
- concurrency 32
- operation mix: 70% `context/build`, 20% `writeback/propose`, 10% `writeback/resolve`
- report p50/p95/p99 and error rate

## 10) Failure and Degrade Behavior

`degrade_mode=true` triggers when any holds:
- dependency unavailable >30s
- timeout rate >20% over rolling 1-minute window
- operation p95 >2x SLA for 3 consecutive windows
- manual operator override enabled

Recovery:
- clear degrade mode after 5 consecutive healthy minutes.

Degraded response requirements:
- include `warnings` entries with:
  - `warning_code`
  - `message`
  - `started_at_utc`
  - `scope` (`context|writeback|global`)
- include `fallback_recommendation: "stateless_chat"`
- never emit partial/unsupported memory claims.

## 11) E2E Flows (Mandatory)

### Flow A: Session context retrieval before model call
1. carsinOS prepares request with `request_id`, `session_id`, `run_id`.
2. carsinOS calls `context/build`.
3. Numquam returns context package, evidence handles, route metadata.
4. carsinOS injects context into model prompt pipeline.
5. carsinOS persists `run_id` <-> `request_id` correlation.

### Flow B: Post-run writeback proposal and approval loop
1. carsinOS calls `writeback/propose` with mutation intent and evidence.
2. Numquam returns `proposal_id` with `pending_review`.
3. carsinOS surfaces proposal to operator approval channels/UI.
4. carsinOS calls `writeback/resolve` after decision.
5. Numquam returns final state and `audit_ref`.

### Flow C: Degrade fallback
1. Numquam returns `degrade_mode=true` + `fallback_recommendation`.
2. carsinOS continues the run in stateless chat path.
3. carsinOS surfaces operator warning.
4. Numquam recovers and eventually clears degrade indicators.

### Flow D: Transport parity
1. Execute same fixture through HTTP and MCP mapped operation.
2. Normalize transport wrappers.
3. Assert payload equivalence and aligned error codes.

## 12) Test Matrix and Signoff Gates

Required test categories:
- unit: validation, error mapping, auth enforcement
- contract: schema and field conformance
- parity: HTTP vs MCP equivalence
- auth matrix: token forms, role paths, deny paths
- resilience: timeouts, dependency degradation, fallback signaling
- mutation safety: proposal idempotency, resolve idempotency, audit completeness
- load: SLA and timeout budgets

Required pass criteria:
- all contract tests pass
- all parity tests pass (zero unresolved drift)
- degrade/fallback tests pass
- mutation audit tests pass
- budget regressions within approved thresholds

Hard merge gates:
- no merge if parity tests fail
- no merge if degrade/fallback tests fail
- no merge if authz deny-path tests fail

## 13) Versioning and Change Control

- Contract uses semantic versioning by major namespace.
- Non-breaking additions are minor/patch and optional-only.
- Breaking changes require new major path/namespace and migration notes.
- Deprecation support window: 2 minor releases or 90 days, whichever is longer.
- Deprecation discovery is required through both:
  - capabilities metadata (`deprecations`), and
  - release changelog.
- Every contract change requires:
  - changelog entry,
  - migration note,
  - updated parity fixtures.

## Implementation Checklist (Numquam Agent)

1. Implement canonical envelope and schema validators (including `request_id_source`, `already_resolved`).
2. Implement all HTTP endpoints in `/api/integration/v1/*` exactly as specified.
3. Implement all MCP tools in `integration.*` with 1:1 contract mapping.
4. Implement parity normalization utilities and deterministic fixtures.
5. Implement auth middleware (opaque + JWT), role enforcement, and deny-path tests.
6. Implement idempotency handling for `writeback/propose` and no-op resolve behavior.
7. Implement structured logs, redaction pipeline, and append-only audit ledger writes.
8. Implement degrade detection, warning payloads, and stateless fallback recommendation signaling.
9. Run full test matrix and produce signoff artifacts:
   - contract report,
   - parity report,
   - auth matrix report,
   - resilience report,
   - load/SLA summary.
