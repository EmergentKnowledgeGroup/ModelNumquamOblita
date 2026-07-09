# Pipeline Guide

## Purpose

The normal MNO build path turns raw source material into:
- durable evidence atoms
- draft episode cards
- human-reviewed episode memory
- runtime retrieval artifacts

## Normal pipeline

`raw source -> import -> atoms.sqlite3 -> draft episode cards -> optional assistant/agent draft curation -> human review -> reviewed episode cards -> runtime`

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

## Stage 3: optional assistant/agent draft curation

The clean repo includes an optional weld-in between Build and Review.

What it does:
- lets an assistant or agent inspect draft cards
- lets an assistant or agent propose bounded edits, titles, summaries, tags, and ranking hints
- keeps all proposals separate until explicit human promotion

What it does not do:
- publish
- verify
- activate
- silently mutate reviewed truth

This lane is draft-only and advisory.

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

The runtime can still run without reviewed episode cards, but then it is leaning more on atoms and runtime memory layers.

## Runtime-only memory lanes

These are not part of the build/import truth path:
- short-term memory
- provisional memory
- proposal-only writeback
- pins, action log, wake-up pack, resume pack
- retrieval feedback
- built-in work-session scratchpad context for strict project/thread/workstream scoped v2 context packages

They are runtime helpers and operator surfaces, not replacements for reviewed truth.

## Contract rule

Draft, proposal, and runtime-helper artifacts do not become reviewed truth unless they pass the explicit human-controlled path.

WSS-specific rule: `scratchpad_ephemeral` can help an agent resume work, but it cannot support a memory claim. See [Work-Session Scratchpad](WORK_SESSION_SCRATCHPAD.md).
