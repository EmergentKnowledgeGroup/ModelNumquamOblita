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
- avoid committing token values into config files
- avoid pasting tokens into screenshots or support logs
- rotate tokens after sharing a machine, config bundle, or terminal session
- use viewer tokens for read-only agents whenever possible

Operator and admin tokens can propose or resolve writeback. Do not give them to untrusted agents.

## Runtime Data

The `runtime/` tree is local generated state. It can contain memory stores, reviewed episode cards, setup reports, logs, import outputs, live-run manifests, MCP config exports, and temporary wizard uploads.

Do not publish populated runtime data. A clean public repo should not include private memory stores, setup logs, checkpoint reports, desktop shell logs, or generated packaging output.

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

## Truth Boundaries

Human review remains authoritative for reviewed episode truth. Draft cards, proposal artifacts, provisional memory, pins, action logs, wake-up packs, resume packs, and retrieval feedback do not outrank reviewed truth.

Writeback is propose/resolve gated. Draft or proposal artifacts are not silently promoted into reviewed truth.

## Deployment Warnings

Before using MNO outside a local workstation:

- require explicit bearer auth on integration routes
- bind services to private interfaces only unless fronted by a secure proxy
- configure OS-level file permissions around `runtime/`
- keep MCP config files scoped to the intended assistant or agent
- verify that raw-context and report retention matches your privacy expectations
- disable or restrict mutation-capable tokens for agents that only need retrieval

## Public Repo Hygiene

The distributable repo should contain product code, launch scripts, tests, and docs. It should not contain:

- personal machine paths
- generated checkpoint files
- populated memory stores
- desktop build output
- local setup reports
- copied dependency folders
- private agent configs
