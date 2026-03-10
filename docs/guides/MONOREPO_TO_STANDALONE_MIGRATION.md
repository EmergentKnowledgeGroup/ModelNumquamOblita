# Monorepo To Standalone MNO Migration

Status: Active  
Owner: MNO runtime / operator lane  
Last Updated: 2026-03-10

## Purpose

This guide explains how an existing MNO operator moves from the old mixed monorepo workflow to the standalone `ModelNumquamOblita` repo without losing local data or forcing a fresh import just because the repo split happened.

## What Stays The Same

- your sqlite memory store stays valid
- your reviewed episode cards stay valid
- your import artifacts stay valid
- your runtime eval/signoff outputs stay valid as historical artifacts

The repo split is a code/runtime packaging change, not a forced data reset.

## Data Path Continuity

Standalone MNO can run against existing artifacts wherever they already live.

Supported operator choices:

1. Keep your current stores and episode files in place, then point standalone MNO at them explicitly.
2. Copy your MNO artifacts into the standalone repo runtime folders if you want a cleaner local layout.
3. Keep the legacy monorepo on disk as historical reference only. Do not delete it as part of cutover.

No re-import is required solely because the repo moved.

## Recommended Cutover Flow

1. Keep the legacy monorepo untouched.
2. Use the standalone repo for all new MNO runtime, packaging, MCP, and GUI work.
3. Point the standalone runtime or connector at the existing sqlite store and reviewed episode cards.
4. Run standalone preflight, boundary audit, and normal runtime tests before treating the standalone lane as primary for daily MNO work.

## Example Operator Paths

Typical carry-forward artifacts:

- sqlite store: `.../atoms.sqlite3`
- reviewed episodes: `.../episode_cards.reviewed.json`
- runtime health/eval artifacts: `runtime/evals/*`

Typical standalone commands:

- `python3 tools/preflight.py --mode runtime --memories <existing_atoms.sqlite3>`
- `python3 tools/run_live_runtime.py --memories <existing_atoms.sqlite3> --episodes <existing_episode_cards.reviewed.json>`
- `python3 tools/run_phase7_signoff.py --memories <existing_atoms.sqlite3>`

## Repo Authority And Fallback

Current authority rules:

- `ModelNumquamOblita` is the authoritative repo for standalone MNO work once its standalone gates are green.
- the legacy `NumquamOblita` repo remains the authoritative ANO workspace until ANO is extracted into its own standalone lane.
- if standalone MNO cutover fails mid-flight, keep the old repo and data paths intact and roll back the launcher/config change instead of re-importing data.

## What Not To Do

- do not delete old local stores or episode files during cutover
- do not assume the standalone repo requires a new import just because paths changed
- do not use the legacy mixed repo as the source of truth for new MNO-only runtime/tooling once the standalone repo gates are green
- do not copy ANO-only tools back into the standalone MNO repo

## Cutover Done Criteria

The standalone cutover is operationally complete for MNO when:

- standalone boundary audit passes
- standalone test suite passes
- runtime launches against the existing store
- operator docs point to the standalone repo for new MNO work
- no local data had to be re-imported solely because of the repo split
