# Installed MNO Runtime

This package provides the local headless runtime and MCP command surfaces:

```text
mno-runtime --setup-mode
mno-mcp --help
mno-import --help
```

Mutable databases, policy, locks, reports, and diagnostics live in the
platform user-state directory by default. Set `MNO_RUNTIME_STATE_ROOT` to use
an explicit writable location.

The Electron desktop application is distributed separately from the Python
wheel. See the public repository documentation for desktop packaging and the
full build/review/publish workflow.
