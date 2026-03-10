# Runtime UI Tour (Operator Guide)

This guide explains the runtime web UI: what each pane does and the core operator workflows.

## Opening the UI

- Run: `python3 tools/run_runtime_demo.py --host 127.0.0.1 --port 7340`
- Open: `http://127.0.0.1:7340/`

## The layout (high level)

The UI is an operations console with these functional areas:

- **Chat shell**: create/select sessions, send turns, see per-turn route badges and reasons.
- **Context preview**: build and inspect `context_package` without sending a turn.
- **Why panel**: explain a specific turn (service verdict, evidence, time window, citations).
- **Telemetry ledger**: session/runtime telemetry summaries and recent turn-level latency/cost rows.
- **Memory workbench**:
  - **Episodes**: browse/edit/disable episode cards (the default recall unit).
  - **Cards/Atoms**: lower-level evidence views with provenance and graphs.
- **Wizard**: end-to-end pipeline for non-technical operation.
  - Includes rollback control via **Restore last published** when a publish step needs reversal.
- **Ops**: health checks, packaging instructions, writeback policy, proposal queue.

## Core workflows

### 1) “Why did you say that?”
1. Send a message in the chat shell.
2. Open the **Why** panel for that turn.
3. Verify:
   - the **service verdict** decision matches the behavior (PASS/ABSTAIN/CLARIFY/NO_MEMORY)
   - **citations** are present internally and valid
   - the evidence window is plausible

### 2) Disable an episode that is causing bad recall
1. Go to **Episodes**.
2. Find the episode, open detail, click **Disable**.
3. Re-run a similar chat query and confirm retrieval no longer uses it.

### 3) Correct an episode summary/title
1. Go to **Episodes** → select an episode.
2. Use **Edit** to update title/summary.
3. Use “Why this answer?” to confirm the edited summary appears in evidence payloads.

### 4) Safely handle writeback (when enabled)
Writeback is OFF by default. When enabled, the system should create **proposals** rather than applying mutations immediately.

### 5) Verify runtime health and telemetry
1. Open the telemetry/ledger panel.
2. Check aggregate counters and recent turn latency/cost rows.
3. If behavior drifts, cross-check with health export in the Ops panel before changing policy.

### 6) Roll back published wizard pointers
1. In the Wizard section, use **Restore last published**.
2. Confirm the response restores `published_pointers`.
3. Re-run Verify and only then continue with Go Live.

## Reference

- API matrix: `docs/api/API_MATRIX.md`
- Pipeline spec: `docs/PIPELINE_REFINEMENT_EXECUTION_PLAN.md`
