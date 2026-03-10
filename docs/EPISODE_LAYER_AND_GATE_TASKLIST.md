# Episode Layer + Gate Tightening Tasklist

## Goal
Move from "statement cards" to event-style memory while reducing accidental memory pull during normal chat.

## Completed Now
- Added one-click eval + human readout (`run_oneclick_eval*`, `build_human_eval_readout.py`).
- Tightened routine-chat gating to reduce over-recall in casual prompts.
- Added repo guardrail: `runtime/` is now git-ignored.
- Added Episode Builder v1 (`tools/build_episode_cards.py`) to generate event-style cards from atoms.
- Added Episode Retrieval v1 (episode-first lookup in runtime; atom fallback when confidence is weak).

## Next Build Blocks
1. **Over-Recall Guardrail v2** ✅
   - Added routine hard-cap route (`routine_hard_cap`) for casual/small-talk prompts.
   - Added regression prompt bank fixture (`tests/fixtures/routine_social_prompt_bank.json`) and test coverage.

2. **Human QA Pack** ✅
   - Added `tools/build_episode_review_pack.py` to generate review artifacts (`episode_cards.review.tsv` + `episode_cards.review.md` + meta).
   - Added compile path to produce `episode_cards.reviewed.json` from approve/reject/edit decisions.

3. **Signoff Gate Update** ✅
   - Add episode-specific metrics:
     - episode_hit_rate
     - episode_false_recall_rate
     - routine_over_recall_rate
   - Keep release gate fail-closed on false memory regressions.

## Checkpoint
- Checkpoint label: `episode-layer-gate-tasklist`
- Resume command:
  - `python3 tools/context_checkpoint.py --repo-root . resume --live`
