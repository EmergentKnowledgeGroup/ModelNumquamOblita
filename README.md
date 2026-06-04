# ModelNumquamOblita

ModelNumquamOblita, or `MNO`, is my local-first memory project for agents.

The simple version: it helps an assistant remember from real evidence instead of guessing from vibes.

MNO is built around a small rule that matters a lot:

`No memory claim without evidence.`

That means memories are not just loose notes floating around in a prompt. They come from source material, get shaped into reviewable memory, and stay tied to the evidence they came from. If MNO cannot find enough support for something, it should be able to say so.

## Why This Exists

Long-term memory for agents can get weird fast.

Sometimes systems remember things that were never said. Sometimes drafts turn into "truth" without anyone noticing. Sometimes a model sounds confident because confidence is cheap, not because the evidence is there.

MNO is my attempt at a more grounded path:

- keep the source evidence close
- separate drafts from reviewed memory
- let a human stay in charge of what becomes durable truth
- give agents a local memory runtime they can query without taking over the whole system
- make it possible to inspect why something was recalled

It is not trying to be a giant hosted memory platform. It is a local, inspectable memory runtime for people building agents who care about provenance, correction, and honesty.

## The Picture Version

These are the plain-language diagrams. They are intentionally simple because the main idea should not require a PhD in repo archaeology.

### Launch Pipeline

How raw source material becomes usable, reviewed memory.

![MNO launch pipeline](docs/visuals/exports/clean/mno-launch-pipeline-clean.svg)

### Runtime And Integration

How an assistant, MCP sidecar, or integration talks to the local runtime.

![MNO runtime and integration](docs/visuals/exports/clean/mno-runtime-integration-clean.svg)

### Current Pipeline

The practical shape of the current system.

![MNO current pipeline](docs/visuals/exports/clean/mno-current-pipeline-clean.svg)

### Runtime Memory And Decision

How a runtime answer moves through memory, evidence, and the decision to answer or abstain.

![MNO runtime memory decision](docs/visuals/exports/clean/mno-runtime-memory-decision-clean.svg)

More diagrams live in:

- [Plain-language diagram exports](docs/visuals/exports/clean/README.md)
- [Engineer architecture diagrams](docs/visuals/exports/architecture/README.md)
- [Visuals guide](docs/visuals/README.md)

## What You Can Use It For

MNO can help you build a local memory layer for:

- personal assistant experiments
- agent sidecars
- MCP-based tools
- local research or writing companions
- systems where memory needs to be reviewable instead of magical

It can start from raw files and folders, or from an existing MNO store. The setup flow can import source material, build draft memory, let you review what should become durable, and then run a local memory runtime over that reviewed set.

## What It Does

MNO can:

- import raw source files like `.json`, `.jsonl`, `.txt`, `.md`, and mixed folders
- preserve bounded original wording for quote and provenance lookups
- build draft episode cards for human review
- keep draft/proposal/helper memory separate from reviewed truth
- compile reviewed episode cards for runtime use
- run locally through the desktop shell, HTTP runtime, MCP server, or integration routes
- show evidence and context for why memory was recalled
- abstain when evidence is too weak

The main public integration boundary is `integration-v1`.

MCP is available when you want tool-style local agent integration. Compatibility adapters also exist for `reference`, `openclaw`, and `nanobot`.

## What It Does Not Promise

MNO does not promise:

- magic memory
- silent truth mutation
- unreviewed drafts becoming published memory
- a hosted multi-user memory service
- that every old internal route is a stable public contract

The bias here is deliberate: better to be a little slower and more inspectable than fast and quietly wrong.

## Quick Start

Use the setup workspace if you want the guided path:

```bash
./launch_setup_workspace.sh
```

PowerShell:

```powershell
./launch_setup_workspace.ps1
```

Command Prompt:

```bat
launch_setup_workspace.bat
```

Or run local setup directly:

```bash
./setup_local.sh
```

PowerShell:

```powershell
./setup_local.ps1
```

Command Prompt:

```bat
setup_local.bat
```

The setup workspace is the easiest way to:

- choose files or folders to import
- create or append to a local memory store
- build reviewable memory
- export or install an integration bundle
- prepare MNO for an assistant, MCP client, or sidecar

## Manual Runtime Commands

Import raw source:

```bash
python3 tools/import_memories.py --input /absolute/path/to/source-or-folder --store runtime/imports/atoms.sqlite3
```

Start the local runtime:

```bash
python3 tools/run_live_runtime.py --memories runtime/imports/atoms.sqlite3
```

Launch the desktop shell:

```bash
npm run desktop:dev --prefix app/desktop
```

Run MCP against the runtime:

```bash
python3 tools/run_mcp_server.py --transport stdio --runtime-base-url http://127.0.0.1:7340
```

## How The Repo Is Organized

- `engine/`: runtime, retrieval, memory, MCP, adapters, and local UI
- `app/desktop/`: Electron desktop shell
- `tools/`: setup, import, build, runtime, and MCP launchers
- `tests/`: validation for setup, runtime, MCP, adapters, packaging, and contracts
- `runtime/`: empty local workspace skeleton for generated data
- `docs/`: guides, API notes, security/privacy docs, and diagrams

Generated runtime data is intentionally not committed. Your imported stores, setup reports, diagnostics, desktop logs, and local state should stay local.

## Start Reading Here

If you are new to the project:

- [Quickstart](docs/QUICKSTART.md)
- [Pipeline Guide](docs/PIPELINE_GUIDE.md)
- [Public Overview](docs/public/README.md)
- [Public Architecture](docs/public/ARCHITECTURE.md)
- [Security And Privacy](docs/SECURITY_AND_PRIVACY.md)

If you are integrating an agent or tool:

- [Agent Integration](docs/AGENT_INTEGRATION.md)
- [MCP Integration](docs/MCP_INTEGRATION.md)
- [API](docs/API.md)
- [Configuration](docs/CONFIGURATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

Integration-specific notes:

- [OpenClaw Integration](docs/integrations/OPENCLAW.md)
- [Hermes Agent Integration](docs/integrations/HERMES_AGENT.md)
- [Nanobot Integration](docs/integrations/NANOBOT.md)
- [Generic Sidecar Integration](docs/integrations/GENERIC_SIDECAR.md)

Longer public writeup:

- [Response To "Why Long-Term Memory Remains Unsolved"](docs/public/MNO_RESPONSE_TO_WHY_LONG_TERM_MEMORY_REMAINS_UNSOLVED_2026-04-12.md)

## For Engineers

The short technical shape is:

`raw source -> import/normalize -> atoms.sqlite3 -> draft episode cards -> human review -> reviewed episode cards -> runtime`

The runtime includes bounded retrieval, reviewed memory, optional local ANN candidate generation, raw-context lookup for exact wording, and verification/abstention behavior. The ANN and raw-context sidecars are helpers only. They are not truth sources and do not bypass review.

Engineer-facing diagrams:

- [System Context](docs/visuals/exports/architecture/mno-architecture-system-context.svg)
- [Build Pipeline](docs/visuals/exports/architecture/mno-architecture-build-pipeline.svg)
- [Runtime Retrieval](docs/visuals/exports/architecture/mno-architecture-runtime-retrieval.svg)
- [Memory Trust Boundaries](docs/visuals/exports/architecture/mno-architecture-memory-trust-boundaries.svg)
- [Integration Contract](docs/visuals/exports/architecture/mno-architecture-integration-contract.svg)
- [Data Lineage](docs/visuals/exports/architecture/mno-architecture-data-lineage.svg)
- [Deployment And Process Model](docs/visuals/exports/architecture/mno-architecture-deployment-process.svg)

## Release Metadata

- [License](LICENSE)
- [Security Policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Distribution Notes](DISTRIBUTION.md)
