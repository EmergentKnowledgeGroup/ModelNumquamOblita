# Memory Visualization Spec — “Obsidian‑style” Graph (Practical, Not Excessive)

## 0) Goal

Ship a **high-clarity memory graph** that lets operators and builders:
- see how memories connect (events, evidence, entities, shared-language keys),
- debug “why did it retrieve that?” visually,
- spot conflicts/duplicates quickly,
- edit/disable safely without leaving the UI.

Target: Obsidian-like *feel* (global graph + local graph + filters + drilldown), but bounded, fast, and auditable.

## 1) Non‑negotiables

- **Performance**: remains responsive on typical local datasets; no “render 50k nodes” mode.
- **Bounded retrieval & privacy**: graph is a view over already-allowed memory surfaces; no bulk exfiltration.
- **Actionability**: every visual affordance maps to an operator action (inspect, explain, disable, propose edit).
- **Truthfulness**: labels reflect what the system actually knows (evidence vs episode vs derived/summary).

## 2) Iteration SOP (required)

For every codebase change while implementing this visualization:

**Pass 1 — targeted correctness**
- [ ] Implement one small UI/data item.
- [ ] Add targeted tests (data shaping + UI behavior for the change).
- [ ] Run targeted tests; fix to green.

**Pass 2 — regression + integration**
- [ ] Run full test suite (or best available).
- [ ] Run a UI smoke flow (load graph, select nodes, filter, focus, open details).
- [ ] Run a behavior smoke (routine chat unaffected; memory recall unchanged).

If Pass 2 fails, stop and fix before proceeding.

## 3) User experience (what it must feel like)

### 3.1 Two graph modes

1) **Global Graph**
- shows a bounded snapshot across memory, suitable for exploration.
- optimized for pattern finding (clusters, hubs, conflicts).

2) **Local Graph**
- centered on a selected node (episode/atom/entity/key).
- shows neighbors to a configurable depth (default 1).
- optimized for “why did this connect?” debugging.

### 3.2 Core interactions

- Pan + zoom (trackpad/mouse).
- Click to select; shift-click to multi-select.
- “Focus selected” (center + re-layout around selection).
- Expand neighbors (incremental, bounded).
- Search box (typeahead; jump to node).
- Filters:
  - node type (episodes / evidence atoms / entities / shared-language keys / tags)
  - status (active/disabled/conflicted)
  - time window (slider or presets)
  - confidence threshold (hide low-signal links)
- Edge legend and toggles (conflict links on/off, shared-language on/off, etc.).

### 3.3 Operator actions from graph

From a node detail panel:
- View plain-language “what this is” summary.
- View provenance (evidence references) for anything that can be cited.
- Open “Why this answer?” context when the node is connected to a selected turn.
- Safe actions:
  - disable/enable episode
  - propose edit to title/summary/tags (proposal-based where appropriate)
  - mark conflict / add operator note
  - undo last change (scoped)

## 4) Visual language (simple, distinctive, readable)

### 4.1 Node styles (examples)

- Episodes: larger nodes; distinct color; icon-like glyph.
- Evidence atoms: smaller nodes; neutral color; status ring.
- Entities: medium nodes; label-first; grouped by type (person/org/place).
- Shared-language keys: key-shaped glyph; edges show anchor evidence.
- Conflicted items: warning ring; conflict edges highlighted.

### 4.2 Edge styles

- Episode→Evidence: “supports” (solid).
- Evidence↔Evidence: “constellation / co-occurrence” (thin).
- Conflict: high-contrast dashed (always visible by default).
- Shared-language: dotted with key-color.

All visuals must degrade gracefully when labels are hidden at zoomed-out levels.

## 5) Data model (what the UI needs)

### 5.1 Node types

Minimum node types to support:
- `episode`
- `atom` (evidence)
- `entity`
- `tag`
- `shared_language_key`

Each node must include:
- `id` (stable string)
- `type`
- `title` (short label)
- `subtitle` (optional)
- `status` (active/disabled/conflicted/etc.)
- `timestamp` or `time_range` (if applicable)
- `metrics` (optional: confidence, retrieval_weight, degree, etc.)

### 5.2 Link types

Minimum link types:
- `supports` (episode ↔ atom)
- `conflict` (atom ↔ atom or episode ↔ episode)
- `constellation` (related evidence)
- `narrative_arc` (time/sequence adjacency)
- `shared_language` (atom ↔ key)
- `tagged_with` (node ↔ tag)
- `mentions` (node ↔ entity)

Each link must include:
- `source_id`
- `target_id`
- `type`
- `weight` (0..1)
- `explain` (short “why this link exists” string)

### 5.3 Bounding rules (hard caps)

To keep the graph practical:
- Global graph cap: `N_nodes <= 600`, `N_links <= 1400` (configurable, but bounded).
- Local graph cap: `N_nodes <= 240`, `N_links <= 600`.
- Any “expand” action must check caps and return a partial result with `truncated=true`.

The UI must visibly indicate truncation and offer narrowing filters, not “load more forever”.

## 6) API/contract surface (client‑agnostic)

Expose two data surfaces:

1) **Graph snapshot**
- returns a bounded set of nodes + links for global view
- supports filters (query text, type/status/time window, contradiction toggle)
- includes `total_estimate` and `truncated` flags

2) **Graph neighborhood**
- returns neighbors/links for a specific node id
- supports `depth` and `limit`
- includes `truncated` flags and a “next suggested filters” hint

Also expose:
- **Node detail** (episode/atom/entity/key)
- **Action endpoints** (enable/disable/edit via proposals)

## 7) UX layout (wireframe)

```text
┌───────────────────────────────────────────────────────────────┐
│ Search [___________]  Type [v]  Status [v]  Time [---|---]    │
├───────────────┬───────────────────────────────┬───────────────┤
│ Filters/Legend│            Graph               │ Details       │
│ - toggles     │  (pan/zoom/select/expand)     │ - summary     │
│ - caps        │                               │ - provenance  │
│ - truncation  │                               │ - links       │
│               │                               │ - safe actions│
└───────────────┴───────────────────────────────┴───────────────┘
```

## 8) Acceptance criteria (what “done” means)

### 8.1 Usability
- A non-technical operator can:
  - find an episode by search,
  - see its connected evidence,
  - disable it,
  - confirm it stops appearing in retrieval,
  - undo the change.

### 8.2 Debuggability
- For any selected node, the detail panel can answer:
  - what it represents,
  - why it is connected to its neighbors,
  - which evidence anchors it (when applicable).

### 8.3 Performance
- Graph renders within a conversational budget on typical datasets.
- Expansions never block the UI indefinitely; they stream/step or show progress.

### 8.4 Safety
- No UI action silently mutates memory; mutation always requires an explicit operator action.
- The graph view cannot enumerate the full store without narrowing filters.

## 9) Implementation phases (practical order)

### Phase 0 — “Make the current map solid”
- [ ] Add pan/zoom, selection, focus, and truncation UX.
- [ ] Add clear node/edge legend and type/status filters.
- [ ] Add node detail panel that explains link reasons.
- [ ] Add tests for bounding and truncation behavior.

### Phase 1 — Local graph mode
- [ ] Add “Local graph” toggle and depth selector.
- [ ] Implement incremental neighbor expansion with caps.
- [ ] Add a “path highlight” feature (selected → neighbor chain).

### Phase 2 — Obsidian-like polish
- [ ] Cluster/communities view (optional toggle).
- [ ] Label scaling by zoom + hover tooltips.
- [ ] Mini-map or breadcrumbs (“you are here”).
- [ ] Saved filters (“views”) for common operator tasks.

### Phase 3 — Action integration (safe mutations)
- [ ] From detail panel: disable/enable, propose edit, mark conflict.
- [ ] Add undo + audit readout for visual changes.
- [ ] Add regression tests to ensure chat behavior is unchanged by visualization changes.

### Phase 4 — Export + share
- [ ] Export current view (image + JSON snapshot).
- [ ] Export a minimal support bundle for a selected problematic node cluster.

## 10) Test plan (must ship with the feature)

- Unit tests:
  - bounding rules and truncation flags
  - filter semantics and default caps
- Integration tests:
  - graph snapshot loads; selecting a node loads details
  - disabling an episode updates graph and retrieval eligibility
- Performance regression:
  - graph render time under cap stays below target threshold

