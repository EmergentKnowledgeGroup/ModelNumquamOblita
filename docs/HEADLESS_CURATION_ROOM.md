# Headless Curation Room (HCR)

HCR is MNO's local browser workflow for agents and users who do not use the desktop application. It is generic: Hermes, Claude, Codex, a custom MCP client, or any other compatible agent uses the same run-bound contract.

## The short version

```text
agent imports/builds
  -> MNO reports CURATION_REQUIRED
  -> agent opens one local HCR URL
  -> agent proposes; human approves, edits, or rejects
  -> publish -> verify -> activate
  -> normal memory operation
```

The agent can perform the tedious preparation and draft work. It cannot silently become the human reviewer.

## Start from raw source

Installed package:

```bash
mno-curate --input /absolute/path/to/export
```

Source checkout:

```bash
python3 tools/run_headless_curation.py --input /absolute/path/to/export
```

## Start from an imported MNO store

```bash
mno-curate --store /absolute/path/to/atoms.sqlite3
```

## Resume a room

```bash
mno-curate --run-id wizard_...
```

The command binds to loopback, prints a machine-readable `hcr_status_json=...` line and `curation_url=...`, and opens the browser unless `--no-open` is supplied. Keep the command running while the room is in use.

## Agent proposal tools

Connect a compatible MCP client to the same running HCR runtime with:

```bash
mno-curation-mcp \
  --runtime-base-url http://127.0.0.1:<port> \
  --run-id wizard_...
```

This profile is bound to one run and exposes only eight draft-curation tools:

- `wizard.draft_curation_status`
- `wizard.draft_curation_cards`
- `wizard.draft_curation_get_card`
- `wizard.draft_curation_proposals`
- `wizard.draft_curation_session_start`
- `wizard.draft_curation_session_heartbeat`
- `wizard.draft_curation_session_release`
- `wizard.draft_curation_proposal_upsert`

Supplying a different `run_id` fails. Hidden tools also fail if called directly. The agent cannot force-release another curator, promote a proposal into review truth, publish, verify, activate, install integrations, or call unrelated memory/chat/admin tools through this profile.

## Human workflow

The local browser room shows the existing MNO authority path in a focused form:

1. **Review:** inspect each generated card and any agent proposal. Approve, edit, or reject every card.
2. **Publish:** freeze the reviewed set. At least one card must remain approved or edited.
3. **Verify:** require a `Safe` result.
4. **Activate:** bind the runtime to the verified reviewed set.

The underlying state is the same wizard state used by the desktop application. HCR does not create a parallel proposal store, review ledger, or publish mechanism.

## Curation wall

Normal headless launch now requires reviewed episode cards:

```bash
mno-runtime --memories /path/to/atoms.sqlite3 --episodes /path/to/episode_cards.reviewed.json
```

Without `--episodes`, explicit store launches return `CURATION_REQUIRED` and point to `mno-curate`. `mno-agent-mcp` applies the same rule.

For development or recovery only, `--allow-uncurated` is an explicit loud bypass. It marks the runtime as `uncurated_override`. It is not a supported way to claim that raw atoms are a reviewed activated memory set.

## Security

- HCR is loopback-only in this release.
- Do not bind its runtime or MCP profile to a LAN or public address.
- Wizard/browser APIs are local operator surfaces, not public authenticated web applications.
- HCR content, wizard state, logs, stores, and episode artifacts are private runtime data.
- HTTP MCP transport requires authentication even on loopback; stdio is the simplest local agent connection.

## Agent response to `CURATION_REQUIRED`

Treat it as workflow state, not a suggestion to bypass the pipeline. Tell the user that draft memory cards are ready or need to be built, give them the local HCR URL, and collaborate on the review. Do not claim memory is ready until the HCR status reaches `ready` after publish, Safe verification, and activation.

