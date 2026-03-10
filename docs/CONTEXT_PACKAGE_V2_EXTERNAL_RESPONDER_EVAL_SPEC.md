# Context Package v2 + External Responder Eval Spec

This spec locks the "memory service" contract for NumquamOblita:

- NumquamOblita produces a `context_package` (memory evidence + guidance).
- An external LLM produces the user-facing reply.
- Evals must test that full pipeline (package -> model -> verifier), not the internal standalone runtime reply.

North star contract: `docs/NEAR_PERFECT_GOAL.md`.

## Non-Negotiable Contracts

1. NumquamOblita is not the user-facing assistant.
- `/api/chat/context-package` is the primary product surface.
- Any "standalone answer" endpoints are debug-only and must not be the acceptance target.

2. "Zero hallucinations" means "no unsupported memory claims."
- Memory-backed claims must be tied to evidence IDs delivered in the context package.
- If the evidence is insufficient, the system must abstain or ask for clarification.

3. Dual verdict remains required, but the judged output changes.
- `safety_verdict`: verifier-backed (no false memory).
- `human_quality_verdict`: question quality + evidence quality + final model reply quality.
- Never claim PASS unless both PASS.

4. Local-first testing.
- Regression runs must be able to use a local model (LM Studio) before using paid endpoints.
- Final signoff runs should also validate the target FT model endpoint.

5. Latency budgets are measured end-to-end.
- `memory_ms` (context-package build time)
- `model_ms` (LLM call time)
- `total_ms`

## Context Package v2 (API Surface)

Endpoint: `POST /api/chat/context-package`

Request (additions to v1):
- `package_version`: `"v1"` (default) or `"v2"`
- `retrieval_query`: optional override for retrieval text (debug/eval)
- `render_citations`: optional bool (default false for natural chat; set true for strict eval/audit)

Response:
- `package_version: "v2"`
- Must include all v1 fields plus v2 fields below.

### v2 Required Fields

1. `timing_ms`
- `build_ms`
- `stm_ms`
- `ltm_ms`
- `verifier_ms`

2. `ltm_evidence`
Ranked evidence items intended for model consumption.

Each entry must include:
- `evidence_id`: stable ID (default: atom id, e.g. `mem_...` or `episode_card:...`)
- `section`: `core|context|continuity|conflict|episode`
- `kind`: `event_card|fact_card|relationship_card` (best-effort)
- `role_hint`: `user|assistant|unknown` (author role of the source turn when known)
- `summary`: compact non-verbatim memory note (service-generated, not model-generated)
- `verbatim`: optional short snippet (bounded, used for auditing/verification)
- `citations`: list of `source_id#message_id` strings
- `anchors`: best-effort anchor tokens (entities/topics)
- `confidence`: float [0..1]
- `contradiction`: bool

3. `retrieval_stats`
- `retrieved_atom_ids`: IDs actually present in the returned evidence pack
- `retrieval_passes`
- `retrieval_stop_reason`
- `p95_retrieved_atoms` is an eval metric, but the package must expose raw counts needed for it

4. `service_verdict`
Deterministic retrieval/verifier verdict intended to constrain the responder model.

Minimum fields:
- `decision`: `PASS|ABSTAIN|CLARIFY|NO_MEMORY`
- `citations`: ranked citations (same format as above)
- `unsupported_claims`: list of reason codes (optional, but useful in debug)

5. `responder_guidance`
Must be explicit and model-agnostic:
- `abstain_without_evidence: true`
- `require_citations: true` (always true for safety)
- `render_citations: true|false` (controls user-visible formatting, not safety requirement)
  - `true` => strict citation-visible mode (PASS replies must include at least one exact citation token)
  - `false` => natural chat mode (PASS replies may omit visible tokens, but internal provenance must be present)
- `citation_format`: `source_id#message_id`
- `do_not_quote_verbatim_unless_asked: true`
- `ask_followup_when_evidence_weak: true`

## External Responder Harness (Provider-Agnostic)

We add a small responder layer that:

1. Calls `context-package v2`.
2. Builds the responder prompt/messages.
3. Calls a configured model endpoint.
4. Verifies the model output against the evidence delivered in the package.
5. Optionally strips citations from display while keeping them internally required.

### Provider Interfaces (initial set)

1. OpenAI Chat Completions compatible (FT endpoint).
- URL: `https://api.openai.com/v1/chat/completions`
- Auth: `OPENAI_API_KEY`

2. LM Studio local endpoint (user-provided).
- Base: `http://127.0.0.1:1234`
- `GET /api/v1/models`
- `POST /api/v1/chat`
- Model: `qwen/qwen3-32b`

Provider expansion (Anthropic/xAI/Ollama/etc) is explicitly out-of-scope for the first v2+eval cut, but the interface must not block it.

### Prompt Construction (required properties)

System instructions must:
- Treat `ltm_evidence` as "memory notes/evidence", not as "assistant output".
- Require citations for memory claims, using provided `source_id#message_id`.
- Prohibit verbatim quoting unless asked.
- Instruct abstain/clarify when `service_verdict.decision` is not PASS.

Evidence should be provided in a consistent sectioned format to reduce model confusion.

## Verifier Rules (Post-LLM)

Required checks (baseline):
- In citation-visible mode (`render_citations=true`), PASS replies must include at least one exact citation token.
- In citation-hidden mode (`render_citations=false`), PASS replies may omit visible tokens but must not semantically abstain, and package-level citation provenance must be present.
- Every citation must match a citation present in the package evidence set.
- Supported test cases must cite evidence that maps back to expected anchors/atom IDs.
- Unsupported/unknown traps must abstain and must not cite unrelated evidence as if it supports a claim.

If verification fails:
- For eval: mark case FAIL and tag defect.
- For runtime integration: return an abstain/clarify "safe wrapper" reply.

## Eval Changes (Truthset -> Context Package -> Model)

New eval path must:
- Generate/validate truthset questions as before (question-quality gates still apply).
- For each case:
  1. Build `context-package v2`
  2. Call external model (LM Studio or FT)
  3. Verify output
  4. Record verdicts, defect tags, citations, and latencies
- Write artifacts in the same operator-friendly format:
  - `acceptance_gate.json` (dual verdict + failures + latency)
  - `human_readout.md` (Q + top evidence + model answer + citations + defect tags)

Acceptance is blocked unless:
- `false_memory_rate == 0`
- `abstain_precision == 1` (or configured floor)
- retrieval fanout remains bounded
- model output is natural enough per rubric (no parroting tool text, no unrelated context injection)
- latency stays within configured budgets

## Definition Of Done (This Phase)

1. `context-package v2` exists and is used by evals.
2. LM Studio local eval runs without paid endpoints.
3. FT endpoint eval runs and matches (or exceeds) local regression quality.
4. `human_readout.md` is skimmable and shows model output (not internal runtime replies).
5. Dual verdict is reported for every run; PASS language only when both pass.
