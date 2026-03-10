# MCP Tool Versioning and Compat-Mode Policy

## Policy Goal
- Keep MCP integrations stable while allowing incremental expansion of tools and outputs.
- Prevent silent client breakage by making all contract changes explicit and test-gated.

## Version Signals
- `protocol_version`: MCP protocol contract level.
- `toolset_version`: NumquamOblita MCP tool surface version.
- Both values are reported in `capabilities.get` and are required release metadata.

## Stable Naming Rules
- Tool names are lowercase, dot-separated, and immutable once published.
- Do not rename an existing tool.
- If behavior must materially change, publish a new tool name and deprecate the old one.

## Allowed vs. Breaking Changes
- Allowed without major bump:
  - add optional input fields,
  - add optional output fields,
  - add new tools,
  - tighten internal validation without changing valid request behavior.
- Breaking (requires new tool name or explicit major compatibility window):
  - removing required fields,
  - changing output field meaning,
  - changing permission tier in a way that blocks existing valid workflows without migration guidance.

## Deprecation Workflow
- Mark deprecated tools in release notes and capabilities metadata.
- Keep deprecated tools active through at least one planned compatibility window.
- Provide direct replacement mapping and migration checklist before retirement.

## Compat Mode Contract
- Default mode: `strict`.
- Optional mode: `lenient_v1` for legacy clients that require alias method/field shapes.
- `lenient_v1` is a migration aid, not the default interface.
- Any new alias behavior must be:
  - explicit in this policy,
  - covered by targeted unit tests,
  - validated by full-suite regression before release.

## Release Checklist (Required)
- Update compatibility matrix status for impacted clients.
- Run two-pass regression:
  - Pass 1: targeted MCP protocol/shape/auth tests,
  - Pass 2: full repo suite.
- Confirm `capabilities.get` reports correct protocol/toolset/compat metadata.
- Validate at least one strict-mode and one compat-mode smoke path when compat logic changes.
