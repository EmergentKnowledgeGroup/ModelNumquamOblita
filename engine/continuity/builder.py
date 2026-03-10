from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable

from ..memory import MemoryAtom
from .model import Constellation, ContinuitySnapshot, DynamicPattern, NarrativeArc, SharedLanguageKey

_POSITIVE_TERMS = {
    "accept",
    "alive",
    "calm",
    "clear",
    "connected",
    "grateful",
    "grounded",
    "hope",
    "joy",
    "love",
    "open",
    "peace",
    "safe",
    "steady",
    "trust",
}
_NEGATIVE_TERMS = {
    "afraid",
    "anxious",
    "avoid",
    "confused",
    "crash",
    "doubt",
    "fear",
    "lost",
    "panic",
    "stuck",
    "tense",
    "uncertain",
    "worry",
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "we",
    "with",
    "you",
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _hash_id(prefix: str, payload: str) -> str:
    return f"{prefix}_{sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _tokenize(text: str) -> list[str]:
    tokens = []
    current = []
    for char in text.lower():
        if char.isalnum() or char == "'":
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _normalized(values: Iterable[str]) -> list[str]:
    return sorted({item.strip().lower() for item in values if item and item.strip()})


def _atom_timestamp(atom: MemoryAtom) -> datetime:
    timestamps = [ref.timestamp for ref in atom.source_refs if ref.timestamp is not None]
    if timestamps:
        return min(timestamps)
    return atom.updated_at


def _atom_sessions(atom: MemoryAtom) -> set[str]:
    sessions = {ref.source_id.strip().lower() for ref in atom.source_refs if ref.source_id and ref.source_id.strip()}
    return sessions or {"unknown"}


class ContinuityBuilder:
    """Derive continuity-layer objects from source-backed memory atoms."""

    def build(
        self,
        atoms: Iterable[MemoryAtom],
        *,
        now: datetime | None = None,
        shared_language_keys: Iterable[SharedLanguageKey] | None = None,
    ) -> ContinuitySnapshot:
        atom_list = [atom for atom in atoms if atom.canonical_text.strip()]
        as_of = now or datetime.now(timezone.utc)
        derived_keys = self._shared_language_keys(atom_list)
        if shared_language_keys:
            derived_keys = self._merge_shared_language_keys(derived_keys, list(shared_language_keys))
        return ContinuitySnapshot(
            generated_at=as_of,
            dynamic_patterns=self._dynamic_patterns(atom_list),
            constellations=self._constellations(atom_list),
            narrative_arcs=self._narrative_arcs(atom_list),
            shared_language_keys=derived_keys,
        )

    def _dynamic_patterns(self, atoms: list[MemoryAtom]) -> list[DynamicPattern]:
        buckets: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"atom_ids": set(), "sessions": set()})
        for atom in atoms:
            tokens = [token for token in _tokenize(atom.canonical_text) if token not in _STOPWORDS and len(token) >= 3]
            if len(tokens) < 2:
                continue
            signature = " ".join(tokens[:2])
            bucket = buckets[signature]
            bucket["atom_ids"].add(atom.atom_id)
            bucket["sessions"].update(_atom_sessions(atom))

        patterns: list[DynamicPattern] = []
        for signature, bucket in buckets.items():
            atom_ids = sorted(bucket["atom_ids"])
            sessions = bucket["sessions"]
            if len(atom_ids) < 3:
                continue
            if len(sessions) < 3 and len(atom_ids) < 4:
                continue
            confidence = _clamp01(min(len(atom_ids), 6) / 6.0 * 0.55 + min(len(sessions), 4) / 4.0 * 0.45)
            patterns.append(
                DynamicPattern(
                    pattern_id=_hash_id("dp", signature),
                    signature=signature,
                    atom_ids=atom_ids,
                    support_count=len(atom_ids),
                    confidence=confidence,
                )
            )
        patterns.sort(key=lambda item: (item.support_count, item.confidence), reverse=True)
        return patterns[:48]

    def _constellations(self, atoms: list[MemoryAtom]) -> list[Constellation]:
        clusters: dict[tuple[str, str, int], list[MemoryAtom]] = defaultdict(list)
        window_seconds = 30 * 60
        for atom in atoms:
            ts = _atom_timestamp(atom)
            bucket = int(ts.timestamp() // window_seconds)
            topics = _normalized(atom.topics) or ["untagged"]
            entities = _normalized(atom.entities) or ["general"]
            for topic in topics:
                for entity in entities:
                    clusters[(topic, entity, bucket)].append(atom)

        merged: dict[tuple[str, tuple[str, ...]], Constellation] = {}
        for (topic, entity, _bucket), members in clusters.items():
            unique_ids = sorted({atom.atom_id for atom in members})
            if len(unique_ids) < 2:
                continue
            timestamps = [_atom_timestamp(atom) for atom in members]
            start_at = min(timestamps)
            end_at = max(timestamps)
            duration_minutes = max((end_at - start_at).total_seconds() / 60.0, 0.0)
            temporal_density = _clamp01(1.0 / (1.0 + duration_minutes / 90.0))
            avg_salience = sum(atom.salience for atom in members) / max(len(members), 1)
            support_signal = _clamp01(sum(max(1, atom.support_count) for atom in members) / (len(members) * 4.0))
            strength = _clamp01(avg_salience * 0.45 + support_signal * 0.25 + temporal_density * 0.30)
            key = (topic, tuple(unique_ids))
            candidate = Constellation(
                constellation_id=_hash_id("cs", f"{topic}|{entity}|{','.join(unique_ids)}"),
                topic=topic,
                atom_ids=unique_ids,
                strength=strength,
                entities=[entity],
                start_at=start_at,
                end_at=end_at,
            )
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
            else:
                existing.entities = sorted(set(existing.entities).union(set(candidate.entities)))
                existing.strength = max(existing.strength, candidate.strength)
                if existing.start_at is None or (candidate.start_at and candidate.start_at < existing.start_at):
                    existing.start_at = candidate.start_at
                if existing.end_at is None or (candidate.end_at and candidate.end_at > existing.end_at):
                    existing.end_at = candidate.end_at

        constellations = list(merged.values())
        constellations.sort(key=lambda item: (item.strength, len(item.atom_ids)), reverse=True)
        return constellations[:64]

    def _narrative_arcs(self, atoms: list[MemoryAtom]) -> list[NarrativeArc]:
        by_entity_topic: dict[tuple[str, str], list[MemoryAtom]] = defaultdict(list)
        for atom in atoms:
            entities = _normalized(atom.entities)
            topics = _normalized(atom.topics)
            if not entities or not topics:
                continue
            for entity in entities:
                for topic in topics:
                    by_entity_topic[(entity, topic)].append(atom)

        arcs: list[NarrativeArc] = []
        for (entity, topic), members in by_entity_topic.items():
            ordered = sorted(members, key=_atom_timestamp)
            unique_ids: list[str] = []
            unique_atoms: list[MemoryAtom] = []
            seen_ids: set[str] = set()
            for atom in ordered:
                if atom.atom_id in seen_ids:
                    continue
                seen_ids.add(atom.atom_id)
                unique_ids.append(atom.atom_id)
                unique_atoms.append(atom)
            if len(unique_ids) < 3:
                continue

            start_at = _atom_timestamp(unique_atoms[0])
            end_at = _atom_timestamp(unique_atoms[-1])
            if end_at <= start_at:
                continue

            first_valence = self._text_valence(unique_atoms[0].canonical_text)
            last_valence = self._text_valence(unique_atoms[-1].canonical_text)
            valence_delta = last_valence - first_valence
            if abs(valence_delta) < 0.18:
                continue

            confidence = _clamp01(min(len(unique_ids), 8) / 8.0 * 0.60 + min(abs(valence_delta), 1.0) * 0.40)
            arcs.append(
                NarrativeArc(
                    arc_id=_hash_id("arc", f"{entity}|{topic}|{','.join(unique_ids)}"),
                    entity=entity,
                    topic=topic,
                    atom_ids=unique_ids,
                    start_at=start_at,
                    end_at=end_at,
                    confidence=confidence,
                    valence_delta=round(valence_delta, 4),
                )
            )
        arcs.sort(key=lambda item: (item.confidence, abs(item.valence_delta)), reverse=True)
        return arcs[:48]

    def _shared_language_keys(self, atoms: list[MemoryAtom]) -> list[SharedLanguageKey]:
        phrase_atoms: dict[str, list[str]] = defaultdict(list)
        for atom in atoms:
            text = atom.canonical_text.strip()
            if len(text) < 6 or len(text) > 120:
                continue
            if atom.salience < 0.55 and atom.support_count < 2:
                continue
            effective_support = max(atom.support_count, len(atom.source_refs))
            phrase_atoms[text.lower()].extend([atom.atom_id] * effective_support)

        keys: list[SharedLanguageKey] = []
        for phrase, atom_ids in phrase_atoms.items():
            support_count = len(atom_ids)
            if support_count < 2:
                continue
            weight = _clamp01(0.45 + min(support_count, 5) * 0.1)
            keys.append(
                SharedLanguageKey(
                    key_id=_hash_id("slk", phrase),
                    phrase=phrase,
                    atom_ids=sorted(set(atom_ids)),
                    support_count=support_count,
                    weight=weight,
                    aliases=[],
                    domains=["derived"],
                    confidence=min(0.95, 0.55 + min(support_count, 6) * 0.06),
                    curated=False,
                )
            )
        keys.sort(key=lambda item: (item.weight, item.support_count), reverse=True)
        return keys[:48]

    def _merge_shared_language_keys(
        self,
        derived: list[SharedLanguageKey],
        curated: list[SharedLanguageKey],
    ) -> list[SharedLanguageKey]:
        by_phrase = {key.phrase.strip().lower(): key for key in derived if key.phrase.strip()}
        for key in curated:
            phrase = key.phrase.strip().lower()
            if not phrase:
                continue
            existing = by_phrase.get(phrase)
            if existing is None:
                by_phrase[phrase] = key
                continue
            merged_atom_ids = sorted(set(existing.atom_ids).union(set(key.atom_ids)))
            existing.atom_ids = merged_atom_ids
            existing.support_count = max(existing.support_count, key.support_count)
            existing.weight = max(existing.weight, key.weight)
            existing.confidence = max(existing.confidence, key.confidence)
            existing.curated = existing.curated or key.curated
            existing.aliases = sorted(set(existing.aliases).union(set(key.aliases)))
            existing.domains = sorted(set(existing.domains).union(set(key.domains)))
        merged = list(by_phrase.values())
        merged.sort(key=lambda item: (item.weight, item.support_count), reverse=True)
        return merged[:48]

    def _text_valence(self, text: str) -> float:
        tokens = _tokenize(text)
        if not tokens:
            return 0.0
        positive = sum(1 for token in tokens if token in _POSITIVE_TERMS)
        negative = sum(1 for token in tokens if token in _NEGATIVE_TERMS)
        if positive == 0 and negative == 0:
            return 0.0
        return _clamp01((positive / max(len(tokens), 1)) * 3.0) - _clamp01((negative / max(len(tokens), 1)) * 3.0)
