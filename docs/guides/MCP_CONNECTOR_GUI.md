# MCP Connector GUI

Use this when you want a minimal point-and-click setup path for NumquamOblita MCP.

## What it does

The connector GUI opens a native Windows desktop window that can:

- pick a known memory DB from a dropdown
- open a file picker instead of making you type long paths
- preview the exact MCP config that will be installed
- install the server into Claude Code in the current environment
- install the server into Claude Desktop on Windows through WSL
- export generic MCP JSON payloads for other clients
- explain confusing settings with inline hover/focus help

It does not replace the server. It writes or installs the correct config that points clients at `tools/run_claude_live_mcp.py`.

## Fastest path

### From Windows Explorer

Double-click:

```text
tools\run_mcp_connector_gui.cmd
```

That batch file starts the native GUI window through Windows Python.

### From WSL / Linux shell

```bash
python3 tools/run_mcp_connector_gui.py
```

That path proxies into the same Windows desktop launcher and then exits.

## Recommended defaults

- Memory DB: `runtime/stores/claude_no.sqlite3` for live Claude feel-testing
- Larger cross-check DB: `runtime/stores/no_lyra.sqlite3`
- Default role: `viewer`
- Compat mode: `strict`
- Claude Code scope: `local` unless you want it available everywhere

## Client targets

### Claude Code

The GUI installs Claude Code through the real MCP command inside WSL:

```text
claude mcp add-json
```

It removes the same-name entry in the chosen scope first, then re-adds the updated config using the WSL-safe POSIX launcher path.

### Claude Desktop

The GUI updates the Windows Desktop config file under:

```text
AppData\Roaming\Claude\claude_desktop_config.json
```

A timestamped backup is written before the file is changed.

### Other MCP clients

Use `Export Generic MCP`.

The saved export bundle includes:

- a POSIX stdio payload for Linux/WSL-native MCP clients
- a Windows-via-WSL payload for Windows clients that should spawn the server through WSL
- the exact `claude mcp add-json` command payload used for Claude Code

## Safety notes

- `Preview Config` is read-only.
- Desktop config writes are backup-first.
- Existing export files require confirmation before overwrite unless they were written by the connector itself.
- The default install path does not inject auth-token placeholders into local stdio configs.
- Mutation tools stay off unless you explicitly enable them.
