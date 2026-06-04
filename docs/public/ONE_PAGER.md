# One Pager

ModelNumquamOblita, or `MNO`, is a local-first memory runtime for agents and operator-driven workflows.

What it does:
- imports raw memory evidence into a durable atom store
- builds draft episode cards and compiles reviewed episode memory
- runs a local runtime over HTTP, adapters, and MCP
- ships a managed Electron desktop shell
- keeps runtime helper memory separate from reviewed truth

What it is built to do well:
- evidence-backed recall
- reviewed durable memory
- bounded retrieval
- honest abstention when evidence is weak

What it does not promise:
- silent truth mutation
- magic multi-tenant memory sharing
- unversioned internal routes as a stable public API
