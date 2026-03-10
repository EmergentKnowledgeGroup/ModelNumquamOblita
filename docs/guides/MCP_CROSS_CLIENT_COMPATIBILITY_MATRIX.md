# MCP Cross-Client Compatibility Matrix

## Purpose
- Define which MCP clients are supported now, what transport/auth mode each uses, and which compatibility settings are required.
- Keep rollout risk low by using one repeatable smoke test path per client before any release.

## Supported Clients (Phase 7 baseline)

| Client | Typical deployment | Transport | Auth model | Compat mode | Status |
|---|---|---|---|---|---|
| Claude Desktop | Local workstation | stdio | local env token (viewer/operator/admin) | `strict` | Supported |
| Cursor MCP integration | Local workstation | stdio | local env token | `strict` | Supported |
| Headless agent runners (CI/service wrappers) | Self-hosted service | HTTP (`/mcp`) behind TLS | bearer token via secret manager | `strict` | Supported |
| Legacy MCP wrappers with dot-method calls | Local or remote | stdio or HTTP | token-auth as configured | `lenient_v1` | Supported (compat path) |

## Compatibility Notes
- Default mode is `strict` (spec-native MCP method names and field names).
- `lenient_v1` is only for clients that need:
  - method aliases like `tools.call` in place of `tools/call`,
  - field aliases like `input_schema` in addition to `inputSchema`,
  - argument alias `args` in place of `arguments`.
- All new clients should be onboarded in `strict` first; only enable `lenient_v1` when strict-mode interop fails.

## Standard Smoke Checklist (All Clients)
- Start server and complete `initialize`.
- Run `tools/list` and confirm core memory/chat tools are visible for current role.
- Run `ops.health` and verify upstream runtime health payload is returned.
- Run one read-only memory tool (`memory.list_episodes`) and confirm bounded results.
- Run `capabilities.get` and verify transport, limits, auth role, and compat metadata are present.

## Regression SOP (Required for client onboarding or compatibility changes)
- Pass 1 (targeted): run MCP unit tests focused on protocol parsing, auth, and tool response shape.
- Pass 2 (full): run full repo test suite after targeted tests are green.
- Only promote client status to “Supported” after both passes are green and smoke checklist is complete.
