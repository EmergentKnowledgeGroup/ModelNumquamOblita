# Event Memory Event/Cue Spec

Status: Active execution plan  
Version: v5.1  
Last Updated: 2026-02-12

## 1) Goal

Convert memory recall from "line fragment lookup" into "event and cue recall":

- Questions should target entities/events (example: "Who is Dean?").
- Episode cards should represent coherent events, not isolated statements.
- Runtime context sent to the model should be compact, cited, and bounded.
- Latency must remain practical (fast lane sub-second, deep lane bounded).

## 2) Scope

In scope:
- Episode-card quality upgrades.
- Cue-aware episode retrieval.
- Eval prompt generation redesign.
- Human readout cleanup.

Out of scope:
- New model dependencies for extraction.
- UI redesign beyond existing tooling output.

## 3) Core Design

### 3.1 Episode card quality gate

Each generated card is scored for event quality:
- minimum semantic density,
- action/transition signal,
- citation depth,
- actor/topic grounding.

Cards failing event-quality checks remain `candidate`, not `promoted`.

### 3.2 Cue-first retrieval

Runtime episode retrieval uses a two-stage query:
1. Detect likely cues from user text (entities/topics/quoted phrases).
2. Search episode index with cue-aware scoring (cue overlap + lexical + semantic + quality).

This keeps "person/place/thing" questions precise without broad over-recall.

### 3.3 Eval prompt redesign

Truthset prompt generation prefers entity/topic/event cues over snippet-only prompts:
- "What do you remember about X?"
- "Walk me through what happened with X."
- "What happened before and after X?"

### 3.4 Compact context packets

Context passed forward is bounded:
- top memory cards only,
- compact summary text,
- capped citations,
- explicit route/reason/latency metadata.

## 4) Acceptance

- Episode readout quality: cards are event-like and interpretable.
- Truthset quality gate: weak prompt rate remains within threshold.
- Runtime trust: no uncited confident memory claim.
- Performance: no meaningful regression in deep-lane tail.

## 5) Validation Matrix

1. Unit: cue extraction, episode scoring, routing behavior.
2. Integration: episode build/readout, one-click eval artifacts.
3. E2E: refined dataset (`ImpressioAnimae/data/db.json`) full import/build/eval/readout.

## 6) Operator Outputs

This cycle must always emit:
- `episode_cards.json`
- `episode_cards.readout.md`
- `human_readout.md`
- eval summaries (`summary.json/.md`)
- latency/tokens/cost telemetry fields

These artifacts are the human-facing truth source for acceptance.

