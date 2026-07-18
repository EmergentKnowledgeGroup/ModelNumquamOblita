# Human Changelog

## v0.2.2 — temporal agency (2026-07-18)

MNO can now carry a small, honest “what time is it / what future note is due?” layer. It reports facts from the server clock and can retain source-backed provisional reminders or future events. It still cannot wake itself up, call anyone, send notifications, decide what the agent should do, or turn a reminder into canonical truth.

The key safety fix is that four things are no longer blurred together: who owns a memory, how much independent evidence supports it, whether it is normally easy to recall, and whether a future note is scheduled or resolved. A memory fading from active to dormant to archived does not mean it is false or deleted. Seeing it again does not strengthen it. Only genuinely new signed evidence can do that.

For the technical details, see [v0.2.2 release notes](RELEASE_NOTES_v0.2.2.md).
