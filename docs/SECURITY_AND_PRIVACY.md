# Security And Privacy

## Core Stance

MNO is a local-first memory runtime. It is designed to keep memory claims evidence-backed, reviewable, and auditable on the machine where it runs.

## Local-Only Assumptions

Default launch patterns bind the runtime and MCP sidecar to loopback addresses such as `127.0.0.1`. Do not expose the runtime, desktop shell, or MCP sidecar directly to the public internet.

If you deploy outside a single-user local machine, put MNO behind your own network controls, TLS termination, process isolation, log retention policy, and secret management. The clean repo does not claim to be a hardened multi-tenant hosted service out of the box.

## Tokens

HTTP integration and MCP entrypoints support bearer tokens. Treat viewer, operator, and admin tokens as local secrets.

Recommended handling:

- set tokens through environment variables or local process managers
- keep `NO_INTEGRATION_REVIEW_APPLY_TOKEN` out of command-line arguments, process listings, shell history, and model-generated bundles; the shipped MCP launchers read it only from the environment
- avoid committing token values into config files
- avoid pasting tokens into screenshots or support logs
- rotate tokens after sharing a machine, config bundle, or terminal session
- use viewer tokens for read-only agents whenever possible

Operator/admin tokens can propose or observe provisional memory. `writeback.resolve` additionally requires the distinct, non-inherited `review_apply` capability and must not be issued to model/integration bundles. Do not give mutation-capable tokens to untrusted agents.

Signed source registrations and retrieval receipts are integrity handles, not bearer authority. Keep them scoped to the intended principal/session/run/store and treat tampering, expiry, or cross-store reuse as invalid. They are designed to prevent a model from manufacturing independent evidence by replaying or summarizing its own output.

## Runtime Data

The `runtime/` tree is local generated state. It can contain memory stores, reviewed episode cards, setup reports, logs, import outputs, live-run manifests, MCP config exports, and temporary wizard uploads.

Do not publish populated runtime data. A clean public repo should not include private memory stores, setup logs, checkpoint reports, desktop shell logs, or generated packaging output.

Work-session scratchpad data is runtime data too. It is stored as a project-local sidecar for strict-scope agent continuity and may contain compact operational summaries. Do not publish populated WSS sidecars.

Use MNO's SQLite backup operation for live atom/provisional/proposal stores. Copying a live database file or its WAL/SHM companions is not a reliable consistency guarantee. Treat backups as private memory data and verify them by reopening before migration or release work.

### Legacy v0.1 provisional stores

The v0.2 schema-v3 opener performs a read-only recursive safety preflight before it opens a v2 provisional store for writing. If legacy record, event, reference, or metadata content looks like a secret, opening aborts with `LEGACY_SECRET_DETECTED`; the original database is left byte-for-byte unchanged and no content digest is emitted.

Scrubbing is an explicit offline recovery operation, not an automatic startup behavior. It requires both a reviewer identity and a new backup destination. MNO creates the v2 backup with SQLite's backup API, verifies its schema, integrity, and row counts, and only then performs the transactional scrub/migration:

```python
from engine.memory import SqliteProvisionalMemoryStore

store = SqliteProvisionalMemoryStore.migrate_legacy_store(
    "runtime/private/provisional.sqlite3",
    scrub_legacy_secrets=True,
    scrub_authorized_by="local-reviewer-id",
    legacy_backup_path="runtime/private/backups/provisional-v2.sqlite3",
)
store.close()
```

The backup intentionally retains the original private content so that downgrade/restore remains possible. Protect it as secret-bearing runtime data and never publish it.

## Logs And Reports

MNO logs are meant for local diagnosis. Depending on what you run, logs and reports may include:

- absolute local paths
- runtime URLs and ports
- MCP target names
- setup failures
- import file names
- selected store paths
- excerpts or summaries from local memory data

Before sharing logs, inspect them as private data.

## Raw Context Risks

MNO can preserve bounded raw-context receipts for provenance and quote-oriented requests. This improves auditability, but it also means source wording can be sensitive.

Practical rule: if the source file contains private text, assume raw-context surfaces may reveal short excerpts of that text to local operators or authorized agents.

Raw import applies the secret-content boundary before normalized conversations, raw-context receipts, reports, or database rows are persisted. A rejected secret-like payload fails closed and must leave no durable canary residue. Desktop and source artifacts are also manifest-checked to exclude populated runtime data.

## Work-Session Scratchpad Risks

WSS summaries are non-authoritative `scratchpad_ephemeral` helper state, but they can still mention local work details. Keep the runtime state root private, rotate or delete WSS sidecars according to your retention policy, and never treat scratchpad summaries as reviewed memory evidence.

## Truth Boundaries

Human review remains authoritative for reviewed episode truth. Draft cards, proposal artifacts, provisional memory, pins, action logs, wake-up packs, resume packs, WSS `scratchpad_ephemeral` context, and retrieval feedback do not outrank reviewed truth.

Writeback is propose/resolve gated. With explicit reviewer `review_apply`, an approved proposal may materialize a durable `evidence_atom` with `human_reviewed=false`; this is evidence substrate, not reviewed/published truth. Draft or proposal artifacts are not silently promoted into reviewed truth.

Autonomous observed/reinforced/consolidated provisional memory remains revisable and lower authority than evidence atoms and human-reviewed canonical truth. Decay can demote provisional retrieval eligibility but must preserve its lineage; it does not delete evidence or canonical memory.

## Deployment Warnings

Before using MNO outside a local workstation:

- require explicit bearer auth on integration routes
- bind services to private interfaces only unless fronted by a secure proxy
- configure OS-level file permissions around `runtime/`
- keep MCP config files scoped to the intended assistant or agent
- verify that raw-context and report retention matches your privacy expectations
- verify that WSS sidecar retention matches your local work-session privacy expectations
- disable or restrict mutation-capable tokens for agents that only need retrieval

## Public Repo Hygiene

The distributable repo should contain product code, launch scripts, tests, and docs. It should not contain:

- personal machine paths
- generated checkpoint files
- populated memory stores
- populated WSS sidecars
- desktop build output
- local setup reports
- copied dependency folders
- private agent configs
