# MNO v0.2 Model-Consolidated Memory Execution Checklist

Status: **LOCKED — implementation and local release gates DONE; GitHub release PENDING**
Companion spec: `docs/MNO_V0_2_MODEL_CONSOLIDATION_SPEC_2026-07-17.md`

State vocabulary: unchecked = `PENDING`; checked = `DONE`. Any blocked item must be annotated `BLOCKED` with its blockerboard ID; active work is annotated `IN PROGRESS` with its owner.

## Traceability

| Checklist section | Spec sections | Blockers |
|---|---|---|
| 0–1 | 1–4, 15–18 | 001, 014, 035, 036 |
| 2 | 5–6, 11 | 002, 004, 009, 012, 015, 016, 026, 037, 039, 040, 044 |
| 3 | 6–8 | 001, 008, 010, 011, 017, 018, 026, 040, 042, 043 |
| 4 | 9.1–9.3, 12 | 005, 013, 028, 029, 037, 042, 044, 045 |
| 5 | 9.1–9.8 | 003, 012, 027, 030, 031, 035–039, 044 |
| 6 | 9.5–9.8 | 005, 020, 028, 031, 032, 036, 037 |
| 7 | 10–11 | 006, 007, 019, 025, 033, 034, 041, 047 |
| 8–9 | 13–14 | 020–022, 032 |
| 10–11 | 11–17 | 004, 013–15, 023–25, 034–39, 45–46 |
| 12–13 | 17 | 014, 023, 024, 033, 034, 038, 046 |

## 0. Definition of done

- [x] The locked spec is implemented without weakening canonical review.
- [x] Lux-style external integration can observe turns and complete explicit writeback.
- [x] Model-consolidated memory is autonomous, evidence-backed, labeled provisional, and subordinate.
- [x] Fresh install and v0.1 upgrade are proven.
- [x] Public docs, diagrams, packages, and version metadata report v0.2.0.
- [ ] PR review and CI are green.
- [ ] PR is merged, branch closed, tag and GitHub release published, clean-clone smoke green.

## 1. Spec gate

- [x] Run gap/edge-case review.
- [x] Run implementation touchpoint mapping.
- [x] Run guardrail/reward-hacking review.
- [x] Fold all findings into exactly this spec, checklist, and blockerboard.
- [x] Run fresh final QA and lock the three artifacts.
- [x] Record complexity score and rationale.
- [x] Update release checkpoint.

## 2. Storage and evidence identity (TDD)

- [x] Restore/add direct provisional-store unit coverage.
- [x] Add schema v2 fixture and migration tests before migration code.
- [x] Produce/checksum a migration fixture with the released v0.1.0 runtime, not only synthetic SQL.
- [x] Add evidence-fingerprint tests for source/message/span/role identity.
- [x] Include store namespace and normalized content digest in evidence identity.
- [x] Reject same identity with changed content atomically.
- [x] Require server-issued source/turn registration for independent-support authority.
- [x] Add signed automatic user registration in `context.build` and explicit HTTP/MCP source registration for tool/external spans.
- [x] Prove unregistered/cross-boundary handles return support delta `0` after restart.
- [x] Enforce the user/tool/assistant/system/developer source-role eligibility matrix.
- [x] Add stateless signed retrieval receipts and server-side echo resolution.
- [x] Test receipt tamper, omission, cross-principal/store/session reuse, expiry, and restart validation.
- [x] Test valid zero-retrieval receipt/native-equivalent handling for assistant self-claims.
- [x] Prove replay is idempotent.
- [x] Prove session changes alone cannot make replay independent.
- [x] Persist support disposition and counts.
- [x] Add authority, maturity, lifecycle, derived lineage, and policy metadata.
- [x] Store authority, maturity, lifecycle, conflict, and supersession as separate dimensions.
- [x] Preserve all v2 rows/events transactionally.
- [x] Prove repeated migration is safe.

## 3. Reinforcement, consolidation, and decay (TDD)

- [x] Add per-kind threshold/config validation tests.
- [x] Enforce locked numeric threshold/session/decay/currentness/TTL/retention/cap bounds and cross-field rules.
- [x] Add fact/preference/plan/event consolidation tests.
- [x] Add stricter self-claim tests.
- [x] Add retrieval-echo and derived-output anti-reinforcement tests.
- [x] Prove every assistant candidate is non-supporting without a valid receipt/native equivalent, and self-claims require a valid zero-retrieval receipt.
- [x] Add conflict-blocking and correction/supersession tests.
- [x] Add exact claim-key, detect-only near-duplicate, and conservative correction targeting tests.
- [x] Add immutable derived-revision/idempotent input-set tests.
- [x] Add injected-clock decay/dormancy/archive tests.
- [x] Add reactivation-on-new-evidence tests.
- [x] Implement bounded deterministic maintenance pass.
- [x] Preserve source observations and event history.
- [x] Propagate input conflict/supersession/demotion/bridge state to derived revisions.

## 4. Runtime integration (TDD)

- [x] Add runtime method to observe a completed external turn.
- [x] Match built-in turn capture semantics.
- [x] Preserve stable source/message/turn IDs.
- [x] Carry retrieved evidence IDs and derived lineage into anti-echo policy.
- [x] Carry a stateless signed retrieval receipt rather than trusting caller-supplied evidence IDs.
- [x] Add explicit bounded maintenance/session-boundary operation.
- [x] Keep context/retrieval/explanation read-only.
- [x] Share authority-aware retrieval between built-in chat and `context.build`.
- [x] Add trust, layer, maturity, lifecycle, conflict, and lineage fields to v2 evidence.
- [x] Make `context.why` resolve provisional evidence durably across restart.
- [x] Add consolidated provisional retrieval cards and labels.
- [x] Prove human-reviewed canonical dominance and visible conflicts.
- [x] Ensure session close performs bounded enabled maintenance only.

## 5. HTTP integration contract (TDD)

- [x] Add authenticated/idempotent `memory.observe` endpoint.
- [x] Add authenticated/idempotent `memory.source.register` endpoint with no memory mutation.
- [x] Add stable boundary object, payload caps, atomic identity-conflict, and partial candidate dispositions.
- [x] Add authenticated/bounded `memory.maintain` endpoint.
- [x] Implement locked request/response limits, cursors, dispositions, error codes, and transaction boundaries.
- [x] Advertise both in capabilities.
- [x] Add validation, authorization, replay, and failure tests.
- [x] Extend `writeback.resolve` with `apply`.
- [x] Add isolated `review_apply` permission and authenticated reviewer identity.
- [x] Make `review_apply` non-inherited; do not grandfather operator/admin or issue it to model bundles.
- [x] Reject caller-supplied server-owned authority/review/lifecycle/lineage fields.
- [x] Support apply-after-prior-approval exactly once.
- [x] Reject apply on rejection.
- [x] Accept deprecated `reviewer` alias if retained; emit `decided_by` only.
- [x] Prove an approved+applied memory is retrievable as an evidence atom with `human_reviewed=false`.
- [x] Prove apply creates no review decision, published card, activation state, or published pointer.
- [x] Persist pending/approved/rejected/applied queue state and audit events.
- [x] Put queue/apply/audit/atom mutation in one atom-DB transaction with deterministic apply identity.
- [x] Add crash-injection and concurrent retry tests.
- [x] Reject opposing resolve retries with `409`; keep same-decision retries idempotent.
- [x] Rebuild/invalidate retrieval snapshots on successful apply.
- [x] Complete provisional bridge lineage after durable-atom apply.
- [x] Write authoritative bridge suppression in the atom transaction; reconcile sidecar lineage idempotently.
- [x] Test crash/restart/concurrency before and after sidecar bridge reconciliation.
- [x] Expose inspect/dismiss/bridge operations for high-risk proposal-only records.
- [x] Default high-risk identity/relationship capture off.
- [x] Reject/redact secret-like material before every persistence/log/response surface.
- [x] Sanitize recursively before normalization/hashing/exceptions; forbid raw/encoded/unkeyed secret digests.
- [x] Add legacy-secret migration abort and explicit backed-up transactional scrub tests.

## 6. MCP and bundle parity (TDD)

- [x] Add `integration.memory.observe` tool.
- [x] Add `integration.memory.source.register` tool.
- [x] Add `integration.memory.maintain` tool.
- [x] Add `integration.memory.proposals.list`, `.dismiss`, and `.bridge` tools.
- [x] Add `apply` to `integration.writeback.resolve`.
- [x] Update tool descriptions and JSON schemas.
- [x] Update capabilities and generated endpoint bundles.
- [x] Add HTTP/MCP parity tests.
- [x] Add metadata-only operator proposal list and `review_apply` content/dismiss/bridge authorization tests.

## 7. Defaults, launcher, and setup (TDD)

- [x] Lock v0.2 fresh-default posture in config tests.
- [x] Preserve explicit upgrade configuration.
- [x] Add consolidation/decay configuration validation.
- [x] Distinguish fresh-standard defaults from upgrade-preserved omitted fields.
- [x] Add `--config` to stock runtime launcher.
- [x] Pass one validated config to retriever and runtime.
- [x] Emit safe effective-policy startup diagnostics.
- [x] Provision store UUID/signing key before network bind for fresh/upgrade paths; fail explicitly when unavailable.
- [x] Test protected key persistence, restart, backup/move/restore, offline rotation, and non-leakage.
- [x] Thread config through combined MCP launcher, desktop controller, setup plan, and generated launchers.
- [x] Verify headless, MCP, desktop-dev, and packaged desktop use the same posture.
- [x] Define WAL-safe backup/move/restore ownership for all runtime sidecars.
- [x] Use SQLite backup API or closed-store snapshots; reject raw live file-copy proof.

## 8. LLM guide and public docs

- [x] Add `docs/LLM_READ_THIS_FIRST.md` (final name may be tightened once).
- [x] Link it prominently from root README and integration docs.
- [x] Explain MNO vs model/personality/orchestrator.
- [x] Explain all authority and helper tiers.
- [x] Give exact retrieve/observe/remember/maintain workflows.
- [x] Give HTTP and MCP examples.
- [x] Explain echo prevention, stable IDs, conflict/abstention, and security.
- [x] Update README.
- [x] Update QUICKSTART.
- [x] Update public architecture.
- [x] Update API reference.
- [x] Update configuration reference.
- [x] Update pipeline guide.
- [x] Update agent integration guide.
- [x] Update MCP guide.
- [x] Update security/privacy guide.
- [x] Update integration bundle docs.
- [x] Correct or implement the documented WSS public payload.
- [x] Update public docs index/navigation.
- [x] Add release notes/changelog.
- [x] Add durable mutation queue and sidecar backup/recovery documentation.
- [x] Run link/terminology drift audit.

## 9. Visuals

- [x] Read the repository flowchart authoring guidance.
- [x] Update architecture source/spec.
- [x] Show canonical, consolidated provisional, observed provisional, STM, WSS, and proposal boundaries.
- [x] Show external retrieve -> answer -> observe loop.
- [x] Show explicit remember -> propose -> reviewer approve+apply -> evidence atom -> normal build/review/publish loop.
- [x] Regenerate SVG/PNG/drawio/public exports.
- [x] Run diagram audit scripts.
- [x] Visually inspect generated assets.

## 10. Version and package

- [x] Bump Python package to `0.2.0`.
- [x] Bump desktop package and lockfile.
- [x] Update runtime-bundle manifest compatibility.
- [x] Update README release badge/links.
- [x] Update version assertions/fixtures.
- [x] Build sdist and wheel.
- [x] Install wheel in clean repo-local environment.
- [x] Verify CLI/runtime/MCP reported versions.
- [x] Run fresh-store smoke.
- [x] Run v0.1-store upgrade smoke.
- [x] Checksum released-v0.1 store family, verify pre-migration backup, migrate twice, restart/compare, restore, and reopen with v0.1.
- [x] Run observe→consolidate→retrieve after restart from installed wheel and packaged/generated HTTP+MCP launch modes.
- [x] Run propose→reviewer approve/apply→restart→evidence retrieval from the same release surfaces.

## 11. Verification gates

- [x] Targeted store/config/runtime tests green.
- [x] Targeted HTTP/MCP integration tests green.
- [x] Truth-fence snapshots are byte-identical across every autonomous transition.
- [x] Provisional flood and 10,000-support tests preserve reviewed-truth dominance.
- [x] Secret non-persistence scan covers DB/WAL/log/audit/response artifacts.
- [x] Restart-recovery tests for context explanation and mutation lifecycle green.
- [x] Negative truth-fence suite proves no provisional path mutates review/publish/activate/WSS truth.
- [x] Full test suite green.
- [x] Static/type/lint checks green where configured.
- [x] `git diff --check` green.
- [x] No secrets, personal data, generated temp DBs, or unrelated files in diff.
- [x] Front-facing diff scope is intentional.
- [x] Clean worktree except intended release files.
- [x] Update post-green checkpoint.

## 12. GitHub PR/review/CI loop

- [ ] Commit coherent implementation/docs/release slices.
- [ ] Push `codex/mno-v0.2.0-model-consolidation`.
- [ ] Open PR with spec, migration, risk, and test evidence.
- [ ] Update PR-open checkpoint.
- [ ] Inspect all checks, reviews, inline comments, and bots.
- [ ] Classify every item as actionable, non-actionable, or already fixed.
- [ ] Fix all actionable feedback, including sound nits.
- [ ] Rerun proportional and full tests.
- [ ] Push fixes and wait for final CI/review state.
- [ ] Resolve addressed threads.
- [ ] Confirm mergeability and release metadata.

## 13. Merge and release

- [ ] Merge PR non-interactively after all gates pass.
- [ ] Confirm PR is merged and closed.
- [ ] Sync local main and verify merge commit.
- [ ] Update post-merge checkpoint.
- [ ] Create annotated `v0.2.0` tag.
- [ ] Push tag.
- [ ] Publish GitHub release with user/model migration notes.
- [ ] Verify GitHub latest release and assets.
- [ ] Clone released tag into a repo-local temporary directory.
- [ ] Build/install and run release smoke from tag.
- [ ] Confirm public docs and version report v0.2.0.
- [ ] Remove or ignore repo-local temporary artifacts safely.
- [ ] Mark goal complete only after release proof is collected.
