# Security Policy

MNO is a local-first memory runtime. Do not expose the runtime, desktop shell,
or MCP sidecar directly to the public internet without your own network
controls, TLS termination, process isolation, log-retention policy, and secret
management.

Start with the full security guide:

- [Security And Privacy](docs/SECURITY_AND_PRIVACY.md)

## Reporting Security Issues

Please do not publish exploit details or private memory data in public issues.
Open a minimal private report with:

- affected version or commit
- runtime surface involved, such as desktop, HTTP, MCP, or integration-v1
- reproduction steps without personal datasets
- whether tokens, generated runtime files, or raw-context receipts are involved

## Local Secret Handling

- Keep bearer tokens out of source files and screenshots.
- Use viewer tokens for read-only agents whenever possible.
- Treat operator and admin tokens as mutation-capable local secrets.
- Inspect logs before sharing them; logs can include local paths and source names.
- Treat populated WSS sidecars as private runtime data; they are local
  `scratchpad_ephemeral` work-continuity summaries, not public artifacts.

## Temporal data safety

Temporal records, clock receipts, delivery telemetry, resolver metadata, and state events are provisional-store data. Protect them like other local memory data and do not include their text in issue reports, screenshots, or release artifacts. MNO sanitizes original expressions and metadata before persistence; reminder text remains inert quoted data and never becomes an instruction to an LLM.

Temporal reads, context construction, due polls, and the heartbeat seam are read-only. A delivery observation is telemetry only: it cannot change support, maturity, authority, lifecycle, decay anchors, or canonical truth. Schedule and resolution writes require authenticated scope, durable SQLite, an idempotency key, and (for resolution) the current revision. No temporal feature creates a daemon, background wake-up, notification, or unsolicited network action.
