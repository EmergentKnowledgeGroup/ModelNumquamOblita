# Lean memory improvements

Status: packet, learning and summary code independently reviewed; full regression and publication proof are recorded in the release validation. Baseline: public v0.2.4 at `c64fbd2`.

The requested outcome is better memory packets, evidence-linked draft learning, useful summaries, and simpler integration, without a new model, runtime dependency, background service, or pipeline rewrite. Human review and Publish / Verify / Activate remain authoritative.

## Packet slice

The existing verifier checks retrieved memory statements, then the integration projection drops its verdict. An external agent can consequently confuse a retrieval match with a verified answer. The local response composer can also choose an incompatible alternative using token overlap.

Smallest fix: preserve the verdict and its scope through the existing context budget; accept optional explicit `answer_claims` on the existing context call; verify exact eligible memory statements only, and abstain on interpretations that this deterministic check cannot establish. Matching text is a source-support check, not a claim that the source is universally true. Keep existing callers and retrieval unchanged. Do not add a language parser or expand paraphrase rules.

Related text remains available with its source references, authority and conflict labels. A canonical memory excerpt must be identified as canonical wording. Original-message expansion uses the existing citation/why tools; joined or shortened context is never newly advertised as a verified original quotation. An unverified answer permits a fixed factual abstention and a clarification question, not an unchecked generated answer.

Related excerpts reuse the existing 320-character evidence limit and explicitly identify omitted context. Full stored memory is preserved and can be inspected through existing detail/expansion tools; adding an unbounded duplicate to every uncertain packet would undermine the lean integration requirement.

Acceptance: the negative Friday source cannot certify the affirmative Friday claim or Monday; an exact eligible source statement can pass; conflicts and existing abstentions cannot become PASS; old callers retain their behavior; HTTP/MCP and the budgeted host packet carry the same verdict/scope; the known local alternative-selection error falls back to source-faithful recall.

## Learning, summaries and usability

Use existing signed observations and draft/review surfaces. Existing capture/reinforcement is not renamed as a new semantic-learning capability. Additional host-authored lessons or revised summaries must remain explicit source-linked drafts, with authorship distinguished from independent evidence. The existing host performs any interpretation; MNO gains no inference runtime.

The new MCP shortcut `integration.learning.propose` resolves existing source IDs through `integration.context.why` and queues a lesson or summary through `integration.writeback.propose`. It does not resolve or apply the proposal. Authorship and source excerpts/citations persist in existing proposal metadata; replay creates no duplicate, missing sources create no draft, and the existing mutation-disable control remains effective. A source record gets one primary citation in the proposal, with its record ID retained for expansion. Native host capture remains separate; an MCP tool alone does not create automatic lifecycle hooks or an extra model call.

First improve the bounded evidence brief so the chosen summary retains the references of its actual supporting row. Reuse setup, status and human handoff flows. A new daemon, general reflection engine or duplicate learning database is outside this design.

`explore.anchor_brief` and runtime wake/resume briefs now return the selected extractive row's `summary_support` and puts that row's citation first. The legacy aggregate confidence field is retained; selected-row confidence is a separate support field. No generation, retriever replacement, or new index is introduced.

## Proof and publication

- Existing packet/runtime/integration baseline: 140 tests passed in an isolated Z-drive environment.
- Packet acceptance and nearby regression package: 224 passed; independent packet QA: 165 focused tests passed and no observed blocking defect. Exact-wording checks leave unverified paraphrases unresolved by design.
- Warm unchanged-caller packet microbenchmark: median 297.04 microseconds before and 297.12 after; normal packet grew about 110 UTF-8 bytes. This single small fixture is not a production latency claim. Runtime dependency list is unchanged.
- Write acceptance tests before each implementation and preserve nearby regression coverage.
- Audit dependencies, source scope, authority and changed files; measure changed-path overhead against the protected baseline.
- Inventory all maintained public docs, READMEs, diagrams/graphs, exports, packaging and release metadata. Record historical/unaffected surfaces explicitly instead of rewriting history.
- Prove exact wheel/sdist installation and upgrade; require relevant CI and independent protected-invariant review before publishing.

Existing dirty development work and OpenClaw PR #21 remain separately owned and preserved. Work is staged in `codex/lean-memory-context`; it does not publish the dirty checkout wholesale. Natural-language inference models are a later evaluation, after this goal lands.

The runtime wake/resume route had the same inherited selected-source omission as the MCP brief. Real HTTP fixtures failed on both routes before the fix, then passed with the selected citation and confidence exposed separately from the unchanged aggregate. The correction reuses each existing builder and changes no selection score or graph edge.
