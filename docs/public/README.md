# Public Overview

ModelNumquamOblita is a local-first memory runtime for agents that need trustworthy recall, not just raw search.

If you are an LLM or integrating agent, begin with the repository-level [LLM read-first contract](../../LLMS.md).

What makes it different:
- evidence is the authority
- reviewed memory stays separate from draft and runtime-helper layers
- the system can say `I can't find that` instead of bluffing
- it can start from raw files or folders, not just a prebuilt store
- it can show bounded original context when exact wording matters
- it keeps reviewed correction chains so current truth is easier to separate from superseded truth

Core pieces:
- evidence atoms
- revisable observed, reinforced, and consolidated provisional memory beneath evidence and reviewed truth
- reviewed episode cards
- bounded retrieval with a local ANN helper
- a read-only raw-context sidecar for quote and provenance requests
- a built-in work-session scratchpad for strict project/thread/workstream scoped `scratchpad_ephemeral` context packages
- verifier-guarded runtime behavior
- optional MCP and adapter surfaces
- a generic Headless Curation Room for human review without the desktop shell

Truth order is simple: human-reviewed canonical truth wins; evidence atoms remain source-backed substrate; provisional memory is labeled and revisable. A work-session scratchpad or short-term session context can help an agent continue work, but neither is evidence.

Further reading:
- [v0.2.1 release notes](../RELEASE_NOTES_v0.2.1.md)
- [v0.2.2 temporal agency notes](../RELEASE_NOTES_v0.2.2.md)
- [human changelog](../CHANGELOG.md)
- [Compatibility and support](../COMPATIBILITY_AND_SUPPORT.md)
- [Agent support tickets](../SUPPORT_TICKETS_FOR_AGENTS.md)
- [Headless Curation Room](../HEADLESS_CURATION_ROOM.md)
- [Public Architecture](ARCHITECTURE.md)
- [Work-Session Scratchpad](../WORK_SESSION_SCRATCHPAD.md)
- [Response To "Why Long-Term Memory Remains Unsolved"](MNO_RESPONSE_TO_WHY_LONG_TERM_MEMORY_REMAINS_UNSOLVED_2026-04-12.md)

## Temporal agency, plainly

MNO can show an assistant what time the server says it is and surface a few source-backed, provisional future notes when their time window is due. That does not make MNO a calendar app or a bot that wakes itself up: it does not send notifications, make calls, decide what the assistant should do, or turn a reminder into truth.

The same note has separate labels for who owns it, how much independent evidence supports it, how normally available it is for recall, and whether it is scheduled/snoozed/resolved. Provisional recall can fade from active to dormant to archived. A strong direct cue can bring a dormant note back with a warning; only new signed evidence can reactivate it. Seeing a note again, delivering it, or repeating it does not make it more trustworthy.
