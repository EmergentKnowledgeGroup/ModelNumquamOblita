# MNO v0.3.0 — lean memory release notes

**Publication status and artifacts:** See [GitHub Releases](https://github.com/EmergentKnowledgeGroup/ModelNumquamOblita/releases). These notes describe v0.3.0; their presence alone does not establish publication.
**Baseline:** Public v0.2.4. Native OpenClaw adapter work is separate and excluded.

## What changes

The context packet now keeps its verification verdict through the host's context budget. Optional v2 `answer_claims` checks explicit statements against eligible active canonical memory wording with citations. Matching is deterministic, with whitespace and terminal-period normalization; it does not infer paraphrases or certify universal truth. Unverified claims change an otherwise passing verdict to `ABSTAIN`. Conflicts and existing non-pass gates cannot become a pass.

`service_verdict` exposes the full result; compact `mno.agent_context.v2.verification` retains `decision`, `scope`, and `answer_status`. `retrieved_evidence` means pack support, while `answer_claims` means the explicitly requested statements were checked. Unverified packets retain inspectable canonical `related_text`, bounded to 320 characters and labeled with `truncated`. Original-message inspection remains on existing why/citation/raw-context surfaces. The local responder uses a fixed factual abstention and clarification question, rather than an unchecked generated assertion.

MCP `integration.learning.propose` resolves existing source IDs and reuses the existing writeback queue for a host-authored `lesson` or revised `summary`. It requires operator/admin authority, mutations enabled, and the existing runtime proposal path. Supply `text`, `evidence_ids`, `idempotency_key`, `session_id`, and `run_id`; optional `kind` defaults to `lesson`. The draft remains pending human review, with authorship and source excerpts/citations persisted in existing proposal metadata. Missing source support creates no draft, and idempotent replay returns the existing proposal. There is no new HTTP endpoint.

MCP/runtime anchor briefs and wake-up-pack briefs bind `summary_support` to the actual selected extractive row and put its source reference first. The legacy aggregate `confidence` is preserved; selected-row support confidence is a separate field. The local response composer also avoids certifying an incompatible alternative through token overlap and falls back to source-faithful recall.

## Lean and compatible

- No new model, inference service, runtime dependency, background worker, database, or schema migration.
- MNO initiates no additional model call. An existing host may author a useful draft during its normal work; routine turns need no new learning task.
- Existing context callers can omit `answer_claims`; retrieval/ranking and the integration envelope remain in place.
- Human Review → Publish → Verify → Activate, review decisions, canonical authority, and MCP installation/activation flows remain unchanged.
- Existing Hermes automatic provisional capture stays separate and retains its dedicated four-operation credential. It cannot submit learning drafts.
- MCP availability alone is not an automatic host hook. Native OpenClaw adapter work is not included.

## Validation and release boundary

The targeted packet, learning, summary, and nearby regression checks passed, and the full Python suite at the initial feature commit passed. The runtime-brief source alignment also passed focused checks. Final artifact/install/upgrade proof, review/CI, and publication evidence belong to the matching GitHub release; these notes do not claim an unverified artifact or test count. No historical retrieval benchmark was rerun, and no new answer-quality or production-latency claim is made.

Use the existing setup/runtime commands. The support matrix inherits the v0.2.4 baseline and does not expand OS or desktop-installer claims. No data migration is introduced; the previous v0.2.4 package remains the release rollback baseline, with existing private runtime data handling unchanged.

See [packet API](API.md#answer-claims-and-verification), [MCP draft workflow](MCP_INTEGRATION.md#source-linked-learning-drafts), [agent integration](AGENT_INTEGRATION.md), [compatibility](COMPATIBILITY_AND_SUPPORT.md), [distribution](../DISTRIBUTION.md), and [security/privacy](SECURITY_AND_PRIVACY.md#lean-packets-and-learning-drafts).
