# MNO v0.2.3 Release Notes

**Release target:** v0.2.3

v0.2.3 closes the largest gap for headless companion-agent integrations: the agent no longer has to remember to use its memory system.

## What changed

### Automatic Hermes turn memory

The optional `mno-memory` plugin is pinned to Hermes Agent v0.19.0.

- Before an eligible root human turn, it asks MNO for bounded factual context.
- Hermes receives that context through its normal pre-model hook.
- Only after a successful completed turn, the plugin enqueues one background `memory.observe` attempt.
- The resulting memory is model-owned provisional memory. It is not a reviewed episode card or canonical truth.
- Interrupted, failed, empty, internal, child/subagent, cron, curator, and background-review turns are not observed.
- If MNO is slow, unavailable, misconfigured, or unauthorized, Hermes continues without memory rather than losing the user's response.

This uses Hermes's existing plugin lifecycle. It is not a Hermes fork and does not require the model to remember a tool call.

### Headless Curation Room

The HCR is the initial human-and-agent review room for integrations that do not use the desktop application. Agents can inspect draft cards and propose edits while the human remains authoritative for every review decision. Publish, Verify, and Activate remain the normal gates.

A normal headless launch without reviewed episode cards reports `CURATION_REQUIRED` instead of silently treating raw import as ready memory.

### Narrow authority and safer diagnostics

The adapter credential is `NO_INTEGRATION_HERMES_ADAPTER_TOKEN`. The server allows it to call only:

- `health.get`
- `capabilities.get`
- `context.build`
- `memory.observe`

It cannot approve cards, resolve review truth, apply canonical writeback, publish, verify, or activate.

The adapter accepts only plain loopback HTTP and disables proxy and redirect routing. Automatic-turn runtime logs retain operation status, timing, message counts/roles, and byte sizes, but not message text, recalled context, or signed handles.

### Ownership-safe lifecycle

`mno-hermes` provides:

- `install`
- repeat `install` for an atomic owned-file update
- `status` and `status --live`
- `doctor`
- `uninstall`

The installer pins Hermes v0.19.0, hashes every owned file, keeps one bounded backup, refuses unowned/changed paths unless explicitly forced, restores prior Hermes plugin state, and reports any incomplete rollback instead of hiding it. Uninstall validates owned files and backups before changing Hermes state.

## Install

MNO itself requires Python 3.12+. Complete initial HCR curation and start the MNO runtime first.

POSIX shell:

```bash
export NO_INTEGRATION_HERMES_ADAPTER_TOKEN="generate-a-long-local-secret"
mno-runtime --memories /absolute/path/to/atoms.sqlite3 --episodes /absolute/path/to/episode_cards.reviewed.json
```

PowerShell:

```powershell
$env:NO_INTEGRATION_HERMES_ADAPTER_TOKEN = "generate-a-long-local-secret"
mno-runtime --memories C:\path\to\atoms.sqlite3 --episodes C:\path\to\episode_cards.reviewed.json
```

In the Hermes environment, set the same variable and run:

```bash
mno-hermes install
mno-hermes doctor
```

Restart Hermes. To update later, rerun `mno-hermes install`. To back out:

```bash
mno-hermes uninstall
```

Then restart Hermes again.

If startup reports `CURATION_REQUIRED`, run `mno-curate --store /path/to/atoms.sqlite3` and finish Review, Publish, Verify, and Activate before relaunching the normal runtime. To report a reproducible problem, capture `mno-hermes doctor --json`, run `mno-report --title "Hermes adapter: ..." --summary "..." --steps "..." --expected "..." --actual "..." --check quick`, and inspect the redacted bundle before choosing the explicit `--submit` action.

## Compatibility and proof boundary

- Real installed lifecycle proof: native Windows, MNO/Hermes Python 3.12, Hermes Agent v0.19.0.
- Proved surfaces: CLI human turns and a Discord/gateway-shaped human turn.
- Proved behavior: two automatic CLI turns, exact context persistence/replay through Hermes `api_content`, provisional reinforcement, gateway observation, interrupt suppression, no reviewed-card/evidence-atom/review mutation, real install, discovery, enablement, doctor, and uninstall.
- Contract/import proof: Python 3.13 MNO package path; standalone copied plugin import under Python 3.11.
- Not claimed by this release: macOS/Linux real installed-Hermes lifecycle, other Hermes versions, or automatic memory for skipped/internal/background surfaces.

Hermes v0.19.0 persists augmented API-bound user content in `messages.api_content` and can replay it in later prompt history. That is Hermes-owned session history. Removing the MNO plugin does not scrub it.

## What did not change

- Human-reviewed canonical truth remains the highest authority.
- Episode-card review remains human-authoritative.
- Provisional memory remains revisable and may mature through eligible independent reinforcement.
- MNO still provides information and context, not instructions about how an agent must act.
- MCP remains available for explicit inspection/actions, but manually calling `memory.observe` alongside the automatic adapter can duplicate an observation.

For the full operator guide, see [Hermes Agent Integration](integrations/HERMES_AGENT.md).
