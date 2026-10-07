# Compatibility and Support

This is the maintained public support contract. MNO v0.3.0 inherits the v0.2.4 host/artifact baseline. Publication status and verified release artifacts are recorded in [GitHub Releases](https://github.com/EmergentKnowledgeGroup/ModelNumquamOblita/releases).

## Supported surfaces

| Surface | Supported hosts | Contract |
| --- | --- | --- |
| Python headless runtime, MCP, import, setup, and HCR | CPython 3.12-3.14 on current x64 Windows, Ubuntu, and macOS | Wheel/sdist and source checkout; `mno-curate` and `mno-curation-mcp` are generic loopback-local surfaces; mutable state is external to installed code |
| Electron source/development shell | Node 22 on current Windows, Ubuntu, and macOS | Node tests are cross-platform; packaging uses a target-native managed runtime |
| Exported integration bundles | POSIX shell, PowerShell, or Command Prompt with installed MNO commands | Relocatable launchers; no embedded checkout or automatic install |
| WSL integration | WSL with Linux Python/Node executables | Windows `.cmd` files are rejected inside WSL; WSL is optional, not a Windows prerequisite |

ARM64 desktop installers are not claimed by v0.2.4. Source Python may work on additional architectures, but that is not release support until the exact artifact/host combination is gated.

## Interpreter rule

MNO selects an argument-vector command that proves Python 3.12 or newer. It can represent `py -3.12`, an explicit absolute interpreter, a virtual environment, or `/usr/bin/python3`. `ensurepip` is not a runtime capability requirement; an otherwise usable uv-managed environment is valid.

## State and paths

- Source checkout defaults to its `runtime/` tree.
- Installed Windows uses `%LOCALAPPDATA%\ModelNumquamOblita` (falling back to `%APPDATA%`).
- Installed macOS uses `~/Library/Application Support/ModelNumquamOblita`.
- Installed Linux uses `$XDG_STATE_HOME/modelnumquamoblita` or `~/.local/state/modelnumquamoblita`.
- `MNO_RUNTIME_STATE_ROOT` explicitly overrides these defaults.
- `runtime/imports` is canonical. Legacy `.runtime/imports` is fallback-only and must not silently win when both exist.

## Client and capability rule

Executable presence is not client compatibility. Connector setup probes identity, version, and required subcommands. Configuration writes are current-user scoped, backup-protected, and atomic. A failed replacement keeps the prior working configuration.

An integration must call capabilities and obey effective availability. Tool exposure, role authorization, separate `review_apply` authority, backend availability, policy state, and degradation are distinct facts.

Normal headless launch requires an explicitly supplied reviewed episode set for
an explicitly supplied store. Missing curation fails closed with
`CURATION_REQUIRED`; it never borrows an unrelated global episode artifact.
The HCR agent profile is bound to one wizard run and cannot publish, verify,
activate, install integrations, promote proposals, or force-release a lease.

## Artifact safety

Python and desktop manifests deny populated stores, WAL/SHM files, WSS data, checkpoints, reports, traces, caches, and live runtime directories. The CI release artifact job builds the exact wheel and sdist, checks manifests, installs the wheel without a source checkout, launches claimed CLI help surfaces, and records SHA-256 digests.

See [Distribution Notes](../DISTRIBUTION.md), [Quickstart](QUICKSTART.md), and [Security and Privacy](SECURITY_AND_PRIVACY.md).

## v0.2.2 additive temporal compatibility

Temporal support is additive to `integration.v1` and MCP parity. Clients discover `temporal_context_v1`, `temporal_memory_v1`, `temporal_due_poll`, and `agent_context_v2` through capabilities rather than assuming a version string grants access. Existing response fields remain additive.

Fresh installs and v0.2.1 upgrades expose compact server-clock facts by default. Scheduling and due injection follow provisional-memory enablement. When that feature is disabled, clock facts remain available and temporal-memory operations fail with a clear disabled reason. Generic HTTP and MCP clients need no vendor-specific executable: the heartbeat is only a bounded read poll, never a daemon or host action.

## v0.2.4 Hermes adapter compatibility

`mno-memory` is an optional general plugin pinned to Hermes Agent v0.19.0. It works against a standalone loopback MNO runtime; MCP is optional. It uses a dedicated `NO_INTEGRATION_HERMES_ADAPTER_TOKEN` restricted to health, capabilities, context build, and provisional observation, with no review or canonical authority.

The adapter is designed to fail open and to observe only successful completed eligible turns. It supplies factual `mno.agent_context.v2` context before a turn and keeps automatic observations provisional. HCR curation and the ordinary human review/publish/activate gates remain unchanged.

Native Windows with Python 3.12 has a real installed-Hermes proof for CLI and a Discord/gateway-shaped human turn, including interrupted-turn suppression. macOS and Linux installed-Hermes lifecycles remain unclaimed until the same proof runs there. MNO itself requires Python 3.12+; the copied stdlib-only plugin also has a standalone Python 3.11 import proof. Hermes v0.19.0's `messages.api_content` persistence/replay of augmented API-bound user content is a disclosed host behavior, not an MNO persistence guarantee.

## Lean-memory compatibility

Existing context callers can omit `answer_claims`. V2 HTTP and MCP context calls accept the optional string array and return additive verdict fields; compact `mno.agent_context.v2.verification` survives its context budget. Consumers must distinguish `retrieved_evidence` from `answer_claims` and honor `ABSTAIN`. This is deterministic canonical wording support, not a new semantic classifier.

MCP `integration.learning.propose` is an operator/admin convenience tool with mutations enabled; it composes existing why/propose operations and stays pending human review. HTTP has no new learning endpoint. Existing Hermes automatic observation remains unchanged, and its restricted credential cannot submit learning drafts. OpenClaw/Nanobot compatibility envelopes remain available, but v0.3.0 includes no native OpenClaw lifecycle adapter. MCP configuration alone is not automatic capture.

MCP/runtime source-selection briefs add selected-row `summary_support`, with the selected reference first; legacy aggregate confidence is preserved. No new model or runtime dependency, migration, installer, or expanded OS support is implied. See [v0.3.0 release notes](RELEASE_NOTES_v0.3.0.md).
