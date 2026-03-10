# MNO P0 Run Summary Contract (Dual-Verdict Required)

Status: Active (P0 process gate)
Updated: 2026-03-04
Scope: `docs/MNO_LEAN_RETRIEVAL_BLOCKERBOARD.md` (`MLRB-009`)

## Purpose

Define the minimum reporting contract for any MNO P0 completion claim.

If this contract is not fully met, status is **not done** even when other gates pass.

## Required Fields (No Exceptions)

Every MNO P0 run summary must include:
- `run_id`
- dataset/corpus id
- case count
- baseline reference
- `safety_verdict`
- `human_quality_verdict`
- quality defect count from `human_readout.md`
- top failure examples (question + answer)
- full per-case Q/A audit table with defect tags

## Blocking Rules

Any of the following is automatic `not done`:
- missing `human_quality_verdict`
- missing per-case Q/A defect table
- PASS/green language when only one verdict passes
- omission of top failure examples when defects are present
- unsupported non-routine case without direct anchor alignment

## P0 Summary Template

Use this template before any success claim:

```text
run_id: <id>
dataset_id: <id>
case_count: <n>
baseline_ref: <run_id or artifact>

safety_verdict: <PASS|FAIL>
human_quality_verdict: <PASS|FAIL>

quality_defect_count: <n>
top_failures:
  - q: "<question>"
    a: "<answer>"
    tags: [<defect_tag>, ...]

per_case_qa_audit:
  - case_id: <id>
    question: "<question>"
    answer: "<answer>"
    defect_tags: [<tag>, ...]
    anchor_alignment: <direct|missing>
```

## Release Language Rule

Allowed:
- "P0 done" only when both verdicts are `PASS` and required fields are present.

Blocked:
- "PASS", "green", "ready", or "done" if any required field is missing.
