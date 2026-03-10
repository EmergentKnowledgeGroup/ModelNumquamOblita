# Data Model and Storage

## 1. Memory atom schema

```json
{
  "atom_id": "mem_...",
  "type": "episodic|semantic|relational|affective|procedural_style",
  "canonical_text": "string",
  "status": "active|superseded|conflicted|archived",
  "confidence": 0.0,
  "salience": 0.0,
  "salience_half_life_days": 180,
  "last_reinforced_at": "iso8601|null",
  "support_count": 0,
  "contradiction_count": 0,
  "first_seen_at": "iso8601",
  "last_seen_at": "iso8601",
  "time_range": {"start": "iso8601|null", "end": "iso8601|null"},
  "entities": ["..."],
  "topics": ["..."],
  "affect": {"valence": -1.0, "intensity": 0.0},
  "source_refs": [
    {
      "source_id": "conversation_or_doc_id",
      "message_id": "optional",
      "timestamp": "iso8601|null",
      "span": {"start": 0, "end": 0}
    }
  ],
  "version_of": "atom_id|null",
  "tombstoned_at": "iso8601|null",
  "tombstone_reason": "string|null",
  "pending_mutation_request_id": "mut_...|null",
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

## 2. Supporting stores

### Episodic ledger
- append-focused event memory atoms.
- optimized for temporal and narrative reconstruction.

### Semantic identity store
- stable abstractions from repeated episodes.
- optimized for consistency and fast retrieval.

### Relationship graph
- nodes: entities, topics, anchors.
- edges: co-occurrence, causality, affinity, contradiction.

### Provenance ledger
- immutable log of writes/updates/merges/conflicts.

### Mutation request queue
- human-review queue for `PROPOSE_EDIT` and `PROPOSE_DELETE`.
- required fields:
  - request id,
  - target atom(s),
  - proposer (`model|user|system`),
  - rationale + evidence refs,
  - decision (`approved|rejected`),
  - approver identity + timestamp.

## 3. Derived continuity objects (V3)

### Dynamic pattern

```json
{
  "pattern_id": "dyn_...",
  "label": "tease_reflect_repair",
  "sequence_signature": ["tease", "deflect", "repair", "warmth"],
  "participants": ["user", "assistant"],
  "support_atom_ids": ["mem_..."],
  "confidence": 0.0,
  "last_observed_at": "iso8601"
}
```

### Constellation

```json
{
  "constellation_id": "con_...",
  "title": "hammer_absurdity_arc",
  "atom_ids": ["mem_..."],
  "themes": ["identity", "humor", "philosophy"],
  "affective_profile": {"valence": 0.0, "intensity": 0.0},
  "time_span": {"start": "iso8601", "end": "iso8601"},
  "strength": 0.0
}
```

### Narrative arc

```json
{
  "arc_id": "arc_...",
  "domain": "identity_confidence",
  "states": [
    {"at": "iso8601", "state": "fear_of_loss"},
    {"at": "iso8601", "state": "defiant_acceptance"}
  ],
  "bridging_events": ["mem_..."],
  "confidence": 0.0
}
```

### Shared language key

```json
{
  "key_id": "slk_...",
  "phrase": "sad hammer noises",
  "origin_atom_id": "mem_...",
  "constellation_id": "con_...",
  "identity_weight": 0.0,
  "last_triggered_at": "iso8601|null"
}
```

### Recognition event

```json
{
  "recognition_id": "rec_...",
  "query_id": "qry_...",
  "selected_atom_ids": ["mem_..."],
  "signal": "strong|weak|none",
  "score": 0.0,
  "captured_at": "iso8601"
}
```

## 4. Indexes

- lexical full-text index on `canonical_text`.
- vector index on atom embeddings.
- time index (`first_seen_at`, `last_seen_at`, `time_range`).
- graph adjacency index for relation expansion.
- composite index on `(type, status, confidence)`.
- constellation index on `themes`, `atom_ids`, and `strength`.
- narrative index on `domain` + temporal sequence.
- shared-language index on exact phrase and normalized variants.

## 5. Scale strategy

- partition by user/mirror id.
- incremental indexing for new atoms only.
- hot cache for recent and high-confidence atoms.
- background compaction and archival of low-value atoms.
- derived continuity refresh in async jobs to avoid online latency spikes.

## 6. Storage invariants

1. no atom without `source_refs`.
2. no destructive overwrite of conflicting information.
3. confidence updates must be monotonic with evidence quality policy.
4. archived atoms remain addressable for audit.
5. derived continuity objects cannot override source-atom truth authority.
6. no autonomous hard delete; destructive changes require approved mutation request.
7. tombstone transitions preserve provenance unless user explicitly requests immediate erase.
