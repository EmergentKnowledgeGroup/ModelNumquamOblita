# Claude MCP Quickstart

Use this path when you want Claude Desktop, Claude Code, or another MCP client to talk to a real local NumquamOblita memory store without manually starting a separate runtime server first.

## What this launcher does

`tools/run_claude_live_mcp.py` starts:

1. a local runtime API against the chosen SQLite store on an ephemeral loopback port
2. the MCP server in the same process

That means Claude only needs one stdio command.

## Recommended stores

Replace these example paths with the local store paths on your machine:

- Claude-focused local test: `<repo_root>/runtime/stores/claude_no.sqlite3`
- Larger cross-check store: `<repo_root>/runtime/stores/no_lyra.sqlite3`

Default fallback behavior looks for `.runtime/imports/atoms.sqlite3` relative to the repo root.

## GUI setup path

For the simplest flow, use the native connector window:

Windows Explorer one-click launcher:

```text
tools\run_mcp_connector_gui.cmd
```

WSL launcher (proxies into the Windows GUI and exits):

```bash
python3 tools/run_mcp_connector_gui.py
```

See [MCP_CONNECTOR_GUI.md](MCP_CONNECTOR_GUI.md) for the point-and-click path.

## Dry-run / config preview

```bash
python3 tools/run_claude_live_mcp.py \
  --memories <repo_root>/runtime/stores/claude_no.sqlite3 \
  --print-claude-config
```

## POSIX stdio config pattern

```json
{
  "mcpServers": {
    "numquamoblita-live": {
      "command": "/usr/bin/python3",
      "args": [
        "/abs/path/to/NumquamOblita/tools/run_claude_live_mcp.py",
        "--memories",
        "<repo_root>/runtime/stores/claude_no.sqlite3",
        "--default-role",
        "viewer",
        "--compat-mode",
        "strict"
      ]
    }
  }
}
```

## Notes

- Default role is `viewer` for safe local testing.
- Add `--episodes /abs/path/to/episode_cards.json` if you want a specific episode-card artifact instead of auto-discovery.
- For HTTP transport testing, pass `--transport http --http-port <port>`, but local Claude attach should use stdio.
- For Windows Claude Desktop, use the GUI installer so it writes the WSL-backed `wsl.exe` config entry instead of this POSIX-only snippet.
