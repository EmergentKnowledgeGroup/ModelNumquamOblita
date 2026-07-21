# Pipeline Guide

## Purpose

The normal MNO build path turns raw source material into:
- durable evidence atoms
- draft episode cards
- human-reviewed episode memory
- runtime retrieval artifacts

## Normal pipeline

`raw source -> import -> atoms.sqlite3 -> draft episode cards -> Headless Curation Room or desktop Review -> human decisions -> publish -> verify -> activate -> runtime`

## Stage 1: import raw source

Generic import:

```bash
python3 tools/import_memories.py --input /absolute/path/to/source-or-folder
```

Supported raw source inputs:
- `conversations.json`
- `db.json` wrappers with `conversations[]`
- `.jsonl` chat logs
- `.txt` transcripts
- `.md` notes
- mixed folders containing any of the above

Desktop setup flow behavior:
- use `Add Files` to pick one or many files
- use `Add Folder` to pick one or many folders
- mix folders and individual files in one source list
- remove entries or clear the list before import
- choose either `New Store` or `Add To Existing Store`

Caveman rule:

`If your source is messy, point MNO at one folder.`
`If your source is split, add the folder and the extra files into one list.`

IA-shaped import:

```bash
python3 tools/import_ia_db.py --input /absolute/path/to/source-or-folder
```

Output:
- `atoms.sqlite3`

Automatic cleanup before insert:
- source files are normalized into conversations and turns
- whitespace is collapsed
- roles are normalized
- timestamps are normalized when possible
- obvious junk directories are skipped during folder walks
- unsupported structured payloads are filtered before extraction

What atoms are:
- small evidence-bearing memory records
- still tied to source provenance
- the main durable substrate used by runtime retrieval

## Stage 2: build draft episode cards

```bash
python3 tools/build_episode_cards.py --memories runtime/imports/atoms.sqlite3
```

Optional explicit output:

```bash
python3 tools/build_episode_cards.py \
  --memories runtime/imports/atoms.sqlite3 \
  --out runtime/episodes/episode_cards_manual.json
```

Draft cards are:
- operator-facing event memory candidates
- not published truth
- not runtime truth by themselves

## Stage 3: Headless Curation Room or desktop review

The same review workflow is available through the desktop setup wizard or the
generic loopback-only Headless Curation Room:

```bash
mno-curate --store runtime/imports/atoms.sqlite3
```

What it does:
- lets an assistant or agent inspect draft cards
- lets an assistant or agent propose bounded edits, titles, summaries, tags, and ranking hints
- keeps all proposals separate until explicit human promotion

What it does not do:
- publish
- verify
- activate
- silently mutate reviewed truth

The agent lane is draft-only and advisory. The browser room lets the human
complete the authoritative Review, Publish, Verify, and Activate gates without
opening the Electron desktop shell.

## Stage 4: human review

Build a review pack:

```bash
python3 tools/build_episode_review_pack.py \
  --episodes runtime/episodes/episode_cards_*.json
```

Typical review artifacts:
- `episode_cards.review.tsv`
- `episode_cards.review.md`
- `episode_cards.review_meta.json`

Human review remains authoritative.

## Stage 5: compile reviewed cards

```bash
python3 tools/build_episode_review_pack.py \
  --compile-reviewed runtime/episodes/review_pack_*/episode_cards.review.tsv
```

Output:
- `episode_cards.reviewed.json`

This is the episode artifact the runtime can actually trust.

## Stage 6: run the runtime

```bash
python3 tools/run_live_runtime.py \
  --memories runtime/imports/atoms.sqlite3 \
  --episodes runtime/episodes/episode_cards.reviewed.json
```

Normal runtime launch requires reviewed episode cards. If they are missing,
MNO stops with `CURATION_REQUIRED` and points the operator to `mno-curate`.
`--allow-uncurated` is an explicit unsafe development override and is never
treated as successful curation or activation.

## Runtime-only memory lanes

These are not part of the build/import truth path:
- short-term memory
- provisional memory
- proposal-only writeback
- pins, action log, wake-up pack, resume pack
- retrieval feedback
- built-in work-session scratchpad context for strict project/thread/workstream scoped v2 context packages

They are runtime helpers and operator surfaces, not replacements for reviewed truth.

### v0.2 authority order

`human_reviewed_canonical` → `evidence_atom` → `provisional_consolidated` → `provisional_observed`

The arrow means authority, not a silent promotion path. Autonomous observation may mature only provisional records (`observed → reinforced → consolidated`) and cannot create canonical truth. A reviewer-applied writeback becomes an `evidence_atom` with `human_reviewed=false`; it still needs the normal build/review/publish path to become canonical. STM and WSS are not tiers in this order: they are scoped helper context and cannot support a durable factual claim.

Raw import and live observation are different lanes. Import starts from source material and materializes evidence atoms. `memory.observe` records a completed live turn only when its independent source evidence is bound by signed source registrations and, for assistant candidates, a signed retrieval receipt. Repeated retrieval, replay, quotation, or generated summaries are not independent evidence.

## Contract rule

Draft, proposal, and runtime-helper artifacts do not become reviewed truth unless they pass the explicit human-controlled path.

WSS-specific rule: `scratchpad_ephemeral` can help an agent resume work, but it cannot support a memory claim. See [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md).
