# MNO Runtime Efficiency P0 Reporting Contract

Status: Active  
Updated: 2026-03-05  
Scope: `docs/MNO_RUNTIME_EFFICIENCY_SPEC.md` + `docs/MNO_RUNTIME_EFFICIENCY_BLOCKERBOARD.md` (`MREB-005`)

## Purpose

Define fail-closed run-summary language for P0 runtime-efficiency work.

If this contract is not fully present in a run summary, status is **not done**.

## Required Declarations (No Exceptions)

Every P0 runtime-efficiency run summary must include:
- `safety_verdict`
- `human_quality_verdict`
- `breach_declaration`
- `waiver_declaration`
- `final_status`

## Breach Declaration Schema

`breach_declaration` must include:
- `has_breach`: `<true|false>`
- `breach_types`: list of triggered breach codes (empty list if none)
- `stop_ship_required`: `<true|false>`
- `reason`: short explanation

Rule:
- Any threshold breach, missing required metric, or non-finite metric sets:
  - `has_breach=true`
  - `stop_ship_required=true`
  - `final_status=NOT_DONE`

## Waiver Declaration Schema

`waiver_declaration` must include:
- `has_waiver`: `<true|false>`
- `waiver_type`: `<none|frozen_surface_exception|other_approved>`
- `blocker_id`: blocker id or `none`
- `blocker_link`: path/link or `none`
- `scope`: explicit affected files/surfaces
- `expires_at`: date or `none`
- `approver`: approver id/name or `none`
- `reason`: short explanation

Rule:
- Frozen-surface exceptions must be declared as:
  - `waiver_type=frozen_surface_exception`
  - `reason` begins with `FROZEN DUE TO ...`
  - `blocker_id` and `blocker_link` are required (not `none`)

## Final Status Rule

Allowed values:
- `DONE`
- `NOT_DONE`
- `FROZEN_WITH_WAIVER`

Gate:
- `DONE` is allowed only when:
  - `safety_verdict=PASS`
  - `human_quality_verdict=PASS`
  - `has_breach=false`
  - `has_waiver=false`
- `FROZEN_WITH_WAIVER` requires:
  - `has_waiver=true`
  - valid waiver schema
  - explicit `FROZEN DUE TO ...` reason
- otherwise force `NOT_DONE`

## Forbidden Language

Blocked free-text claim words when gate is not fully satisfied
(structured fields like `final_status: NOT_DONE` are exempt):
- `PASS`
- `green`
- `ready`
- `complete`
- `done`

## Summary Template

```text
safety_verdict: <PASS|FAIL>
human_quality_verdict: <PASS|FAIL>

breach_declaration:
  has_breach: <true|false>
  breach_types: [<code>, ...]
  stop_ship_required: <true|false>
  reason: "<text>"

waiver_declaration:
  has_waiver: <true|false>
  waiver_type: <none|frozen_surface_exception|other_approved>
  blocker_id: <id|none>
  blocker_link: <path_or_url|none>
  scope: "<files_or_surfaces>"
  expires_at: <YYYY-MM-DD|none>
  approver: "<name_or_none>"
  reason: "<FROZEN DUE TO ...|none>"

final_status: <DONE|NOT_DONE|FROZEN_WITH_WAIVER>
```
