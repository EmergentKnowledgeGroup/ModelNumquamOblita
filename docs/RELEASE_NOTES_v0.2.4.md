# MNO v0.2.4 — Hermes supervised-gateway fix

v0.2.4 fixes an installation/runtime environment split in the optional Hermes
v0.19.0 automatic-turn adapter.

`mno-hermes install` previously verified the scoped adapter token in the
installer shell, while the loaded gateway plugin required that token to be
inherited by the gateway process. A service or supervisor could therefore
produce a healthy doctor result while loading silent no-op hooks.

The installer now writes the scoped credential to an ownership-checked
`~/.hermes/mno/adapter-token` file. The gateway environment still takes
precedence when present. On POSIX, group/world-readable credential files are
rejected. Update and uninstall refuse missing or changed owned credentials
unless the operator explicitly uses the existing force path.

`doctor --json` and `status --live --json` now report `credential_source` as
`environment`, `credential_file`, or `missing` without exposing the token.

The credential remains limited server-side to `health.get`,
`capabilities.get`, `context.build`, and `memory.observe`. It cannot approve,
review, publish, verify, activate, or mutate canonical truth.

Validation includes focused installer/adapter security tests and a real
installed Hermes lifecycle with the token deliberately removed from the Hermes
process before CLI and Discord/gateway-shaped turns.
