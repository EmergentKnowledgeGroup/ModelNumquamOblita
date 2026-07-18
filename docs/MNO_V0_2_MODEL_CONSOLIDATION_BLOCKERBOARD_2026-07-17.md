# MNO v0.2 Model-Consolidated Memory Blockerboard

Status: **LOCKED — all implementation/local release blockers Closed; MNO-020-014 remains Open for GitHub review/merge/tag proof**
Rule: any open release blocker prevents merge or release.

| ID | Class | Sev | Owner | Area / failure | Detection and unblock proof | Fallback / backout | State |
|---|---|---:|---|---|---|---|---|
| MNO-020-001 | Release blocker | Critical | Memory core | Consolidation reaches/outranks reviewed canonical truth | Truth-fence and 10k-support tests | Disable consolidation; revert slice | Closed |
| MNO-020-002 | Release blocker | Critical | Memory core | Replay/echo/derived text reinforces itself | Anti-echo plus invalid-receipt-all-assistant-blocked and valid-zero-retrieval self-claim tests | Disable capture/reinforcement | Closed |
| MNO-020-003 | Release blocker | Critical | Integration security | Approve does not apply evidence atom | Propose→approve/apply→evidence retrieval | Disable public apply; retain proposal-only | Closed |
| MNO-020-004 | Release blocker | Critical | Memory core | v2 migration loses data, falsely matures, or preserves secrets | Released-v0.1 fixture, backup, scrub/abort, repeat/restore proof | Restore verified v2 backup | Closed |
| MNO-020-005 | Release blocker | High | Runtime integration | Lux-style runtime cannot report completed turns | Auth/idempotent HTTP+MCP observe tests | Disable external observe docs/capability | Closed |
| MNO-020-006 | Release blocker | High | Runtime integration | Stock launcher cannot load policy | Launcher config and startup smoke | Require explicit legacy disabled profile | Closed |
| MNO-020-007 | Release blocker | High | Runtime integration | Shipped feature is inert/ambiguous | Fresh/upgrade policy tests and diagnostics | Preserve v0.1 disabled posture | Closed |
| MNO-020-008 | Release blocker | High | Memory core | Conflicts merge into false certainty | Default block and visible-conflict tests | Disable consolidation for conflicted claims | Closed |
| MNO-020-009 | Release blocker | High | Memory core | Consolidation overwrites source/lineage | Immutable input/revision/event tests | Disable revision creation | Closed |
| MNO-020-010 | Release blocker | High | Integration security | High-risk inference becomes answer truth | Risk-routing and default-off tests | Disable high-risk lane | Closed |
| MNO-020-011 | Release blocker | High | Memory core | Decay deletes evidence/non-provisional truth | Injected-clock demotion-only tests | Disable decay | Closed |
| MNO-020-012 | Release blocker | High | Memory core | Retries duplicate observe/consolidate/apply | Cross-layer exact-once tests | Disable affected write operation | Closed |
| MNO-020-013 | Release blocker | High | Runtime integration | Reads/receipts perform hidden writes | Stateless receipt and before/after store snapshots | Disable receipt-backed reinforcement | Closed |
| MNO-020-014 | Release blocker | High | Release owner | Merge/tag bypasses green reviewed commit | GitHub CI/review/merge/tag evidence | Do not merge/tag | Open |
| MNO-020-015 | Implementation risk | Medium | Memory core | Authority/maturity/lifecycle/conflict conflated | Schema/API/docs field assertions | Revert v3 schema slice | Closed |
| MNO-020-016 | Implementation risk | Medium | Memory core | Session ID alone creates support | Cross-session replay test | Ignore session-only support | Closed |
| MNO-020-017 | Implementation risk | Medium | Memory core | Self-claim thresholds/echo unsafe | Self-claim threshold/no-bridge tests | Disable self-claim capture | Closed |
| MNO-020-018 | Implementation risk | Medium | Memory core | Stale plans appear current | Server-time currentness tests | Historical-only plan retrieval | Closed |
| MNO-020-019 | Implementation risk | Medium | Runtime integration | Invalid caps/windows are unsafe | Bound/cross-field config tests | Reject invalid config/startup | Closed |
| MNO-020-020 | Implementation risk | Medium | Runtime integration | HTTP/MCP/bundles/docs drift | Contract parity and bundle smoke | Hide mismatched capability | Closed |
| MNO-020-021 | Implementation risk | Medium | Docs/release | Docs imply second model/canonical consolidation | Terminology/link/LLM-guide audit | Revert docs to last accurate state | Closed |
| MNO-020-022 | Implementation risk | Medium | Docs/release | Visuals collapse trust paths | Source/export audit and inspection | Retain prior canonical visuals | Closed |
| MNO-020-023 | Implementation risk | Medium | Release owner | Version surfaces disagree | Version sweep and installed-wheel smoke | Block packaging/tag | Closed |
| MNO-020-024 | Implementation risk | Medium | Release owner | Temp/personal/secret/unrelated files ship | Diff, secret, status audit | Remove intended artifacts only; block release | Closed |
| MNO-020-025 | Implementation risk | Medium | Runtime integration | v0.1 callers break | Backward-envelope/default tests | Feature-gate additive operations | Closed |
| MNO-020-026 | Implementation risk | Medium | Memory core | Derivation loses support/rewrites history | Derivation-integrity revision tests | Disable derived retrieval | Closed |
| MNO-020-027 | Release blocker | Critical | Memory core | Review proposals vanish on restart | Atom-DB queue lifecycle restart tests | Disable apply; preserve queue DB | Closed |
| MNO-020-028 | Release blocker | High | Runtime integration | Context omits/erases provisional trust state | HTTP/MCP/prompt/restart parity tests | Disable provisional context retrieval | Closed |
| MNO-020-029 | Release blocker | High | Runtime integration | Context explanation fails after restart | Durable provisional explanation test | Return explicit unavailable, not guessed | Closed |
| MNO-020-030 | Release blocker | High | Memory core | Bridge crash leaves duplicate live provisional | Atom suppression plus reconcile/crash tests | Suppress from authoritative atom marker | Closed |
| MNO-020-031 | Release blocker | High | Integration security | High-risk proposals cannot be reviewed/dismissed | Sanitized inspect/dismiss/bridge tests | Disable high-risk capture | Closed |
| MNO-020-032 | Implementation risk | Medium | Docs/runtime | WSS payload promised but discarded | HTTP/MCP parity test or explicit retraction | Mark native-only | Closed |
| MNO-020-033 | Implementation risk | Medium | Desktop/runtime | Launch modes use different policy | Cross-launch health/package smoke | Force explicit disabled legacy profile | Closed |
| MNO-020-034 | Implementation risk | Medium | Release owner | Backup/move orphans store family | SQLite backup/restore smoke | Closed-store backup; abort move | Closed |
| MNO-020-035 | Release blocker | Critical | Integration security | Apply/bridge grants published authority | Byte-identical review/publish/activate truth fences | Disable bridge/apply | Closed |
| MNO-020-036 | Release blocker | Critical | Integration security | Role inheritance/forged fields bypass review | Non-inherited capability and forged-field tests | Disable resolve/apply routes | Closed |
| MNO-020-037 | Release blocker | Critical | Runtime integration | Minted IDs/collisions/forged receipts create support | Signed registration/collision/boundary tests plus invalid-receipt-all-assistant-zero-support | Treat unregistered/assistant evidence as non-supporting | Closed |
| MNO-020-038 | Release blocker | Critical | Memory core | Crash/concurrency makes apply ambiguous/duplicate | One atom transaction plus crash/concurrency proof | Disable apply; restore DB backup if needed | Closed |
| MNO-020-039 | Release blocker | Critical | Integration security | Raw/encoded/guessable secret material persists | Pre-hash sanitizer and all-artifact scans | Abort capture/migration; restore backup | Closed |
| MNO-020-040 | Release blocker | High | Memory core | Semantic overmerge/derived overwrite | Exact claim-key and immutable revision tests | Detect/log only; disable consolidation | Closed |
| MNO-020-041 | Release blocker | High | Runtime integration | Fresh/upgrade defaults collapse | Separate policy-source fixture tests | Upgrade-preserved disabled profile | Closed |
| MNO-020-042 | Release blocker | High | Memory core | Boundary retry runs maintenance twice | Durable event and restart idempotency tests | Disable automatic boundary maintenance | Closed |
| MNO-020-043 | Implementation risk | Medium | Memory core | Caller time manipulates decay/currentness | Server-clock/plan-currentness tests | Disable decay; historical-only plan label | Closed |
| MNO-020-044 | Release blocker | High | Runtime integration | Caller IDs/roles manufacture evidence | Automatic/explicit registration, role matrix, unregistered support-delta-zero tests | Non-supporting provenance only | Closed |
| MNO-020-045 | Release blocker | High | Retrieval | Global cutoff hides reviewed matches | Overfetch/ceil/top-k=1/pinned-winner flood tests | Disable provisional merge | Closed |
| MNO-020-046 | Release blocker | High | Release owner | Synthetic smoke hides real upgrade/package failure | Released-v0.1 fixture and installed/package full-loop restart proof | Block release | Closed |
| MNO-020-047 | Release blocker | High | Integration security | Missing/corrupt/leaked signing key breaks read-only restart validation | Fresh/upgrade provisioning, startup fail, ACL, backup/restore, rotate/non-leak tests | Refuse network bind; restore protected backup | Closed |

## Local closure evidence

- Full Python regression suite passed with `TMP`, `TEMP`, and pytest base temp on the external Z-drive test root.
- Desktop shell passed 58/58 tests; v0.2.0 Python/desktop/lock/manifest metadata aligned.
- HTTP/MCP contract suites cover signed observe/register/maintain, proposal inspect/dismiss/bridge, and explicit reviewer apply.
- Truth-fence, 10,000-support, replay, collision, restart, crash/concurrency, conflict, key lifecycle, backup, and secret-artifact tests passed.
- A store produced by the released v0.1.0 code migrated/reopened repeatably, restored from its verified backup under v0.1.0, and was conservatively unmatured.
- Independent QA re-reviewed the legacy-secret and assistant-receipt boundaries after the final fixes and returned PASS.
- Final wheel/sdist built with Z-drive temporary storage. The wheel installed into an isolated environment and passed observe→consolidate→restart retrieval plus propose→human approve/apply→restart evidence proof.
- Architecture/public/Draw.io exports regenerated; strict diagram audit, local link/terminology audit, `git diff --check`, and front-facing diff-scope audit passed.

MNO-020-014 intentionally stays open until the reviewed commit is green in GitHub CI, merged, and tagged. Its closure evidence is recorded after those external events.

## Required stop conditions

Stop implementation or release when any of these occurs:

- the design requires autonomous canonical promotion;
- an implementation shortcut makes generated text its own source;
- migration cannot preserve v2 data transactionally;
- public writeback cannot be made exact-once;
- a security-sensitive write operation lacks explicit permission and audit evidence;
- the full test suite, clean install, upgrade smoke, CI, or required review is red;
- the release tag would not point at the reviewed merge commit.

## Closure protocol

For each blocker:

1. assign an owner and classification: Critical/High = release blocker; Medium = implementation risk that must still close; external dependencies/deferred items must be stated explicitly;
2. record detection evidence, affected files, and the unblock condition;
3. link the implementing commit or file;
4. record the exact validating command/test and observed result;
5. record fallback/backout where the change touches schema, authority, permissions, or release automation;
6. change state to `Closed` only after proof exists;
7. reopen on regression or contradictory evidence.

No external dependency or deferred non-blocker is currently accepted for v0.2.0.
