# Compatibility and Support

This is the public support contract for MNO v0.2.1.

## Supported surfaces

| Surface | Supported hosts | Contract |
| --- | --- | --- |
| Python headless runtime, MCP, import, setup | CPython 3.12-3.14 on current x64 Windows, Ubuntu, and macOS | Wheel/sdist and source checkout; mutable state is external to installed code |
| Electron source/development shell | Node 22 on current Windows, Ubuntu, and macOS | Node tests are cross-platform; packaging uses a target-native managed runtime |
| Exported integration bundles | POSIX shell, PowerShell, or Command Prompt with installed MNO commands | Relocatable launchers; no embedded checkout or automatic install |
| WSL integration | WSL with Linux Python/Node executables | Windows `.cmd` files are rejected inside WSL; WSL is optional, not a Windows prerequisite |

ARM64 desktop installers are not claimed by v0.2.1. Source Python may work on additional architectures, but that is not release support until the exact artifact/host combination is gated.

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

## Artifact safety

Python and desktop manifests deny populated stores, WAL/SHM files, WSS data, checkpoints, reports, traces, caches, and live runtime directories. The CI release artifact job builds the exact wheel and sdist, checks manifests, installs the wheel without a source checkout, launches claimed CLI help surfaces, and records SHA-256 digests.

See [Distribution Notes](../DISTRIBUTION.md), [Quickstart](QUICKSTART.md), and [Security and Privacy](SECURITY_AND_PRIVACY.md).
