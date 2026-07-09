# API Matrix

## Primary public orchestration

- `integration-v1`

## Primary agent tool surface

- MCP parity tools over stdio or HTTP

## Runtime context helper surface

- WSS `work_session_context` in strict project/thread/workstream scoped v2 context packages

WSS uses trust tier `scratchpad_ephemeral`. It is work-continuity helper state, not retrieval evidence, reviewed truth, or a writeback path.

## Internal/operator surfaces

- native `/api/memory/*`
- native `/api/wizard/*`
- runtime diagnostics and packaging helpers
