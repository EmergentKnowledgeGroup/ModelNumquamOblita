# ModelNumquamOblita

ModelNumquamOblita, or `MNO`, is a local-first memory runtime for agents that need:
- evidence-backed memory
- reviewed durable truth
- bounded retrieval
- honest abstention when evidence is weak

Core rule:

`No memory claim without evidence.`

## What MNO does

MNO can start from either:
- raw source files or folders such as `conversations.json`, `.jsonl`, `.txt`, `.md`, or mixed folders
- an existing MNO atom store plus optional reviewed episode set

From there it can:
- import evidence into `atoms.sqlite3`
- preserve bounded original wording for quote and provenance lookups
- build draft episode cards for review
- optionally let an assistant or agent help curate the draft before human review
- compile reviewed episode cards for runtime use
- keep reviewed correction chains clear so current vs superseded truth stays visible
- run a local runtime over HTTP, adapters, MCP, or the desktop shell

## What MNO does not do

MNO does not promise:
- silent truth mutation
- unreviewed draft artifacts becoming published truth
- one giant shared multi-agent runtime
- unversioned internal routes as the main public integration contract

## How you run it

MNO has 3 normal launch shapes:
- desktop app: Electron shell with managed runtime and local operator UI
- headless runtime: HTTP server over a memory store and optional reviewed episode set
- MCP sidecar: stdio or HTTP MCP server pointed at a running runtime

The normal public integration boundary is:

`integration-v1`

Compatibility adapters also exist for:
- `reference`
- `openclaw`
- `nanobot`

If you are building a new integration, prefer `integration-v1` first.

## Retrieval note

This clean repo ships with a bounded local ANN sidecar enabled by default.

`ANN` means `approximate nearest neighbor`.

In MNO it is:
- local only
- bounded
- additive candidate generation only
- kill-switchable

It is not:
- a truth source
- a verifier replacement
- a shortcut around review, publish, or evidence rules

MNO also keeps a bounded raw-context sidecar for explicit quote, original-wording, and provenance requests. That sidecar is read-only and only augments the evidence pack when the query asks for original context.

## Repo layout

- `engine/`: runtime, retrieval, memory, MCP, adapters, UI
- `app/desktop/`: Electron desktop shell
- `tools/`: setup, import, build, runtime, and MCP launchers
- `tests/`: focused validation for setup, runtime, MCP, adapters, packaging, and integration contract behavior
- `runtime/`: empty local workspace skeleton for imports, episodes, runs, and state

## Fast start

1. Use the one-click setup workspace if you want the guided path.
   - Unix/macOS: `./launch_setup_workspace.sh`
   - PowerShell: `./launch_setup_workspace.ps1`
   - Command Prompt: `launch_setup_workspace.bat`
2. Or run local setup directly.
   - Unix/macOS: `./setup_local.sh`
   - PowerShell: `./setup_local.ps1`
   - Command Prompt: `setup_local.bat`
3. Start from raw source.
   - GUI path: launch the setup workspace, click `Add Files` and/or `Add Folder`, build a mixed source list, then either create a new store or append into an existing one.
   - CLI path: `python3 tools/import_memories.py --input /absolute/path/to/source-or-folder --store runtime/imports/atoms.sqlite3`
4. Launch the runtime:
   - `python3 tools/run_live_runtime.py --memories runtime/imports/atoms.sqlite3`
5. Or launch the desktop shell:
   - `npm run desktop:dev --prefix app/desktop`
6. Or launch MCP against the runtime:
   - `python3 tools/run_mcp_server.py --transport stdio --runtime-base-url http://127.0.0.1:7340`

The setup workspace is the easiest launch path if you want to:
- open the GUI setup flow
- choose a managed client or export target
- install or export the right integration bundle
- finish with MNO ready for assistant/agent or sidecar use

Managed MCP targets currently include:
- `Claude Code`
- `Claude Desktop`

## Raw-source import behavior

The desktop import flow is picker-first now:
- `Add Files` opens a file picker
- `Add Folder` opens a folder picker
- you can mix folders and individual files in one source list
- you can clear or remove entries before import
- you can import into a new store or append into an existing store

Advanced manual path entry still exists as a fallback, but it is no longer the primary path.

Sanitization and normalization happen automatically before insert:
- supported raw files are normalized into conversations and turns
- whitespace is cleaned
- roles and timestamps are normalized when possible
- obvious junk directories are skipped in folder imports
- tool payload noise and unsupported blocks are filtered before extraction

## Pick the right integration path

- Use `integration-v1` for orchestrators, sidecars, and agent hot loops.
- Use adapter routes when you already speak an existing compatibility envelope like OpenClaw or Nanobot.
- Use MCP when you want tool-driven local agent integration or parity with the runtime contract.

## Docs

Start here:
- [Quickstart](docs/QUICKSTART.md)
- [Pipeline Guide](docs/PIPELINE_GUIDE.md)
- [Agent Integration](docs/AGENT_INTEGRATION.md)
- [MCP Integration](docs/MCP_INTEGRATION.md)
- [API](docs/API.md)
- [Configuration](docs/CONFIGURATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Security And Privacy](docs/SECURITY_AND_PRIVACY.md)

Public-facing summary docs:
- [Public Overview](docs/public/README.md)
- [Public Architecture](docs/public/ARCHITECTURE.md)
- [One Pager](docs/public/ONE_PAGER.md)
- [Teaser](docs/public/TEASER.md)

Launch visuals:
- [Clean Public Diagram Exports](docs/visuals/exports/clean/README.md)
- [Architecture Diagram Exports](docs/visuals/exports/architecture/README.md)
- [Rendered SVG/PNG Export Index](docs/visuals/exports/README.md)
- [Launch Pipeline Visual Spec](docs/visuals/MNO_LAUNCH_PIPELINE_VISUAL_SPEC_2026-04-12.md)
- [Launch Pipeline Draw.io](docs/visuals/MNO_LAUNCH_PIPELINE_2026-04-12.drawio)
- [Launch Runtime And Integration Visual Spec](docs/visuals/MNO_LAUNCH_RUNTIME_AND_INTEGRATION_VISUAL_SPEC_2026-04-12.md)
- [Launch Runtime And Integration Draw.io](docs/visuals/MNO_LAUNCH_RUNTIME_AND_INTEGRATION_2026-04-12.drawio)

Current-state visuals:
- [Current Pipeline Visual Spec](docs/visuals/MNO_CURRENT_PIPELINE_VISUAL_SPEC_2026-04-12.md)
- [Current Pipeline Draw.io](docs/visuals/MNO_CURRENT_PIPELINE_2026-04-12.drawio)
- [Current Runtime Memory And Decision Visual Spec](docs/visuals/MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_VISUAL_SPEC_2026-04-12.md)
- [Current Runtime Memory And Decision Draw.io](docs/visuals/MNO_CURRENT_RUNTIME_MEMORY_AND_DECISION_2026-04-12.drawio)

Public article response:
- [Response To "Why Long-Term Memory Remains Unsolved"](docs/public/MNO_RESPONSE_TO_WHY_LONG_TERM_MEMORY_REMAINS_UNSOLVED_2026-04-12.md)

Integration-specific docs:
- [OpenClaw Integration](docs/integrations/OPENCLAW.md)
- [Hermes Agent Integration](docs/integrations/HERMES_AGENT.md)
- [Nanobot Integration](docs/integrations/NANOBOT.md)
- [Generic Sidecar Integration](docs/integrations/GENERIC_SIDECAR.md)

## Visual tour

MNO ships generated flowcharts for both quick public explanation and engineering review.

Plain-language/caveman diagrams:
- [Launch Pipeline](docs/visuals/exports/clean/mno-launch-pipeline-clean.svg)
- [Runtime And Integration](docs/visuals/exports/clean/mno-runtime-integration-clean.svg)
- [Current Pipeline](docs/visuals/exports/clean/mno-current-pipeline-clean.svg)
- [Runtime Memory And Decision](docs/visuals/exports/clean/mno-runtime-memory-decision-clean.svg)

Engineer diagrams:
- [System Context](docs/visuals/exports/architecture/mno-architecture-system-context.svg)
- [Build Pipeline](docs/visuals/exports/architecture/mno-architecture-build-pipeline.svg)
- [Runtime Retrieval](docs/visuals/exports/architecture/mno-architecture-runtime-retrieval.svg)
- [Memory Trust Boundaries](docs/visuals/exports/architecture/mno-architecture-memory-trust-boundaries.svg)
- [Integration Contract](docs/visuals/exports/architecture/mno-architecture-integration-contract.svg)
- [Data Lineage](docs/visuals/exports/architecture/mno-architecture-data-lineage.svg)
- [Deployment And Process Model](docs/visuals/exports/architecture/mno-architecture-deployment-process.svg)

![MNO clean launch pipeline](docs/visuals/exports/clean/mno-launch-pipeline-clean.svg)

The canonical draw.io files and regeneration notes live in [Visuals Guide](docs/visuals/README.md).

## Release metadata

- [License](LICENSE)
- [Security Policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Distribution Notes](DISTRIBUTION.md)
