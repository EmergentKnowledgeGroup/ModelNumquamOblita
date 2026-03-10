# Pipeline Refinement Execution Spec (Phased, Implementation-Ready)

Status: Implemented (phases 0–7 complete)  
Owner: NumquamOblita Core  
Last Updated: 2026-02-16  

This document is both:
- the **single execution spec** for the refinement pipeline, and
- a **completion record** (the phase DoD checklists below are marked complete because the corresponding surfaces exist in the repo).

North star contracts (do not drift):
- `docs/NEAR_PERFECT_GOAL.md`
- `docs/CONTEXT_PACKAGE_V2_EXTERNAL_RESPONDER_EVAL_SPEC.md`
- `docs/MEMORY_FORMATION_GAMEPLAN.md`
- `docs/EPISODIC_MEMORY_CARD_BUILD_SPEC.md`
- `docs/EVENT_MEMORY_EVENT_CUE_SPEC.md`
- `docs/PIPELINE_VERIFICATION_REPORT_20260213.md` (what exists + known gaps)

This is the **single execution spec** for refining NumquamOblita from “verified working” to “product-grade.”

> Testing policy (directive):
> - “Does the memory recall system work?” tests are **local-only verification** and do not ship.
> - “Is the pipeline wired correctly?” tests (import/build/retrieval connectivity) remain tracked.
> - This document is written to be implementation-ready without being code. It is the plan you implement from.

Quick “is it shipped?” pointers (as-built):
- Operator flow: `docs/guides/PIPELINE_END_TO_END.md`
- Public diagrams: `docs/public/ARCHITECTURE.md`
- Runtime UI tour: `docs/guides/RUNTIME_UI_TOUR.md`
- Runtime/API surface: `docs/api/API_MATRIX.md`

---

## 0) Executive Summary (what we are doing and why)

We already verified the end-to-end system works (import → memory store → context package → external model → verifier). The gaps are now mostly:
- schema drift vs specs,
- episode cards not as strong/structured as the long-term spec wants,
- episode-first retrieval not strict enough,
- missing non-technical UX (wizard, builder, management),
- missing safe writeback + packaging.

The clean order is:
1) lock contracts, naming, artifact conventions (Phase 0)
2) lock episode card schema + diagnostics (Phase 1)
3) improve episode quality + segmentation (Phase 2)
4) enforce episode-first retrieval + fix context-package alignment (Phase 3)
5) formalize evidence vs episodic tier behavior (Phase 4)
6) ship a GUI wizard + episode builder UI (Phase 5)
7) ship memory management + “Why this answer?” UI (Phase 6)
8) add safe writeback + single-exe packaging + health checks (Phase 7)

---

## 1) Non-Negotiables (design constraints)

### 1.1 Truthfulness
- The system must not produce unsupported-memory claims (no “made-up memories”).
- If evidence is insufficient, the system must abstain or ask one clarifying question (per service verdict).

### 1.2 Provenance
- Every PASS memory claim must be traceable to evidence delivered in `context_package v2`.
- Internal citations are always required for PASS decisions.
- Visible citations are optional (default OFF for natural chat; ON for audit/eval).

### 1.3 Naturalness
- No internal jargon in user-facing assistant output.
- No “robot template” phrasing (`Acknowledged:`, `Memory-backed response for:`).
- Routine chat must feel like routine chat (short, normal).

### 1.4 Offline-first
- Entire pipeline must run locally with a local provider (LM Studio or similar).
- Paid cloud providers are optional and must be a config switch, not a dependency.

### 1.5 Boundedness and reversibility
- Retrieval fanout is bounded.
- Evidence payload is bounded.
- Every pipeline step produces artifacts and supports rollback (backup + restore).

---

## 2) Glossary (terms we will not drift on)

- Evidence: raw source-backed text from archive, citeable.
- Memory atom: deterministic evidence unit in SQLite (often 1 message).
- Episode card: event-level memory artifact built from multiple atoms/turns.
- Service verdict: deterministic decision from NO (`PASS|ABSTAIN|CLARIFY|NO_MEMORY`) intended to constrain the model.
- Context package v2: memory service output consumed by the external responder.
- External responder: provider-agnostic model caller producing the user-facing response from context package.
- Citation token: a string in format `source_id#message_id` that must exist in the package evidence set.
- Builder profile: a user-curation profile that teaches the system “what counts” as names/cues/domains for that user’s archive.
- Review pack: a human-editable approval artifact (TSV + guide) used to approve/reject/edit episode cards before they’re used in runtime.
- Published artifacts: the versions that runtime uses by default (reviewed episodes; active store).
- Draft artifacts: intermediate outputs (unreviewed episode build; candidate proposals).
- Writeback: any operation that changes the memory store based on live chat activity.

---

## 3) What ships vs what is local-only

### 3.1 Shippable product surface
- A GUI that leads a non-technical user through:
  - import archive
  - build episode cards
  - curate (builder)
  - review/approve
  - verify
  - go-live chat
- A runtime chat surface using:
  - context package v2
  - external responder model call
  - post-LLM verifier
- A memory management UI:
  - browse episodes and atoms
  - disable/rollback
  - inspect “Why this answer?”

### 3.2 Local-only verification surface (not shipped)
- Large-scale eval harnesses and truthset generation used for development confidence.

### 3.3 Diagnostics that SHOULD ship (user-facing)
- Health check screen (store integrity, episode cards loaded, model provider reachable).
- “Export diagnostics” button producing a zip of key artifacts/logs (no secrets).

---

## 4) Target architecture (steady-state)

### 4.1 High-level pipeline

```text
IA: db.json (clean archive) + optional FT endpoint
          |
          v
NO Import -> atoms.sqlite3 (evidence atoms)
          |
          v
Episode Build -> episode_cards_<stamp>.json + rejects + readout
          |
          v
Review Pack -> episode_cards.reviewed.json (published episodic memories)
          |
          v
Runtime Chat:
  user msg -> context_package v2 (episode-first evidence) -> external model -> verifier -> reply
          |
          v
Memory Management UI ("Why this answer?", edit/disable/rollback)
```

### 4.2 Default artifact locations (local dev)
- Evidence store (sqlite): `.runtime/imports/atoms.sqlite3`
- Import reports: `.runtime/imports/import_ia_<stamp>.{json,md}`
- Episode builds (draft): `runtime/episodes/episode_cards_<stamp>.json`
- Episode rejects: `runtime/episodes/episode_cards_<stamp>.rejects.json`
- Episode readout: `runtime/episodes/episode_cards_<stamp>.readout.md`
- Episode review packs: `runtime/episodes/review_packs/episode_review_pack_<stamp>/`
- Episode published set: `runtime/episodes/episode_cards.reviewed.json` (or `episode_cards.approved.json`)
- Live runs (chat): `runtime/live_runs/live_<stamp>/` (turn logs + packages + provider stats)
- Backups: `runtime/backups/backup_<stamp>/` (store + episodes + profiles)

Packaging note: in a desktop app, these map to an app data directory (per-user), but the same structure remains.

---

## 5) Contracts (explicit schemas and rules)

This section is the “nuts-and-bolts” so implementation has no ambiguity.

### 5.1 Input contract: IA `db.json`

Required:
- top-level object with `conversations: []`
- each conversation:
  - has `id` (string, stable)
  - has `messages: []`
- each message:
  - `role` in `{user, assistant}` (system/tool messages may exist but are ignored for memory)
  - `text` (string) OR `content` (string/object)
  - `time_iso` (preferred) OR `time` (epoch/float/int)

Rules:
- If a message has no stable ID, importer MUST synthesize `message_id` deterministically from message index (e.g., `m000123`).
- Every imported message must have a `source_id` equal to conversation id (or a stable derived id).
- Timestamps are normalized to UTC; if missing, they may be null but episode building will treat them as low quality.

### 5.2 Memory store contract: atoms (SQLite)

Atom is the minimal evidence unit.

Required properties (conceptual):
- `atom_id`: stable
- `canonical_text`: normalized text
- `source_refs[]`: at least one, each includes:
  - `source_id` (conversation id)
  - `message_id` (stable; synthetic ok)
  - `timestamp` (UTC if known)

Rules:
- Store must be append-only in provenance/audit terms (user edits are new versions or tombstones, not silent rewrites).
- “Disable” is a reversible status, not deletion.

### 5.3 Episode cards contract: `EpisodeCards.v1`

We standardize episode cards as a separate artifact with explicit schema and compatibility.

#### 5.3.1 Root object
Required fields:
- `schema`: `numquamoblita.episode_cards.v1`
- `generated_at`: ISO timestamp
- `source_store`: path/id of the atoms store used
- `build_policy`: object (thresholds used)
- `counts`: `{ atom_count, episode_count, promoted_count, candidate_count, rejected_count }`
- `cards`: array of episode card objects

#### 5.3.2 Episode card object
Required fields:
- Identity:
  - `episode_id` (string)
  - `card_type`: `episode_event`
  - `promotion_status`: `promoted|candidate|rejected|approved`
  - `promotion_reason` (string enum-ish)
- Content:
  - `title` (short)
  - `summary` (2–5 lines, no tool jargon)
- Anchors:
  - `actors` (array of strings; canonical)
  - `topic_tags` (array of strings; canonical)
  - `cue_terms` (array of strings used for retrieval)
- Provenance:
  - `citations` (array of `source_id#message_id` tokens)
  - `linked_atom_ids` (array)
  - `message_ids` (array; redundant but convenient)
- Time bounds:
  - `timestamp_start` (ISO)
  - `timestamp_end` (ISO)
- Event window:
  - `event_window`: object with:
    - `before`: `{ citation, message_ids[] }`
    - `core`: `{ message_ids[] }`
    - `after`: `{ citation, message_ids[] }`
- Quality metrics (float 0..1 unless noted):
  - `confidence`
  - `evidence_strength`
  - `event_shape_score`
  - `anchor_strength`
  - `retrieval_weight`
  - `quality_flags[]` (array of strings)

Compatibility rule (migration safety):
- For at least one release cycle, cards MAY also include legacy aliases:
  - `entities` as alias for `actors`
  - `topics` as alias for `topic_tags`
  - `start_at` as alias for `timestamp_start`
  - `end_at` as alias for `timestamp_end`

#### 5.3.3 Rejects artifact
We require a separate rejects artifact to support human debugging:
- file: `episode_cards_<stamp>.rejects.json`
- contains:
  - `schema: numquamoblita.episode_cards.rejects.v1`
  - `generated_at`
  - `source_cards` (path to the draft cards file)
  - `rejected[]`: array of `{ episode_id, reasons[], quality_flags[], key_fields_snapshot }`

### 5.4 Episode review pack contract

Directory structure:
- `guide.md`: plain instructions
- `meta.json`: links to source cards and timestamps
- `review.tsv`: table with:
  - immutable columns: `episode_id`, `title`, `summary`, `timestamp_start`, `timestamp_end`, `actors`, `topic_tags`, `citations_count`, `quality_flags`
  - review columns: `review_status (APPROVE|REJECT|EDIT|PENDING)`, `edited_title`, `edited_summary`, `edited_actors`, `edited_topic_tags`, `review_note`
- compile output:
  - `episode_cards.reviewed.json` with only APPROVE/EDIT applied

Rules:
- Runtime only consumes the **reviewed** set by default (published episodic tier).
- The GUI must support generating and compiling review packs without manual file hacking.

### 5.5 Builder profile contract (user curation)

Builder profile is how a non-technical user teaches the system “what is a real name / alias / cue / domain” in their archive.

File:
- `runtime/builder_profiles/profile_<id>.json`

Required fields:
- `schema: numquamoblita.builder_profile.v1`
- `profile_id`
- `created_at`, `updated_at`
- `entities`: array of:
  - `{ value, kind, status, aliases[], notes }`
  - `kind`: `person|place|project|concept|other`
  - `status`: `include|exclude|alias_of`
- `cue_phrases`: array of `{ value, status, notes }`
- `domain_rules`: array of `{ pattern, domain, status }`

Rules:
- Profiles are additive and reversible (no destructive edits without confirmation).
- Episode build uses the profile to:
  - boost real actors/topics,
  - suppress garbage entities,
  - improve titles/summaries/cue_terms.

### 5.6 Context package v2 contract (service output)

Context package v2 is the product surface consumed by external responder.

Required top-level fields:
- `package_version: "v2"`
- `message` (user text)
- `preview` (route, reason, memory_mode, etc.)
- `timing_ms` (build/stm/ltm/verifier)
- `retrieval_stats` (retrieved ids, passes, stop reason, episode hit stats)
- `ltm_evidence[]` (bounded evidence items)
- `service_verdict`:
  - `decision: PASS|ABSTAIN|CLARIFY|NO_MEMORY`
  - `citations[]`: MUST be `source_id#message_id` tokens (not source_id-only)
  - `unsupported_claims[]` (optional but useful)
- `responder_guidance`:
  - `require_citations: true`
  - `abstain_without_evidence: true`
  - `render_citations: true|false`
  - `citation_format: "source_id#message_id"`

Additional required refinement fields (to close known gaps):
- `evidence_time_window`:
  - `{ start_at, end_at, display }`
  - computed from evidence timestamps (min/max), display is a human-readable string in UTC.
- `evidence_sections_present`:
  - includes whether episode evidence is present (explicit boolean).

### 5.7 External responder contract

Responder must:
- obey service verdict
- cite evidence tokens when `render_citations=true`
- omit citation tokens when `render_citations=false` (but still be constrained by evidence)
- abstain EXACTLY with canonical phrase when service verdict is ABSTAIN

Canonical abstain phrase:
- `I don't have that memory.`

Verifier rules (high-level):
- PASS + citations visible => at least one valid citation token present in reply
- PASS + citations hidden => reply must not abstain and internal citation provenance must exist in package
- ABSTAIN => reply must contain abstain marker; must not cite
- Unknown citations in reply => FAIL

---

## 6) Phase plan (expanded: dependencies, deliverables, gates)

Phases are sequential on purpose. Each phase locks a contract or behavior that later phases depend on.

### Phase gate template (applies to every phase)
Each phase MUST explicitly define:
- **Inputs**: what artifacts/config must exist before starting.
- **Outputs**: what new artifacts/schemas/UI surfaces exist after completion.
- **Backward compatibility**: how older artifacts are handled (loaders, aliases).
- **Operator workflow**: the exact clicks/commands a human uses.
- **Local verification**: how we convince ourselves it works (not shipped).
- **Rollback**: how we revert without data loss.
- **Definition of Done (DoD)**: a checklist that can be read and marked complete.

---

### Phase 0 — Contract lock + artifact conventions

Objective:
- Freeze naming, schemas, and what counts as “the judged surface” so we stop thrashing.

Dependencies: none

Scope (decisions locked in writing):
- Episode card canonical field names and aliases.
- Citation token format and strictness.
- Artifact paths, naming, and “draft vs published” semantics.
- “Acceptance surface” confirmation: context-package v2 + external responder output.
- Default: `render_citations=false` for chat; `true` only for audit.

Deliverables:
- This document updated and explicitly approved as the system spec of record.
- A short glossary doc for stakeholders: “Evidence vs Memory vs Episode.”
- Artifact naming spec:
  - what file names are used
  - how stamps are generated
  - which file is “published default”
- Traceability table:
  - each contract requirement in the north-star docs maps to:
    - a context-package field OR
    - an episode-card field OR
    - a GUI feature

Phase 0 lock decisions (effective immediately):
- Canonical episode-card fields are:
  - `actors`, `topic_tags`, `timestamp_start`, `timestamp_end`
- Legacy aliases are accepted for one compatibility cycle only:
  - `entities -> actors`
  - `topics -> topic_tags`
  - `start_at -> timestamp_start`
  - `end_at -> timestamp_end`
- Citation token strictness:
  - canonical token format is always `source_id#message_id`
  - source-only tokens are non-compliant in strict eval/audit paths
- Judged acceptance surface:
  - only `context-package v2` + external responder output + verifier results
  - internal standalone runtime answer text is debug-only and non-gating
- Render mode defaults:
  - chat default is `render_citations=false`
  - strict eval/audit uses `render_citations=true`

Artifact naming and published defaults:
- Stamp format:
  - `<stamp> := YYYYMMDDTHHMMSSZ` (UTC)
- Draft artifacts:
  - `runtime/episodes/episode_cards_<stamp>.json`
  - `runtime/episodes/episode_cards_<stamp>.rejects.json`
  - `runtime/episodes/episode_cards_<stamp>.readout.md`
  - `runtime/episodes/review_packs/episode_review_pack_<stamp>/`
- Published episodic artifact consumed by runtime by default:
  - `runtime/episodes/episode_cards.reviewed.json`
- Published pointers (wizard/runtime) must resolve to explicit file paths and be restart-stable via persisted wizard state.

Local verification (non-shipping):
- N/A (this is planning + signoff only).

Rollback:
- N/A.

DoD checklist:
- [x] Canonical field names chosen and documented.
- [x] “Published artifacts” definition is explicit.
- [x] “Judged surface” is explicit.

Risks:
- Decision churn → mitigation: “write it once, approve, then implement.”

---

### Phase 1 — Episode card schema + rejects/diagnostics (make the artifacts real)

Objective:
- Make episode cards match the promised spec fields and make failures debuggable by humans.

Dependencies: Phase 0

Inputs:
- A working atoms store (`atoms.sqlite3`).
- Episode builder can already produce draft cards (even if imperfect).

Scope:
- EpisodeCards.v1 becomes a **real schema**, not “whatever the builder emits today.”
- Every episode build produces:
  1) draft cards
  2) rejects/diagnostics
  3) a human-skimmable readout
  4) a review pack (TSV or UI equivalent)
- Compatibility rules are enforced (aliases allowed for one cycle).

Deliverables (concrete artifacts):
- `runtime/episodes/episode_cards_<stamp>.json` (EpisodeCards.v1 root schema)
- `runtime/episodes/episode_cards_<stamp>.rejects.json`
- `runtime/episodes/episode_cards_<stamp>.readout.md`
- `runtime/episodes/review_packs/episode_review_pack_<stamp>/` containing:
  - `guide.md`
  - `meta.json`
  - `review.tsv`
- `runtime/episodes/episode_cards.reviewed.json` (published set after compile)

Required behavior details:
- Cards MUST contain canonical fields (`actors`, `topic_tags`, `timestamp_start`, `timestamp_end`).
- Cards MUST contain citations in `source_id#message_id` format.
- Rejects MUST include machine-readable reasons (not just prose).
- Readout MUST show:
  - title + summary
  - actors/topic tags
  - time window
  - top citations
  - why promoted vs rejected

Local verification (non-shipping):
- Generate one build and confirm:
  - draft + rejects + readout all exist
  - review pack can be compiled into reviewed set
  - runtime can load reviewed set without errors

Rollback:
- Draft builds are never used by runtime by default.
- Keep last known-good `episode_cards.reviewed.json` and allow switching back.

DoD checklist:
- [x] EpisodeCards.v1 schema documented + enforced.
- [x] Rejects artifact exists and is informative.
- [x] Review pack round-trips (approve/edit/reject) into reviewed JSON.

Risks:
- Breaking older loaders → mitigation: alias fields for one release and add a schema_version guard.

---

### Phase 2 — Episode quality + segmentation (event-grade episodes)

Objective:
- Ensure promoted episodes are real multi-turn events, not stitched fragments or vibe lines.

Dependencies: Phase 1

Inputs:
- EpisodeCards.v1 draft pipeline exists.
- Builder profile contract exists (even if GUI not built yet).

Scope (quality and segmentation rules):
- Episode segmentation considers:
  - time gaps
  - speaker transitions (user↔assistant alternation)
  - topic shift signals (lexical change / cue changes)
  - domain shifts (if domain tagging exists)
- Promotion thresholds default to:
  - minimum distinct turns/messages ≥ 3
  - minimum meaningful token count ≥ 30 (across event window)
  - at least one “event-shape” signal (transition/action/outcome)
- Missing timestamps:
  - episodes with unknown time bounds are allowed but cannot be auto-promoted unless evidence is very strong (explicit rule).

Deliverables:
- Improved build_policy presets (explicitly versioned, e.g. `policy: "v1_strict_event_grade"`).
- Episode card summaries/titles avoid “single snippet as title” failure mode.
- Quality flags cover all demotions with no “silent” demotions.

Local verification (non-shipping):
- Build episodes and manually skim the readout for:
  - promoted set feels event-like
  - rejects explain demotions
  - low-info acknowledgements are excluded

Rollback:
- Keep previous build policy preset selectable.

DoD checklist:
- [x] Promotions reflect event-grade thresholds.
- [x] Episode readout no longer contains fragment-only promoted cards.

Risks:
- Over-strict thresholds reduce recall coverage → mitigation: keep candidate tier + human review workflow.

---

### Phase 3 — Episode-first retrieval + context-package alignment (make runtime obey the memory design)

Objective:
- Make recall-style prompts retrieve episode cards first, and make context package v2 match the spec exactly.

Dependencies: Phase 2

Inputs:
- Reviewed episode set exists (`episode_cards.reviewed.json`).
- Runtime can load episode index.

Scope:
- Recall intent detection:
  - “remember when…”, “what happened…”, “walk me through…”, “do you remember…”, timeline prompts.
- Retrieval routing:
  - recall intent → episode-first
  - factual intent → evidence atoms first
  - routine intent → none/STM
- Context package v2:
  - service verdict citations must be full tokens (`source_id#message_id`)
  - add `evidence_time_window`
  - explicit `episode_evidence_present` flag (or equivalent in `evidence_sections_present`)

Deliverables:
- Context package v2 is unambiguous and self-contained for downstream models.
- “Why this answer?” surface can show time window and citations.

Local verification (non-shipping):
- For a recall prompt:
  - context package includes episode evidence when episodes exist
  - verdict citations are usable tokens (not source-only)
- For a routine prompt:
  - context package shows route=none and no evidence payload inflation

Rollback:
- Feature flag to disable episode-first routing (emergency only).

DoD checklist:
- [x] Context package v2 includes time window.
- [x] Service verdict citations are full tokens.
- [x] Episode evidence presence is explicit.

Risks:
- Episode index quality causes false negatives → mitigation: bounded fallback to atom retrieval when episodes missing.

---

### Phase 4 — Evidence vs episodic tier separation (make “evidence” stop pretending to be “memory”)

Objective:
- Stop treating single-line evidence as episodic memory by default, even if it remains searchable.

Dependencies: Phase 3

Inputs:
- Episode-first runtime routing exists.

Scope:
- Ingest classification tightening:
  - EPISODE atom type is no longer the default catch-all label.
  - most turns become atomic_fact / relational / affective / procedural_style (or “evidence” semantics) unless eventness is high.
- Retrieval weighting:
  - episodic recall uses episode cards as “memory”
  - atoms become “details” and should not dominate recall prompts
- Context packaging:
  - episode cards summarized as the memory
  - evidence atoms included only as bounded supporting detail

Deliverables:
- Predictable user experience:
  - “remember when” feels like events, not fragments
  - “what did we say about X” can still pull precise evidence

Local verification (non-shipping):
- Spot check a set of recall prompts:
  - with episodes available → memory is episode-shaped
  - with no episodes → graceful fallback, still truthful

Rollback:
- Config preset to restore previous extractor and weighting if needed.

DoD checklist:
- [x] Single-line fragments no longer drive recall when episodes exist.

Risks:
- Some archives are sparse and need atoms as “memories” → mitigation: fallback lane when episodic tier is empty.

---

### UI/UX skill contract (required for Phases 5–7)

Execution requirement:
- All Phase 5–7 UI/UX implementation must explicitly use the `$frontend-design` skill:
  - `/home/ultx/.codex/skills/frontend-design/SKILL.md`

Minimum design workflow (non-optional):
- Before coding each surface, write a short design brief:
  - purpose/user goal,
  - bold aesthetic direction,
  - one memorable differentiator.
- Build production-grade UI with intentional typography, color system, motion, and layout composition.
- Avoid generic AI UI defaults; visual language must be distinctive and cohesive.
- Preserve existing product patterns where already established; apply the skill to elevate quality, not create random drift.
- Desktop and mobile layouts must both be usable and coherent.

---

### Phase 5 — GUI wizard + episode builder UI (non-technical pipeline)

Objective:
- Ship a GUI that a non-technical user can use end-to-end with safe defaults and resumability.

Dependencies: Phase 4

Inputs:
- All contracts stable: episode cards, review pack, context package.

Scope:
- A wizard that implements a deterministic state machine:
  - Welcome/Resume → Import → Build Episodes → Builder Curation → Review → Verify → Go Live
- Every wizard step writes a durable state file (so crash/restart resumes safely).
- The wizard exposes progress/time estimates and clear errors.
- Screen/UI implementation follows the required `$frontend-design` workflow above.

Wizard state contract:
- persisted at `runtime/wizard_runs/wizard_<stamp>/wizard_state.json`
- includes:
  - selected input archive path
  - store path
  - last built episode draft path
  - last compiled reviewed path
  - builder profile id
  - “published” pointers

Screen-level spec (must exist, with these minimum behaviors):
- Screen: Welcome/Resume
  - shows last wizard run and “Resume” button
  - shows “Start new” button
- Screen: Import
  - file chooser for `db.json`
  - “Validate” button that reports counts and obvious issues
  - “Import” button that creates/updates store and writes an import report
- Screen: Build Episodes
  - select build policy preset (default strict)
  - “Build” button producing draft + rejects + readout
  - show counts: promoted/candidate/rejected
- Screen: Builder (Curation)
  - entity list with include/exclude/alias-of
  - cue phrase list with include/exclude
  - domain rules editor (basic: include/exclude patterns)
  - “Save profile” and “Rebuild episodes” actions
- Screen: Review
  - inline review UI (no external spreadsheet required)
  - approve/edit/reject per card
  - “Compile reviewed set” produces published reviewed JSON
- Screen: Verify
  - runs a small local verification pass (no paid calls by default)
  - shows: “Safe”, “Needs attention”, with links to the exact cards/evidence
- Screen: Go Live
  - starts local chat UI
  - shows provider/model config panel

Deliverables:
- GUI wizard implemented with the above screens and persisted state.
- Builder profiles saved and reused.
- Review is possible without leaving the app.

Local verification (non-shipping):
- Complete the wizard from scratch on an IA archive without CLI.
- Kill app mid-step and confirm resume works.
- Run a quick design QA pass against the `$frontend-design` brief (typography, motion, spacing, responsive behavior).

Rollback:
- “Restore last published” button that swaps pointers back to last reviewed episodes/store.

DoD checklist:
- [x] A non-technical user can complete the pipeline without docs.
- [x] Wizard resumes after restart.
- [x] All artifacts are discoverable in-app (“Open output folder”).

Risks:
- UI scope creep → mitigation: ship only the minimal screens above; add polish later.

---

### Phase 6 — Memory management UI + “Why this answer?”

Objective:
- Give users control surfaces so the system is trustable and correctable.

Dependencies: Phase 5

Inputs:
- Live chat UI exists.
- Context package includes time window and citations.

Scope:
- Memory browser:
  - list and filter episode cards (approved/rejected/disabled)
  - list and filter atoms (active/superseded/conflicted)
- Memory edit flows:
  - disable/enable
  - edit title/summary/actors/topic tags (episodes)
  - mark conflicts (atoms) with a reason
- “Why this answer?” panel in chat:
  - service verdict (plain words)
  - top evidence summaries
  - citations (toggle reveal)
  - evidence time window
  - “open the cited message” action (navigates to archive viewer)
- Screen/UI implementation follows the required `$frontend-design` workflow above.

Deliverables:
- A user can answer:
  - “Why did you say that?”
  - “Where did that come from?”
  - “Turn that off / correct it”

Local verification (non-shipping):
- In chat, click “Why this answer?” and verify it matches the context package.
- Disable an episode and confirm it stops appearing in retrieval.
- Run a quick design QA pass against the `$frontend-design` brief (typography, motion, spacing, responsive behavior).

Rollback:
- Every edit is versioned and reversible.
- Provide “undo last change” button with audit log.

DoD checklist:
- [x] “Why this answer?” exists and is readable.
- [x] Episodes can be disabled and changes take effect immediately.

Risks:
- Too much power without guardrails → mitigation: confirmations + audit log + rollback.

---

### Phase 7 — Safe writeback + single-exe packaging + health checks

Objective:
- Make the app distributable and safe in live usage over time.

Dependencies: Phase 6

Inputs:
- User can manage memories through UI (required before writeback).

Scope:
- Writeback defaults to OFF.
- When enabled, writeback creates **proposals**, not immediate commits:
  - proposal contains the new evidence pointer(s) and suggested atom/card changes
  - user must approve to publish
- Packaging:
  - Windows-first single executable
  - local data directory
  - bundled UI + runtime server + config UI
- Health check:
  - store integrity
  - episode cards load
  - provider reachable
  - disk space + permissions
  - diagnostic export
- Screen/UI implementation follows the required `$frontend-design` workflow above.

Deliverables:
- “Safe update” memory writeback policy and UI.
- Single-exe build instructions and release pipeline.
- Health check dashboard and export.

Local verification (non-shipping):
- Enable writeback, generate a proposal, approve it, and verify it appears in memory browser.
- Run health check offline with local model provider.
- Run a quick design QA pass against the `$frontend-design` brief (typography, motion, spacing, responsive behavior).

Rollback:
- Restore last backup; disable writeback.

DoD checklist:
- [x] Writeback cannot silently change memory without approval.
- [x] Health check can be run by non-technical users.
- [x] Packaging is one-click install/run.

Risks:
- Corrupting memory store via writeback → mitigation: staged proposals + atomic swaps + backups.

---

## 7) Cross-phase dependency graph (hard order)

- Phase 0 → everything
- Phase 1 → 2 → 3 → 4 → 5 → 6 → 7

Rationale:
- UI work before contract/schema work causes guaranteed rework.
- Writeback before management UI is unsafe (no user control surface).

---

## 8) Gap-to-phase traceability (what we close where)

Known gaps (from verification report) and where they are closed:
- Episode card missing fields / schema drift → Phase 1
- Weak event_window structure → Phase 1–2
- Loose promotion thresholds → Phase 2
- Episode-first retrieval not strict → Phase 3–4
- Context package citation token mismatch → Phase 3
- Missing human-readable time windows → Phase 3
- Missing GUI wizard + builder → Phase 5
- Missing memory management + “Why” → Phase 6
- No safe LTM writeback, no packaging, no health check → Phase 7

### 8.1) North-star requirement traceability table

| Requirement source | Requirement | Contract surface |
|---|---|---|
| `docs/NEAR_PERFECT_GOAL.md` | No unsupported memory claims | `service_verdict.decision`, responder verifier pass/fail rules |
| `docs/NEAR_PERFECT_GOAL.md` | Memory claims are citation-backed | `ltm_evidence[].citations`, `service_verdict.citations` |
| `docs/NEAR_PERFECT_GOAL.md` | Unknown memory traps abstain | `service_verdict=ABSTAIN`, canonical abstain phrase enforcement |
| `docs/NEAR_PERFECT_GOAL.md` | Routine chat stays lightweight | routing (`none\|stm_only`) + bounded `ltm_evidence` behavior |
| `docs/CONTEXT_PACKAGE_V2_EXTERNAL_RESPONDER_EVAL_SPEC.md` | Judged surface is package + external responder | `POST /api/chat/context-package` v2 + external provider + verifier output |
| `docs/CONTEXT_PACKAGE_V2_EXTERNAL_RESPONDER_EVAL_SPEC.md` | Citation token format is strict | `source_id#message_id` across evidence + service verdict + verifier |
| `docs/MEMORY_FORMATION_GAMEPLAN.md` | Event recall is episode-first | reviewed `EpisodeCards.v1` + episode-first retrieval routing |
| `docs/EPISODIC_MEMORY_CARD_BUILD_SPEC.md` | Episodes are multi-turn event memory | `EpisodeCards.v1` fields (`actors`, `topic_tags`, `event_window`, evidence scores) |
| `docs/EVENT_MEMORY_EVENT_CUE_SPEC.md` | Cue-first event recall quality | cue-aware episode retrieval + compact/bounded context evidence |
| `AGENTS.md` | Dual verdict required for PASS language | `safety_verdict` + `human_quality_verdict` gates in run artifacts |

---

## 9) Implementation workflow (when executing this spec)

This is how execution should be run to avoid losing the plot:
- One phase per PR (no mixed scope).
- Every phase produces:
  - updated checkpoint (`runtime/checkpoints/LATEST.md` + `.json`)
  - new/updated docs and example artifacts
  - local-only verification run notes (not shipped)

---

## Appendix A — Example EpisodeCards.v1 (illustrative)

```json
{
  "schema": "numquamoblita.episode_cards.v1",
  "generated_at": "2026-02-13T20:15:00Z",
  "source_store": ".runtime/imports/atoms.sqlite3",
  "build_policy": {
    "min_turns": 3,
    "min_meaningful_tokens": 30
  },
  "counts": {
    "atom_count": 12034,
    "episode_count": 412,
    "promoted_count": 128,
    "candidate_count": 220,
    "rejected_count": 64
  },
  "cards": [
    {
      "episode_id": "ep_001",
      "card_type": "episode_event",
      "promotion_status": "promoted",
      "promotion_reason": "event_shape_and_anchors",
      "title": "Planning the LM Studio eval run",
      "summary": "We adjusted sampling settings and reran a larger eval to confirm memory behavior.",
      "actors": ["Lyra", "NumquamOblita"],
      "topic_tags": ["evals", "lmstudio", "latency"],
      "cue_terms": ["lm studio", "eval run", "p95 latency"],
      "citations": ["conv_123#m000045", "conv_123#m000046"],
      "linked_atom_ids": ["mem_a", "mem_b"],
      "message_ids": ["m000045", "m000046"],
      "timestamp_start": "2026-02-13T19:50:00Z",
      "timestamp_end": "2026-02-13T20:02:00Z",
      "event_window": {
        "before": { "citation": "conv_123#m000045", "message_ids": ["m000044"] },
        "core": { "message_ids": ["m000045", "m000046"] },
        "after": { "citation": "conv_123#m000046", "message_ids": ["m000047"] }
      },
      "confidence": 0.74,
      "evidence_strength": 0.71,
      "event_shape_score": 0.68,
      "anchor_strength": 0.62,
      "retrieval_weight": 0.72,
      "quality_flags": []
    }
  ]
}
```
