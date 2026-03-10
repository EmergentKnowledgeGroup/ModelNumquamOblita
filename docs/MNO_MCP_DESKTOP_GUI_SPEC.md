# MNO MCP Desktop GUI Spec

## Goal
Replace the current browser-hosted MCP connector control panel with a real self-contained desktop GUI window that is simple enough for non-technical users to run, understand, and recover from without hand-editing paths or reading CLI instructions.

## Why This Needs A Spec
The current connector solved install/config plumbing, but it missed the user-facing requirement. Opening a localhost website is not a desktop GUI. It also forces manual path typing, exposes jargon without help text, and does not feel like a finished tool.

This spec defines a narrow MNO-only redesign for the connector UX. It does not change removed document-research/add-on surfaces, retrieval behavior, or MCP runtime semantics.

## Root Cause
The current implementation is a pure-Python stdlib browser panel because the WSL Python runtime used for development does not have a native GUI toolkit available. That led to a web page wrapper around valid installer logic.

Windows Python **is** available on the user machine (`py -3`) and includes `tkinter`, so the correct fix is to move the GUI shell to a native Windows desktop window while keeping the existing MCP config/install logic shared and testable.

## User Contract
The finished tool must satisfy all of these:

1. Launch as a real desktop window, not a browser tab.
2. Support double-click startup from Windows Explorer.
3. Allow memory DB / JSON path selection through a file picker.
4. Allow optional episode-cards file selection through a file picker.
5. Avoid requiring long hand-typed paths in normal use.
6. Explain confusing settings in plain language with hover help.
7. Default to a dark-mode UI.
8. Keep Claude Code, Claude Desktop, and generic MCP export flows in one place.
9. Preserve safe defaults (`viewer`, `strict`, mutations off).
10. Fail with clear user-facing error messages, not stack traces.
11. Remain keyboard-usable for all required actions and help text.

## Non-Goals
- No browser-hosted control panel as the primary GUI.
- No Electron/Tauri/PySide packaging phase in P0.
- No changes to retrieval quality, runtime memory behavior, or removed document-research/add-on code.
- No auto-install of Python/tooling outside the repo.
- No silent mutation enablement.

## Architecture Decision
### Chosen approach
Use a **native Windows `tkinter` desktop window** launched by Windows Python (`py -3` / `pyw -3`).

### Why
- already present on the user machine
- native file dialogs and tooltips are straightforward
- no new heavy dependency for P0
- keeps the launcher double-clickable
- avoids the localhost HTTP/browser indirection entirely

### Boundary
Keep business logic in shared MNO-only modules so GUI code is mostly presentation/controller glue.

### WSL / Windows boundary rule
- The GUI is a Windows-native app.
- If invoked from WSL, the launcher should attempt to proxy-launch the Windows GUI and then exit cleanly.
- If proxy launch is not possible, the tool must fail fast with a clear user-facing message telling the user to run the Windows launcher.
- Before any install/export action, the app must validate that the chosen file path is accessible from the side that will use it.
- If a WSL path needs to be referenced from Windows, the app must translate it to a `\\\\wsl$\\...` path or refuse the action with guidance.

## Allowed / No-Touch Surfaces
### Allowed
- `tools/run_mcp_connector_gui.py`
- `tools/run_mcp_connector_gui.cmd`
- `tools/mcp_connector_common.py`
- `tools/run_claude_live_mcp.py` only if help/config preview needs additive alignment
- `docs/guides/MCP_CONNECTOR_GUI.md`
- `docs/guides/CLAUDE_MCP_QUICKSTART.md`
- matching unit tests under `tests/unit/`

### No touch
- removed document-research/add-on surfaces
- dedicated disconnect/spec-governance docs
- retrieval/session semantics unrelated to connector install/export UX
- MCP server behavior outside additive config/launcher wiring

## UX Requirements
### Window model
- Single-window desktop app with no external browser launch.
- OS file dialogs and message boxes are allowed and expected.
- Title should clearly identify the app: `NumquamOblita MCP Connector`.
- Window opens centered and usable at laptop resolutions without scrolling on first load.
- During long-running actions, action buttons should disable to prevent accidental double execution.

### Visual direction
- Dark mode by default.
- Deliberate, polished styling; not stock OS-gray utility look.
- Strong contrast, clear hierarchy, large enough click targets.
- Aesthetic direction: restrained industrial dark UI with warm accent color and subtle depth.
- Minimum legibility rules:
  - base text size at least 12pt / 16px
  - interactive controls at least 36px tall
  - contrast at least WCAG AA for body text and primary controls

### File inputs
- Memory store path uses:
  - known-store dropdown for detected candidates
  - `Browse...` button for file-picker override
- Episode cards path uses:
  - optional field
  - `Browse...` button for file-picker selection
  - `Clear` button to unset
- Manual typing remains possible but should not be required for normal use.
- File picker cancel should preserve the prior field value.
- Allowed file dialog filters must include only supported memory types (`*.sqlite3`, `*.sqlite`, `*.db`, `*.json`) and episode-card JSON files.
- If no stores are detected, the dropdown should show an explicit empty state and the status panel should explain that the user can browse to a store manually.
- If multiple stores share the same filename, the dropdown must disambiguate them with path/source context.
- Known-store detection must include repo-known stores plus Windows-visible and `\\\\wsl$`-reachable store paths when available.

### Help affordances
Each of these controls needs an inline `(i)` or `?` help affordance with hover tooltip text in plain language:
- Default role
- Claude Code scope
- Compat mode
- Mutation tools
- Episode cards

Tooltip text must be short, concrete, and non-jargony.
The same help text must also be available on keyboard focus, not hover alone.

### Actions
Primary actions:
- `Preview Config`
- `Install Claude Code`
- `Install Claude Desktop`
- `Export Generic MCP`

Secondary actions:
- `Copy Result`
- `Open Config Folder` when a config file was created or updated
- `Open Export Folder` when an export file was written
- `Quit`

### Status and output
- A visible status strip shows `Ready`, `Working`, `Done`, or specific failure text.
- Results pane shows compact structured output and important next steps.
- Success state should tell the user what changed and where.
- Failure state should name the missing path/tool/config and how to fix it.

## Technical Design
### Shared logic split
Refactor the current browser-panel logic into testable units:

1. `mcp_connector_common.py`
- continue to own path detection, config payload construction, install/export helpers, and backup behavior
- add any small helper needed for GUI-friendly labels/metadata

2. `run_mcp_connector_gui.py`
- becomes the desktop app entry point
- owns window creation, widget layout, file dialogs, tooltips, theme application, and action wiring
- no localhost server and no browser auto-open path in the normal app flow
- owns message-box/status translation for user-facing failures

3. `run_mcp_connector_gui.cmd`
- launches the GUI through Windows Python without opening a terminal-heavy UX
- should prefer `pyw -3` when available, with a clean fallback to `py -3`

### Launch model
- Windows Explorer double-click on `.cmd` must open the GUI window.
- Running from WSL via `python3 tools/run_mcp_connector_gui.py` should either:
  - clearly error with “run this from Windows” guidance, or
  - proxy-launch the Windows GUI via `cmd.exe` / `pyw -3` and then exit cleanly.

The default user path should be the Windows-native one.
All GUI install/export actions run on the Windows side; WSL invocation must never execute write actions directly inside WSL.

Launcher failure requirements:
- If `pyw -3` is present, prefer it for a no-console launch.
- If `pyw -3` is missing but `py -3` works, use it.
- If Windows Python or `tkinter` is unavailable, show a clear recovery message with the missing prerequisite.

### Export/install behavior
Keep the current install/export behaviors, but surface them through the native GUI:
- Claude Code install still uses `claude mcp add-json`
- Claude Desktop install still writes backup-first config JSON
- Generic export still writes/prints MCP JSON payloads for other clients
- `Preview Config` must be strictly read-only and must not write files, mutate config, or invoke install/export helpers.
- Install/export actions must be idempotent where possible.
- If an action targets an existing export file, require explicit confirmation first unless the file already contains a connector-written signature/header for safe overwrite.
- If a same-name MCP entry already exists, the result panel must say whether it was replaced, updated, or left unchanged.

### Data validation
Before any action runs, validate:
- memory path exists and is a supported file type (`.sqlite3`, `.sqlite`, `.db`, `.json`)
- episode cards file exists if provided
- server name is valid
- role / scope / compat values are in allowlists
- mutation toggle is explicit, default-off
- validation rules must be shared between preview/install/export paths

Allowed values:
- `default_role`: `viewer`, `operator`, `admin`
- `claude_code_scope`: `local`, `user`, `project`
- `compat_mode`: `strict`, `lenient_v1`

### Error handling
- Convert exceptions into user-facing message boxes or status text.
- Never dump raw tracebacks into the main UI.
- Keep debug detail available in structured result text for troubleshooting.

## Phase Plan
## P0: Native Window Replacement
Goal: replace browser page with a real desktop GUI while preserving current config/install behavior.

Scope:
- native `tkinter` window
- dark-mode theme
- detected-store dropdown
- file-picker buttons for memory DB and episode cards
- hover tooltips for confusing options
- current preview/install/export flows wired into buttons
- user-facing success/error messaging
- updated docs and launcher

Done when:
- no browser opens
- double-click launcher opens a real window
- a user can select `claude_no.sqlite3` without typing its path
- Claude Code and Claude Desktop installs still work
- generic export still works
- tooltips/help are available on hover and keyboard focus
- dark mode is the default rendered state

Regression gates:
- targeted unit tests for controller/state/validation helpers
- targeted tests for launcher behavior and install/export wiring
- full `pytest -q`
- no browser/localhost control-panel path remaining in the primary GUI flow

## P1: UX Hardening
Goal: remove remaining friction and ambiguity.

Scope:
- clearer result copy (what changed, where, what to do next)
- open-config/open-export convenience buttons
- improved empty/error states
- window sizing polish for typical laptop screens

Done when:
- non-technical user can recover from common path/config failures without docs
- output panel consistently explains next step after each action

Regression gates:
- targeted unit tests for new controller helpers
- full `pytest -q`

## P2: Optional Packaging / Distribution
Goal: decide whether the GUI should become a packaged standalone Windows app.

This phase is optional and only justified if the Python-installed path still creates real user friction.

Possible scope:
- packaged `.exe`
- app icon / installer polish
- signed release packaging if distribution requires it

This phase must be backed by actual user friction, not aesthetics alone.

## Testing Strategy
### Unit tests
Add or update tests for:
- known-store detection and default selections
- validation of role/scope/compat/path inputs
- tooltip/help metadata presence for required fields
- tooltip/help availability on keyboard focus
- action wiring calling shared install/export helpers
- `.cmd` launcher text/behavior expectations
- no browser-launch code path remaining in the main GUI flow
- WSL proxy-launch / fail-fast behavior
- overwrite confirmation or idempotent replace behavior
- no-store-detected empty state
- duplicate-store disambiguation
- file-picker cancel preserving previous values

### Manual smoke tests
Required before PR:
1. open GUI from Windows launcher
2. pick `claude_no.sqlite3` through picker/dropdown
3. preview config
4. install Claude Desktop
5. install Claude Code
6. export generic MCP payload
7. verify failure message on an invalid path
8. verify help text is visible by mouse hover and keyboard focus
9. verify repeated clicks do not trigger double execution

### Regression rule
If the tool again opens primarily as a browser-hosted control panel, the slice is not done.
If the tool ships without file-picker-driven path selection, keyboard-accessible help, or dark mode by default, the slice is not done.

## Rollout / Backout
### Rollout
- keep changes isolated to MNO GUI/install surfaces
- open one focused PR for P0
- wait for CodeRabbit
- clear all actionable comments
- merge only when tests are green and UX contract is met
- do not call P0 done until Windows manual smoke checks are completed, even if Linux CI/unit tests are green

### Backout
If the native GUI path introduces instability:
- keep shared install/export logic intact
- revert only the GUI shell/launcher layer
- do not revert config/install helpers unless they regress independently
- WSL proxy-launch or path-translation breakage is an explicit backout trigger for the GUI shell/launcher layer

## Implementation Touchpoints Map
### User Contract / UX core
- `tools/run_mcp_connector_gui.py`
- `tools/mcp_connector_common.py`
- `tools/run_mcp_connector_gui.cmd`
- `tests/unit/test_run_mcp_connector_gui.py`
- `tests/unit/test_mcp_connector_common.py`

### Install / export plumbing
- `tools/mcp_connector_common.py`
- `tools/run_claude_live_mcp.py` only if config-preview/help alignment is required
- `tests/unit/test_mcp_connector_common.py`
- `tests/unit/test_run_claude_live_mcp.py` only if preview contract changes

### Docs / handoff
- `docs/guides/MCP_CONNECTOR_GUI.md`
- `docs/guides/CLAUDE_MCP_QUICKSTART.md`

### Forbidden / Later Scope
- removed document-research/add-on surfaces
- dedicated disconnect/spec-governance docs
- unrelated runtime/retrieval/session code

## Open Questions To Resolve In Spec Review
1. Should generic export write to a chosen file path by default, or only preview/copy unless user clicks Save?
2. Should the GUI expose server-name editing in P0, or treat that as an advanced option collapsed by default?

## Recommended Initial Answers
1. Generic export should support `Save As...` in P0 because that matches the file-picker-first UX contract.
2. Server name can stay visible in P0, but advanced/rare controls should be grouped lower in the form.
