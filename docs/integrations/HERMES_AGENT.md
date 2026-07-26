# Hermes Agent Integration

## v0.2.3 adapter

v0.2.3 provides an optional general Hermes plugin, `mno-memory`, pinned to Hermes Agent v0.19.0. It is an information-only MNO sidecar, not a Hermes memory-provider replacement or a change to Hermes core.

For each eligible root, human-facing turn, the plugin builds bounded MNO context before the model call and, after a successful completed turn, offers a provisional observation in the background. The agent does not need to remember to call an MNO tool for that routine path. Interrupted, failed, empty, skipped, ambiguous-origin, child, cron, curator, background, and internal turns are not automatically observed.

The adapter is fail-open and nonblocking: unavailable, slow, unauthorized, or invalid MNO responses leave the Hermes reply path unchanged. Its transport is plain HTTP to a validated loopback runtime only; redirects and proxy routing are rejected.

## Authority and information boundaries

The dedicated `NO_INTEGRATION_HERMES_ADAPTER_TOKEN` is shared by the local Hermes and MNO processes, but the server constrains it to exactly `health.get`, `capabilities.get`, `context.build`, and `memory.observe`. It has no canonical, review, writeback-apply, publish, verify, or activation authority. Automatic observation remains provisional; HCR's initial curation and the ordinary human review/publish/activate path remain in force.

Injected context is a validated `mno.agent_context.v2` fact envelope in an `MNO_MEMORY_CONTEXT_V1` wrapper. It carries information and provenance, never behavioral instructions for the agent.

## Privacy and coexistence

The adapter itself does not persist recalled context in its own files or logs. Hermes v0.19.0 does persist the composed API-bound augmented user content in `messages.api_content` and may replay it in later prompt history. Removing the adapter does not scrub that Hermes-owned history.

MCP remains optional. MCP configuration alone does not produce a second automatic observation, but explicit MCP `memory.observe` calls can intentionally duplicate content. The adapter neither disables nor deduplicates a configured Hermes memory provider; overlapping memory systems can contribute competing or duplicate context/observations.

## Lifecycle surface

The lifecycle family is `mno-hermes install`, `status`, `doctor`, and `uninstall`. Rerun `install` for the ownership-checked atomic update path. The lifecycle command accepts configuration references such as the runtime URL and token environment name, never a bearer-token value on its command line or in adapter config.

`doctor` and live status are read-only probes. They report installation/configuration and the limited runtime capability state; they do not claim hook history or canonical/review authority. The installer is ownership-scoped and does not alter MNO stores, reviewed cards, or Hermes sessions during removal.

### Install

Complete initial HCR curation and start MNO with the dedicated token in its environment:

```bash
export NO_INTEGRATION_HERMES_ADAPTER_TOKEN="generate-a-long-local-secret"
mno-runtime --memories /path/to/atoms.sqlite3 --episodes /path/to/episode_cards.reviewed.json
```

Set the same variable in the Hermes environment, then:

```bash
mno-hermes install
mno-hermes doctor
```

PowerShell uses `$env:NO_INTEGRATION_HERMES_ADAPTER_TOKEN = "..."`. Restart Hermes after install, repeat-install update, or uninstall. `mno-hermes status` performs static ownership/config checks; add `--live` to include the read-only runtime probe.

If the runtime reports `CURATION_REQUIRED`, open the local review room with `mno-curate --store /path/to/atoms.sqlite3`, finish human review through Publish, Verify, and Activate, then restart the normal runtime with the reviewed episode-card file.

For a reproducible adapter defect, save `mno-hermes doctor --json`, then run `mno-report --title "Hermes adapter: ..." --summary "..." --steps "..." --expected "..." --actual "..." --check quick` and review the redacted local bundle before any explicit `--submit`. Do not add conversation exports, tokens, or Hermes `messages.api_content` databases to a public ticket.

## Compatibility posture

The adapter is designed and tested against the pinned Hermes v0.19.0 lifecycle. Native Windows with Python 3.12 has a real installed-Hermes proof for CLI and a Discord/gateway-shaped human turn. Other operating systems remain unclaimed until the same installed lifecycle proof runs there. MNO requires Python 3.12+; the copied stdlib-only plugin has an additional standalone Python 3.11 import proof. Standalone loopback MNO operation does not require MCP.

For generic, explicit orchestration, `integration-v1` remains the stable public contract. See [Agent Integration](../AGENT_INTEGRATION.md) and [API](../API.md).
