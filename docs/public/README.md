# Public Overview

ModelNumquamOblita is a local-first memory runtime for agents that need trustworthy recall, not just raw search.

What makes it different:
- evidence is the authority
- reviewed memory stays separate from draft and runtime-helper layers
- the system can say `I can't find that` instead of bluffing
- it can start from raw files or folders, not just a prebuilt store
- it can show bounded original context when exact wording matters
- it keeps reviewed correction chains so current truth is easier to separate from superseded truth

Core pieces:
- evidence atoms
- reviewed episode cards
- bounded retrieval with a local ANN helper
- a read-only raw-context sidecar for quote and provenance requests
- verifier-guarded runtime behavior
- optional MCP and adapter surfaces

Further reading:
- [Public Architecture](ARCHITECTURE.md)
- [Response To "Why Long-Term Memory Remains Unsolved"](MNO_RESPONSE_TO_WHY_LONG_TERM_MEMORY_REMAINS_UNSOLVED_2026-04-12.md)
