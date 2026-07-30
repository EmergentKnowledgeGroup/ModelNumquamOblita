# Human Changelog

## v0.2.4 — Hermes supervised-gateway credential fix (2026-07-29)

- Removed the Hermes gateway's dependence on inheriting the install shell's adapter token.
- Added an ownership-checked adapter credential file with POSIX permission checks.
- Made doctor report the effective credential source without exposing the token.
- Added real installed-Hermes proof with the token absent from the Hermes process.

## v0.2.3 — Headless Curation Room + automatic Hermes memory (2026-07-26)

Agents that run MNO without the desktop app now have a proper human handoff instead of silently operating on raw imported memory. `mno-curate` prepares or resumes one local Headless Curation Room, where the agent can do draft work and the human can review every episode card before Publish, Verify, and Activate.

The agent connection is pinned to one run and exposes only draft-reading and proposal tools. It cannot approve itself, change rooms, publish, verify, activate, install integrations, or force another curator out. Normal `mno-runtime` and `mno-agent-mcp` launches now stop with `CURATION_REQUIRED` when reviewed episode cards are missing. A loud `--allow-uncurated` switch remains for deliberate development or recovery work.

The shared curation screen now behaves like a normal responsive web page on desktop and mobile instead of inheriting the desktop shell's fixed-height layout. The Windows PowerShell runtime wrapper also avoids PowerShell's reserved `$Host` variable, forwards the reviewed-episode and explicit-bypass flags, and uses the same canonical `runtime/imports` path as the Python launchers.

Hermes Agent v0.19.0 can now use an optional installed `mno-memory` plugin instead of relying on Lux—or any model—to remember to call MNO manually. Before an eligible human turn, it asks MNO for compact factual context. After a successful completed turn, it makes one background provisional-memory observation attempt. Interrupted, failed, empty, child, cron, curator, and internal turns are not recorded.

The adapter is deliberately narrow: loopback only, fail-open, no proxy or redirects, and a dedicated token that can call only health, capabilities, context build, and provisional observation. It cannot approve cards, mutate review truth, publish, verify, or activate. Installation, repeat-install update, diagnosis, status, rollback, and uninstall are ownership-safe and leave MNO stores alone.

For setup, proof boundaries, and privacy details, see [v0.2.3 release notes](RELEASE_NOTES_v0.2.3.md).

## v0.2.2 — temporal agency (2026-07-18)

MNO can now carry a small, honest “what time is it / what future note is due?” layer. It reports facts from the server clock and can retain source-backed provisional reminders or future events. It still cannot wake itself up, call anyone, send notifications, decide what the agent should do, or turn a reminder into canonical truth.

The key safety fix is that four things are no longer blurred together: who owns a memory, how much independent evidence supports it, whether it is normally easy to recall, and whether a future note is scheduled or resolved. A memory fading from active to dormant to archived does not mean it is false or deleted. Seeing it again does not strengthen it. Only genuinely new signed evidence can do that.

For the technical details, see [v0.2.2 release notes](RELEASE_NOTES_v0.2.2.md).
