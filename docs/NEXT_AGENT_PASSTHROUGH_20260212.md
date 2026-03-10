# Next-Agent Passthrough (Post PR-A/PR-B, Pre PR-C)

## Update (2026-02-13): PR C Acceptance Surface Lock
- NumquamOblita is a **memory service**, not the user-facing assistant.
- Acceptance/signoff surface is now:
  - `context-package v2` (`POST /api/chat/context-package`) + evidence + service verdict
  - plus an **external responder model** reply (LM Studio / OpenAI) using that package as context.
- Locked spec: `docs/CONTEXT_PACKAGE_V2_EXTERNAL_RESPONDER_EVAL_SPEC.md`.
- Eval tooling:
  - Standalone responder eval: `python3 tools/run_responder_eval.py ...`
  - Oneclick: `python3 tools/run_oneclick_eval.py --eval-surface responder ...`
- Latest execution checkpoint: `runtime/checkpoints/LATEST.md` + `runtime/checkpoints/LATEST.json`.

## Where We Are
- PR A merged: `#100` (episode promotion + alignment pass)
- PR B merged: `#101` (citation ranking + direct-citation gate + oneclick acceptance gate)
- Branch/state now: `main` synced to `origin/main`

## Ground Truth Files
- Goal contract: `docs/NEAR_PERFECT_GOAL.md`
- A/B tasklist: `docs/NEAR_PERFECT_PR_A_B_TASKLIST.md`
- New gap spec: `docs/NEAR_PERFECT_EVENT_PROMPT_GAP_FIX_SPEC.md`
- PR C failure report: `docs/PR_C_HUMAN_QUALITY_FAILURE_REPORT_20260212.md`
- Memory formation gameplan: `docs/MEMORY_FORMATION_GAMEPLAN.md` (evidence vs episode memory; why snippet-seeded prompts look random)
- System overview: `docs/SYSTEM_MASTER_OVERVIEW.md`
- Workflow rules: `AGENTS.md` + local `AGENTS.md` in repo root

## What Is Green
- Safety and correctness gates are strong in latest oneclick check:
  - `decision_accuracy=1.0`
  - `false_memory_rate=0.0`
  - `abstain_precision=1.0`
  - `citation_hit_rate=0.7778`
- Reference run:
  - `runtime/evals/prb_check_20260212_070600/eval/summary.json`
  - `runtime/evals/prb_check_20260212_070600/acceptance_gate.json`

## What Is Not Done
- Near-perfect question quality is still not complete.
- Generated truthset prompts can still be fragment-style in places.
- Core remaining work:
  - event-grade prompt generation hardening,
  - eval integrity hardening (strict expected-anchor alignment),
  - response composition hardening (no parrot/echo formats),
  - dual-verdict signoff (`safety_verdict` + `human_quality_verdict`).
  - implement all regression rules described in `docs/PR_C_HUMAN_QUALITY_FAILURE_REPORT_20260212.md` (treat as blocking contract, not advisory).

## Critical Clarification
- Previous PASS output reflected safety-gate success, not full near-perfect quality success.
- Going forward, PASS language is blocked unless both verdicts pass.

## Next Execution Block
1. Implement PR C scope in `docs/NEAR_PERFECT_PR_A_B_TASKLIST.md`.
2. Add regression tests for:
   - malformed prompt rejection,
   - strict supported anchor alignment,
   - anti-parrot response composition.
3. Run full test suite.
4. Run oneclick on:
   - refined corpus
   - noisy corpus
5. Produce human-readable question + answer audit artifact.
6. Report dual verdicts and block completion if either fails.

## Commands to Resume
```bash
cd /mnt/z/openAIdata/NumquamOblita
python3 tools/context_checkpoint.py --repo-root . resume --live
python3 -m pytest -q
python3 tools/run_oneclick_eval.py --eval-surface responder --skip-import --store .runtime/imports/atoms.sqlite3 --run-dir runtime/evals/<stamp> --requested-cases 12 --scan-budget 600000 --responder-provider mock --responder-model mock
```

## Compaction Safety Protocol
- Always checkpoint at phase start/post-tests/PR-open/post-merge.
- Keep `runtime/checkpoints/LATEST.md` and `LATEST.json` authoritative.
- On resume, verify branch + head first, then run the recorded `next_cmd`.

## Risk Notes
- Do not overfit generator to one corpus/personality.
- Preserve strict abstain/citation behavior while improving readability.
- Keep latency within current conversational budget.
- Never treat acceptance gate safety pass as full product-quality pass.
