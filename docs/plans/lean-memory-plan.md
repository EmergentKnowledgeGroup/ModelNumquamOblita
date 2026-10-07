# Lean memory improvements

Status: implementation in progress. Baseline: public v0.2.4 at `c64fbd2`.

The requested outcome is better memory packets, evidence-linked draft learning, useful summaries, and simpler integration, without a new model, runtime dependency, background service, or pipeline rewrite. Human review and Publish / Verify / Activate remain authoritative.

## Packet slice

The existing verifier checks retrieved memory statements, then the integration projection drops its verdict. An external agent can consequently confuse a retrieval match with a verified answer. The local response composer can also choose an incompatible alternative using token overlap.

Smallest fix: preserve the verdict and its scope through the existing context budget; accept optional explicit `answer_claims` on the existing context call; verify exact eligible memory statements only, and abstain on interpretations that this deterministic check cannot establish. Matching text is a source-support check, not a claim that the source is universally true. Keep existing callers and retrieval unchanged. Do not add a language parser or expand paraphrase rules.

Related text remains available with its source references, authority and conflict labels. A canonical memory excerpt must be identified as canonical wording. Original-message expansion uses the existing citation/why tools; joined or shortened context is never newly advertised as a verified original quotation. An unverified answer permits a fixed factual abstention and a clarification question, not an unchecked generated answer.

Acceptance: the negative Friday source cannot certify the affirmative Friday claim or Monday; an exact eligible source statement can pass; conflicts and existing abstentions cannot become PASS; old callers retain their behavior; HTTP/MCP and the budgeted host packet carry the same verdict/scope; the known local alternative-selection error falls back to source-faithful recall.

## Learning, summaries and usability

Use existing signed observations and draft/review surfaces. Existing capture/reinforcement is not renamed as a new semantic-learning capability. Additional host-authored lessons or revised summaries must remain explicit source-linked drafts, with authorship distinguished from independent evidence. The existing host performs any interpretation; MNO gains no inference runtime.

First improve the bounded evidence brief so the chosen summary retains the references of its actual supporting row. Reuse setup, status and human handoff flows. A new daemon, general reflection engine or duplicate learning database is outside this design.

## Proof and publication

- Existing packet/runtime/integration baseline: 140 tests passed in an isolated Z-drive environment.
- Write acceptance tests before each implementation and preserve nearby regression coverage.
- Audit dependencies, source scope, authority and changed files; measure changed-path overhead against the protected baseline.
- Inventory all maintained public docs, READMEs, diagrams/graphs, exports, packaging and release metadata. Record historical/unaffected surfaces explicitly instead of rewriting history.
- Prove exact wheel/sdist installation and upgrade; require relevant CI and independent protected-invariant review before publishing.

Existing dirty development work and OpenClaw PR #21 remain separately owned and preserved. Work is staged in `codex/lean-memory-context`; it does not publish the dirty checkout wholesale. Natural-language inference models are a later evaluation, after this goal lands.
