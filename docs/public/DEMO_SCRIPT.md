# NumquamOblita Demo Script (Operator + Stakeholder)

This is a lightweight script for a ~8–12 minute demo of the full “import → episode build → chat → why” loop.

## Setup (1–2 minutes)

- Run setup: `./setup_local.sh` (Windows: `setup_local.bat`)
- Start runtime UI: `python3 tools/run_runtime_demo.py --host 127.0.0.1 --port 7340`
- Open: `http://127.0.0.1:7340/`

## Part 1 — Pipeline Wizard (3–5 minutes)

1) **Resume / Start new**
- In “Pipeline Wizard”, click **Start New** (or **Resume** if you have a prior run).

2) **Import**
- Paste a path to an IA `db.json`.
- Click **Validate**, then **Import**.
- Call out: importer produces an evidence store (`atoms.sqlite3`) with provenance.

3) **Build Episodes**
- Select policy `strict (recommended)`.
- Click **Build**.
- Call out: build produces draft episode cards + rejects + a human-skimmable readout.

4) **Review**
- Skim a few draft cards in the review list.
- Approve/reject one example (optional).
- Click **Compile Reviewed Set**.
- Call out: reviewed/published episodes are the default unit used for recall-style prompts.

5) **Verify**
- Click **Run Local Verification**.
- Call out: verification is intended to fail-closed; issues should be actionable.

## Part 2 — Runtime Chat + “Why this answer?” (3–5 minutes)

1) **Chat**
- Start a thread (left sidebar) and ask a recall-style question (e.g., “Do you remember when we discussed X?”).

2) **Why panel**
- Open the **Why** panel for the turn.
- Point out:
  - service verdict (PASS / ABSTAIN / CLARIFY / NO_MEMORY)
  - evidence summary + citations
  - evidence time window (when available)

3) **Open a cited message**
- Use a citation link or archive viewer action to jump to the cited evidence.

Note: citation tokens are `source_id#message_id`. When used in URLs, `#` must be encoded as `%23`.

## Part 3 — Trust controls (optional, 1–2 minutes)

- Disable an episode in **Episodes**, then re-ask a similar question and show the retrieval changes.
- Run **Health** checks and export diagnostics (no secrets) as a support bundle.

## If asked “what makes this different?”

- **Evidence is first-class** (no “memory” without provenance).
- **Episode-first recall** (events, not fragments).
- **Fail-closed verification** (abstain/clarify when support is weak).
- **Local-first** (works with local providers; cloud is optional).

