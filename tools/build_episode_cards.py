#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.memory import SqliteAtomStore
from engine.memory.store import AtomStatus, MemoryAtom
from engine.runtime import load_inmemory_store_from_json

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_CLAUSE_SPLIT_RE = re.compile(r"[.\n!?;:]+")
_CUE_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-']+")
_GENERIC_WORDS = {
    "about",
    "again",
    "also",
    "and",
    "because",
    "been",
    "before",
    "could",
    "from",
    "have",
    "just",
    "like",
    "more",
    "only",
    "that",
    "there",
    "these",
    "this",
    "thing",
    "very",
    "what",
    "when",
    "where",
    "with",
    "would",
    "your",
}
_CUE_STOPWORDS = _GENERIC_WORDS.union(
    {
        "remember",
        "recall",
        "memory",
        "detail",
        "happened",
        "happen",
        "before",
        "after",
    }
)
_ACTION_HINTS = {
    "agreed",
    "asked",
    "built",
    "changed",
    "chose",
    "confirmed",
    "created",
    "decided",
    "defined",
    "discussed",
    "fixed",
    "found",
    "implemented",
    "launched",
    "planned",
    "reviewed",
    "shipped",
    "started",
    "switched",
    "updated",
}
_CARD_TOPIC_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("memory", "memory"),
    ("remember", "memory"),
    ("continuity", "continuity"),
    ("constitution", "continuity"),
    ("identity", "identity"),
    ("sentient", "identity"),
    ("anchor", "anchors"),
    ("prompt", "prompting"),
    ("systemprompt", "prompting"),
    ("test", "testing"),
    ("benchmark", "testing"),
    ("eval", "evaluation"),
    ("project", "project"),
    ("pipeline", "pipeline"),
)
_TRANSITION_HINTS = {
    "after",
    "before",
    "then",
    "later",
    "next",
    "finally",
    "eventually",
    "during",
    "while",
}
_ROLE_HINT_PRIORITY = ("assistant", "developer", "system", "tool", "user")


@dataclass(slots=True)
class _AtomEvidence:
    atom: MemoryAtom
    source_id: str
    day_key: str
    domain: str
    timestamp: datetime
    message_ids: list[str]
    citations: list[str]
    signal_score: float
    role_hint: str
    topic_tags: set[str]
    lexical_tokens: set[str]
    meaningful_token_count: int


@dataclass(slots=True)
class _Cluster:
    source_id: str
    day_key: str
    entries: list[_AtomEvidence]


@dataclass(slots=True)
class _BuilderProfile:
    profile_id: str
    include_entities: dict[str, str]
    exclude_entities: set[str]
    alias_lookup: dict[str, str]
    cue_include: list[str]
    cue_exclude: set[str]
    domain_rules: list[dict[str, Any]]



def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _coerce_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _compact_text(text: str, *, max_chars: int = 180) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _tokenize(text: str) -> list[str]:
    return [item.lower() for item in _WORD_RE.findall(str(text or ""))]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_list(value: Any, *, max_items: int = 256, max_chars: int = 160) -> list[str]:
    if isinstance(value, str):
        rows = [item.strip() for item in value.replace("\n", ",").split(",")]
    elif isinstance(value, list):
        rows = [str(item).strip() for item in value]
    else:
        rows = []
    out: list[str] = []
    seen: set[str] = set()
    for item in rows:
        if not item:
            continue
        cleaned = item[:max_chars].strip()
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
        if len(out) >= max_items:
            break
    return out


def _load_builder_profile(path: Path) -> _BuilderProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("builder profile payload must be a JSON object")

    entities_entries = payload.get("entities")
    include_entities: dict[str, str] = {}
    exclude_entities: set[str] = set()
    alias_lookup: dict[str, str] = {}
    if isinstance(entities_entries, list):
        for row in entities_entries:
            if not isinstance(row, dict):
                continue
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            status = str(row.get("status") or "include").strip().lower() or "include"
            value_key = value.lower()
            if status == "exclude":
                exclude_entities.add(value_key)
            else:
                include_entities[value_key] = value
            for alias in _normalize_list(row.get("aliases"), max_items=24, max_chars=80):
                alias_lookup[alias.lower()] = value
    else:
        entities_legacy = payload.get("entities_legacy")
        if isinstance(entities_legacy, dict):
            for item in _normalize_list(entities_legacy.get("include"), max_items=200, max_chars=120):
                include_entities[item.lower()] = item
            for item in _normalize_list(entities_legacy.get("exclude"), max_items=200, max_chars=120):
                exclude_entities.add(item.lower())
            for row in list(entities_legacy.get("aliases") or []):
                if not isinstance(row, dict):
                    continue
                alias = str(row.get("alias") or "").strip()
                canonical = str(row.get("canonical") or "").strip()
                if alias and canonical:
                    alias_lookup[alias.lower()] = canonical

    cue_include: list[str] = []
    cue_exclude: set[str] = set()
    cue_entries = payload.get("cue_phrases")
    if isinstance(cue_entries, list):
        for row in cue_entries:
            if not isinstance(row, dict):
                continue
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            status = str(row.get("status") or "include").strip().lower() or "include"
            if status == "exclude":
                cue_exclude.add(value.lower())
            else:
                cue_include.append(value)
    else:
        cues_legacy = payload.get("cues_legacy")
        if isinstance(cues_legacy, dict):
            cue_include.extend(_normalize_list(cues_legacy.get("include"), max_items=200, max_chars=120))
            cue_exclude.update(item.lower() for item in _normalize_list(cues_legacy.get("exclude"), max_items=200, max_chars=120))

    domain_rules_payload = payload.get("domain_rules")
    domain_rules: list[dict[str, Any]] = []
    if isinstance(domain_rules_payload, list):
        for row in domain_rules_payload:
            if not isinstance(row, dict):
                continue
            pattern = str(row.get("pattern") or "").strip()
            if not pattern:
                continue
            domain = str(row.get("domain") or "general").strip() or "general"
            status = str(row.get("status") or "include").strip().lower() or "include"
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue
            domain_rules.append(
                {
                    "pattern": pattern,
                    "domain": domain,
                    "status": status,
                    "compiled": compiled,
                }
            )

    return _BuilderProfile(
        profile_id=str(payload.get("profile_id") or path.stem),
        include_entities=include_entities,
        exclude_entities=exclude_entities,
        alias_lookup=alias_lookup,
        cue_include=_normalize_list(cue_include, max_items=200, max_chars=120),
        cue_exclude={item.lower() for item in cue_exclude},
        domain_rules=domain_rules,
    )


def _apply_aliases(text: str, alias_lookup: dict[str, str]) -> str:
    out = str(text or "")
    for alias, canonical in list(alias_lookup.items()):
        if not alias or not canonical:
            continue
        out = re.sub(rf"\\b{re.escape(alias)}\\b", canonical, out, flags=re.IGNORECASE)
    return out


def _meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in _tokenize(text)
        if len(token) >= 4 and token not in _GENERIC_WORDS
    ]


def _looks_low_information(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    tokens = _tokenize(value)
    if len(tokens) < 8:
        return True
    meaningful = _meaningful_tokens(value)
    if len(meaningful) < 3:
        return True
    density = len(meaningful) / max(1, len(tokens))
    if density < 0.25:
        return True
    lowered = value.lower().strip(" .!?")
    if lowered in {
        "ok",
        "okay",
        "thanks",
        "thank you",
        "sounds good",
        "go ahead",
        "yes",
        "yep",
        "sure",
    }:
        return True
    return False


def _best_clause(text: str, *, max_words: int = 14) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    clauses = [
        re.sub(r"\s+", " ", piece).strip("`\"'[]{}() ")
        for piece in _CLAUSE_SPLIT_RE.split(raw)
    ]
    clauses = [item for item in clauses if item]
    if not clauses:
        return ""
    ranked = sorted(
        clauses,
        key=lambda piece: (
            len(_meaningful_tokens(piece)),
            len(_tokenize(piece)),
        ),
        reverse=True,
    )
    best = ranked[0]
    words = [item for item in best.split() if item]
    if not words:
        return ""
    return " ".join(words[:max_words])


def _norm_source_id(atom: MemoryAtom) -> str:
    refs = list(getattr(atom, "source_refs", []) or [])
    for ref in refs:
        source_id = str(getattr(ref, "source_id", "") or "").strip()
        if source_id:
            return source_id
    return "unknown_source"


def _norm_day_key(atom: MemoryAtom) -> str:
    refs = list(getattr(atom, "source_refs", []) or [])
    timestamps: list[datetime] = []
    for ref in refs:
        parsed = _coerce_dt(getattr(ref, "timestamp", None))
        if parsed is not None:
            timestamps.append(parsed)
    if timestamps:
        return min(timestamps).date().isoformat()
    created = _coerce_dt(getattr(atom, "created_at", None))
    if created is not None:
        return created.date().isoformat()
    return "unknown_date"


def _norm_domain(atom: MemoryAtom) -> str:
    topics = sorted(
        {
            str(item).strip().lower()
            for item in list(getattr(atom, "topics", []) or [])
            if str(item).strip()
        }
    )
    if topics:
        return topics[0]
    return str(getattr(atom, "atom_type", "episode")).strip().lower() or "episode"


def _role_hint(atom: MemoryAtom) -> str:
    entities = {
        str(item).strip().lower()
        for item in list(getattr(atom, "entities", []) or [])
        if str(item).strip()
    }
    for label in _ROLE_HINT_PRIORITY:
        if label in entities:
            return label
    return ""


def _episode_key(source_id: str, day_key: str, index: int) -> str:
    return f"{source_id}::{day_key}::{index:04d}"


def _episode_id_from_key(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:14]
    return f"ep_{digest}"


def _sort_key_for_atom(atom: MemoryAtom) -> tuple[float, float, int]:
    salience = float(getattr(atom, "salience", 0.0) or 0.0)
    confidence = float(getattr(atom, "confidence", 0.0) or 0.0)
    support = int(getattr(atom, "support_count", 0) or 0)
    return (salience, confidence, support)


def _build_citations(atoms: list[MemoryAtom]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for atom in atoms:
        for ref in list(getattr(atom, "source_refs", []) or []):
            source_id = str(getattr(ref, "source_id", "") or "").strip()
            message_id = str(getattr(ref, "message_id", "") or "").strip()
            if not source_id:
                continue
            citation = source_id if not message_id else f"{source_id}#{message_id}"
            if citation in seen:
                continue
            seen.add(citation)
            merged.append(citation)
    return merged


def _build_entities(atoms: list[MemoryAtom]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for atom in atoms:
        for entity in list(getattr(atom, "entities", []) or []):
            clean = str(entity).strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(clean)
            if len(values) >= 24:
                return values
    return values


def _build_topics(atoms: list[MemoryAtom]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for atom in atoms:
        for topic in list(getattr(atom, "topics", []) or []):
            clean = str(topic).strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(clean)
            if len(values) >= 24:
                return values
    return values


def _refine_topics(title: str, summary: str, topics: list[str]) -> list[str]:
    clean_topics = [str(topic).strip() for topic in list(topics or []) if str(topic).strip()]
    non_general = [topic for topic in clean_topics if topic.lower() != "general"]
    if non_general:
        return clean_topics
    text_blob = f"{title} {summary}".lower()
    inferred: list[str] = []
    seen: set[str] = set()
    for keyword, topic in _CARD_TOPIC_KEYWORDS:
        if keyword not in text_blob:
            continue
        if topic in seen:
            continue
        seen.add(topic)
        inferred.append(topic)
        if len(inferred) >= 3:
            break
    if inferred:
        return inferred
    return clean_topics or ["general"]


def _build_time_bounds(atoms: list[MemoryAtom]) -> tuple[str, str]:
    timestamps: list[datetime] = []
    for atom in atoms:
        for ref in list(getattr(atom, "source_refs", []) or []):
            parsed = _coerce_dt(getattr(ref, "timestamp", None))
            if parsed is not None:
                timestamps.append(parsed)
    if not timestamps:
        return ("", "")
    start = min(timestamps).isoformat()
    end = max(timestamps).isoformat()
    return (start, end)


def _message_ids(atom: MemoryAtom) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for ref in list(getattr(atom, "source_refs", []) or []):
        message_id = str(getattr(ref, "message_id", "") or "").strip()
        if not message_id or message_id in seen:
            continue
        seen.add(message_id)
        out.append(message_id)
    return out


def _event_signal_score(text: str) -> float:
    value = str(text or "").strip()
    if not value:
        return 0.0
    if _looks_low_information(value):
        return 0.0
    tokens = _tokenize(value)
    meaningful = _meaningful_tokens(value)
    action_hits = sum(1 for token in meaningful if token in _ACTION_HINTS)
    score = 0.0
    score += min(0.34, len(meaningful) * 0.04)
    score += min(0.30, len(tokens) * 0.015)
    score += min(0.26, action_hits * 0.13)
    if any(term in value.lower() for term in ("before", "after", "then", "later", "next", "finally")):
        score += 0.08
    if any(ch.isdigit() for ch in value):
        score += 0.04
    return max(0.0, min(1.0, score))


def _entry_timestamp(atom: MemoryAtom) -> datetime:
    values: list[datetime] = []
    for ref in list(getattr(atom, "source_refs", []) or []):
        parsed = _coerce_dt(getattr(ref, "timestamp", None))
        if parsed is not None:
            values.append(parsed)
    if values:
        return min(values)
    created = _coerce_dt(getattr(atom, "created_at", None))
    if created is not None:
        return created
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _entry_from_atom(atom: MemoryAtom) -> _AtomEvidence:
    source_id = _norm_source_id(atom)
    day_key = _norm_day_key(atom)
    domain = _norm_domain(atom)
    topic_tags = {
        str(item).strip().lower()
        for item in list(getattr(atom, "topics", []) or [])
        if str(item).strip()
    }
    text = str(getattr(atom, "canonical_text", "") or "")
    lexical_tokens = set(_meaningful_tokens(text))
    citations = _build_citations([atom])
    return _AtomEvidence(
        atom=atom,
        source_id=source_id,
        day_key=day_key,
        domain=domain,
        timestamp=_entry_timestamp(atom),
        message_ids=_message_ids(atom),
        citations=citations,
        signal_score=_event_signal_score(text),
        role_hint=_role_hint(atom),
        topic_tags=topic_tags,
        lexical_tokens=lexical_tokens,
        meaningful_token_count=len(lexical_tokens),
    )


def _is_topic_shift(previous: _AtomEvidence, current: _AtomEvidence) -> bool:
    if previous.topic_tags and current.topic_tags and previous.topic_tags.isdisjoint(current.topic_tags):
        return True
    prev_tokens = previous.lexical_tokens
    curr_tokens = current.lexical_tokens
    if len(prev_tokens) < 4 or len(curr_tokens) < 4:
        return False
    overlap = len(prev_tokens.intersection(curr_tokens))
    baseline = max(1, min(len(prev_tokens), len(curr_tokens)))
    return (overlap / baseline) < 0.15


def _cluster_entries(entries: list[_AtomEvidence], *, max_gap_minutes: int) -> list[_Cluster]:
    grouped: dict[tuple[str, str], list[_AtomEvidence]] = {}
    for entry in entries:
        grouped.setdefault((entry.source_id, entry.day_key), []).append(entry)

    clusters: list[_Cluster] = []
    max_gap_seconds = max(1, int(max_gap_minutes)) * 60
    for (source_id, day_key), rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item.timestamp)
        current: list[_AtomEvidence] = []
        for row in ordered:
            if not current:
                current = [row]
                continue
            last = current[-1]
            gap_s = max(0.0, (row.timestamp - last.timestamp).total_seconds())
            current_domain = str(last.domain or "").strip().lower()
            next_domain = str(row.domain or "").strip().lower()
            domain_unknown = (
                not current_domain
                or current_domain == "episode"
                or not next_domain
                or next_domain == "episode"
            )
            domain_overlap = current_domain == next_domain or domain_unknown
            speaker_transition = bool(last.role_hint and row.role_hint and last.role_hint != row.role_hint)
            topic_shift = _is_topic_shift(last, row)
            if gap_s <= max_gap_seconds and domain_overlap and (not topic_shift or speaker_transition):
                current.append(row)
            else:
                clusters.append(_Cluster(source_id=source_id, day_key=day_key, entries=current))
                current = [row]
        if current:
            clusters.append(_Cluster(source_id=source_id, day_key=day_key, entries=current))

    clusters.sort(
        key=lambda item: (
            item.source_id,
            item.day_key,
            item.entries[0].timestamp if item.entries else datetime(1970, 1, 1, tzinfo=timezone.utc),
        )
    )
    return clusters


def _build_title(atoms: list[MemoryAtom], domain: str) -> str:
    ranked = sorted(atoms, key=_sort_key_for_atom, reverse=True)
    for atom in ranked:
        cue = _best_clause(str(getattr(atom, "canonical_text", "") or ""), max_words=10)
        if cue and not _looks_low_information(cue):
            return cue
    fallback = domain.replace("_", " ").strip()
    return fallback.title() if fallback else "Episode"


def _normalize_summary_seed(text: str) -> str:
    return " ".join(_tokenize(text))


def _summary_duplicates_title(title: str, snippet: str) -> bool:
    title_seed = _normalize_summary_seed(title)
    snippet_seed = _normalize_summary_seed(snippet)
    if not title_seed or not snippet_seed:
        return False
    return snippet_seed == title_seed or snippet_seed.startswith(f"{title_seed} ")


def _trim_duplicate_title_prefix(title: str, summary: str) -> str:
    title_text = str(title or "").strip()
    summary_text = str(summary or "").strip()
    if not title_text or not summary_text:
        return summary_text
    if summary_text.casefold().startswith(title_text.casefold()):
        remainder = summary_text[len(title_text) :].lstrip(" \t\r\n|:;,.!?-–—")
        if remainder:
            return remainder
    return summary_text


def _build_episode_summary(atoms: list[MemoryAtom], *, title: str = "") -> str:
    ranked = sorted(atoms, key=_sort_key_for_atom, reverse=True)
    chronological = sorted(atoms, key=_entry_timestamp)
    lines: list[str] = []
    seen: set[str] = set()
    fallback_snippet = ""
    for atom in list(chronological[:2]) + list(ranked[:4]):
        snippet = _best_clause(str(getattr(atom, "canonical_text", "") or ""), max_words=18)
        if not snippet:
            continue
        if _summary_duplicates_title(title, snippet):
            if not fallback_snippet:
                fallback_snippet = _compact_text(snippet, max_chars=190)
            continue
        normalized = snippet.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        lines.append(_compact_text(snippet, max_chars=190))
        if len(lines) >= 3:
            break
    if not lines:
        for atom in ranked:
            snippet = _best_clause(str(getattr(atom, "canonical_text", "") or ""), max_words=22)
            trimmed = _trim_duplicate_title_prefix(title, snippet)
            if trimmed and not _summary_duplicates_title(title, trimmed):
                return _compact_text(trimmed, max_chars=190)
            if not fallback_snippet and snippet:
                fallback_snippet = _compact_text(snippet, max_chars=190)
        if fallback_snippet:
            return fallback_snippet
        return "No summary available."
    return " | ".join(lines)


def _cue_terms_from_values(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in _CUE_TOKEN_RE.findall(str(value or "")):
            cleaned = str(token).strip().lower()
            if len(cleaned) < 3:
                continue
            if cleaned in _CUE_STOPWORDS:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            terms.append(cleaned)
            if len(terms) >= 40:
                return terms
    return terms


def _contains_event_shape(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    tokens = _tokenize(lowered)
    if any(token in _ACTION_HINTS for token in tokens):
        return True
    if any(token in _TRANSITION_HINTS for token in tokens):
        return True
    if any(ch.isdigit() for ch in lowered):
        return True
    return False


def _quality_flags(
    *,
    summary: str,
    title: str,
    atom_count: int,
    evidence_strength: float,
    event_shape_score: float,
    anchor_strength: float,
    source_id: str,
    day_key: str,
    entities: list[str],
    topics: list[str],
    meaningful_token_count: int,
    min_meaningful_tokens: int,
) -> list[str]:
    flags: list[str] = []
    summary_tokens = _tokenize(summary)
    meaningful = _meaningful_tokens(summary)
    if len(summary_tokens) < 10 or len(meaningful) < 3:
        flags.append("low_information_summary")
    if meaningful_token_count < max(1, int(min_meaningful_tokens)):
        flags.append("low_meaningful_tokens")
    if (
        (not _contains_event_shape(summary) and not _contains_event_shape(title))
        or event_shape_score < 0.52
    ):
        flags.append("weak_event_shape")
    if atom_count < 2 and evidence_strength < 0.70:
        flags.append("single_atom_low_support")
    if not entities and not topics:
        flags.append("no_entity_topic_anchor")
    if anchor_strength < 0.34:
        flags.append("low_anchor_strength")
    if str(source_id or "").strip().lower() in {"", "unknown_source"}:
        flags.append("unknown_source_anchor")
    if str(day_key or "").strip().lower() in {"", "unknown_date"}:
        flags.append("unknown_day_anchor")
    if len(_tokenize(title)) < 3 and len(summary_tokens) < 14:
        flags.append("weak_question_seed_basis")
    return flags


def _question_seed(entities: list[str], topics: list[str], title: str, summary: str) -> str:
    day_token = ""
    for value in (title, summary):
        for token in _tokenize(value):
            if len(token) == 10 and token[:4].isdigit() and token[4] == "-" and token[7] == "-":
                day_token = token
                break
        if day_token:
            break
    if entities:
        if day_token:
            return f"What happened with {entities[0]} on {day_token}?"
        return f"What do you remember about {entities[0]}?"
    if topics:
        if day_token:
            return f"What happened around {topics[0]} on {day_token}?"
        return f"What do you remember about {topics[0]}?"
    cue = _best_clause(title or summary, max_words=12)
    if cue:
        return f"What do you remember about: {cue}?"
    return "What do you remember about this event?"


def _anchor_strength(
    *,
    entries: list[_AtomEvidence],
    entities: list[str],
    topics: list[str],
    citations: list[str],
    message_ids: list[str],
    day_key: str,
    source_id: str,
) -> float:
    score = 0.0
    score += min(0.22, len(entries) * 0.06)
    score += min(0.16, len(citations) * 0.04)
    score += min(0.16, len(message_ids) * 0.03)
    score += min(0.18, len(entities) * 0.07)
    score += min(0.12, len(topics) * 0.04)
    if str(day_key or "").strip().lower() not in {"", "unknown_date"}:
        score += 0.08
    if str(source_id or "").strip().lower() not in {"", "unknown_source"}:
        score += 0.08
    return _clamp01(score)


def _evidence_strength(entries: list[_AtomEvidence], citations: list[str]) -> float:
    if not entries:
        return 0.0
    avg_signal = sum(item.signal_score for item in entries) / max(1, len(entries))
    atom_component = min(len(entries), 6) / 6.0
    citation_component = min(len(citations), 6) / 6.0
    score = 0.35 * atom_component + 0.30 * citation_component + 0.35 * avg_signal
    return max(0.0, min(1.0, score))


def _event_window(entries: list[_AtomEvidence], citations: list[str], start_at: str, end_at: str) -> dict[str, Any]:
    message_ids: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        for message_id in entry.message_ids:
            if message_id in seen:
                continue
            seen.add(message_id)
            message_ids.append(message_id)
    return {
        "timestamp_start": start_at,
        "timestamp_end": end_at,
        "before": {
            "citation": citations[0] if citations else "",
            "message_ids": message_ids[:1],
        },
        "core": {
            "message_ids": message_ids[:12],
        },
        "after": {
            "citation": citations[-1] if citations else "",
            "message_ids": message_ids[-1:] if message_ids else [],
        },
        "start_at": start_at,
        "end_at": end_at,
        "before_anchor": citations[0] if citations else "",
        "after_anchor": citations[-1] if citations else "",
        "core_message_ids": message_ids[:12],
    }


def _fallback_cluster_time_bounds(entries: list[_AtomEvidence]) -> tuple[str, str]:
    if not entries:
        return ("", "")
    ordered = sorted(entries, key=lambda item: item.timestamp)
    return (ordered[0].timestamp.isoformat(), ordered[-1].timestamp.isoformat())


def _cluster_meaningful_token_count(entries: list[_AtomEvidence]) -> int:
    return sum(max(0, int(item.meaningful_token_count)) for item in entries)


def _reject_reasons(
    card: dict[str, Any],
    *,
    min_atoms: int,
    min_meaningful_tokens: int,
    min_evidence_strength: float,
) -> list[str]:
    reasons: list[str] = []
    atom_count = int(card.get("atom_count") or 0)
    meaningful_count = int(card.get("meaningful_token_count") or 0)
    evidence_strength = float(card.get("evidence_strength") or 0.0)
    if atom_count < max(1, int(min_atoms)):
        reasons.append("min_atoms_not_met")
    if meaningful_count < max(1, int(min_meaningful_tokens)):
        reasons.append("min_meaningful_tokens_not_met")
    if evidence_strength < float(min_evidence_strength):
        reasons.append("min_evidence_strength_not_met")
    for flag in list(card.get("quality_flags") or []):
        clean = str(flag).strip()
        if clean:
            reasons.append(f"quality_flag:{clean}")
    if not reasons:
        reasons.append("demoted_by_policy")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in reasons:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered


def _build_rejects_payload(
    *,
    cards: list[dict[str, Any]],
    source_cards: Path,
    min_atoms: int,
    min_meaningful_tokens: int,
    min_evidence_strength: float,
) -> dict[str, Any]:
    rejected: list[dict[str, Any]] = []
    for card in cards:
        status = str(card.get("promotion_status") or "").strip().lower()
        if status in {"promoted", "approved"}:
            continue
        rejected.append(
            {
                "episode_id": str(card.get("episode_id") or ""),
                "reasons": _reject_reasons(
                    card,
                    min_atoms=min_atoms,
                    min_meaningful_tokens=min_meaningful_tokens,
                    min_evidence_strength=min_evidence_strength,
                ),
                "quality_flags": [str(item).strip() for item in list(card.get("quality_flags") or []) if str(item).strip()],
                "key_fields_snapshot": {
                    "title": str(card.get("title") or ""),
                    "summary": str(card.get("summary") or ""),
                    "source_id": str(card.get("source_id") or ""),
                    "day_key": str(card.get("day_key") or ""),
                    "atom_count": int(card.get("atom_count") or 0),
                    "meaningful_token_count": int(card.get("meaningful_token_count") or 0),
                    "evidence_strength": float(card.get("evidence_strength") or 0.0),
                    "actors": list(card.get("actors") or []),
                    "topic_tags": list(card.get("topic_tags") or []),
                    "timestamp_start": str(card.get("timestamp_start") or ""),
                    "timestamp_end": str(card.get("timestamp_end") or ""),
                    "citations_count": int(card.get("citation_count") or 0),
                },
            }
        )
    return {
        "schema": "numquamoblita.episode_cards.rejects.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cards": str(source_cards),
        "rejected": rejected,
    }


def _build_cards(
    atoms: list[MemoryAtom],
    *,
    min_atoms: int = 2,
    max_gap_minutes: int = 45,
    min_meaningful_tokens: int = 30,
    min_evidence_strength: float = 0.35,
    allow_single_strong: bool = False,
    builder_profile: _BuilderProfile | None = None,
) -> list[dict[str, Any]]:
    entries = [_entry_from_atom(atom) for atom in atoms]
    clusters = _cluster_entries(entries, max_gap_minutes=max_gap_minutes)

    cards: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters):
        atoms_chrono = [item.atom for item in sorted(cluster.entries, key=lambda item: item.timestamp)]
        atoms_sorted = sorted([item.atom for item in cluster.entries], key=_sort_key_for_atom, reverse=True)
        citations = _build_citations(atoms_sorted)
        citations_chrono = _build_citations(atoms_chrono)
        start_at, end_at = _build_time_bounds(atoms_sorted)
        if not start_at or not end_at:
            start_at, end_at = _fallback_cluster_time_bounds(cluster.entries)
        confidence_values = [float(getattr(item, "confidence", 0.0) or 0.0) for item in atoms_sorted]
        confidence = round(sum(confidence_values) / max(1, len(confidence_values)), 4)
        salience_values = [float(getattr(item, "salience", 0.0) or 0.0) for item in atoms_sorted]
        salience_score = round(sum(salience_values) / max(1, len(salience_values)), 4)
        evidence_strength = round(_evidence_strength(cluster.entries, citations), 4)
        meaningful_token_count = _cluster_meaningful_token_count(cluster.entries)
        strong_single = (
            allow_single_strong
            and len(cluster.entries) == 1
            and evidence_strength >= 0.72
            and meaningful_token_count >= max(8, int(min_meaningful_tokens) // 2)
        )
        promoted = (
            len(cluster.entries) >= max(1, int(min_atoms))
            and evidence_strength >= float(min_evidence_strength)
            and meaningful_token_count >= max(1, int(min_meaningful_tokens))
        ) or strong_single
        title = _build_title(atoms_sorted, cluster.entries[0].domain if cluster.entries else "episode")
        summary = _build_episode_summary(atoms_sorted, title=title)
        entities = _build_entities(atoms_sorted)
        topics = _build_topics(atoms_sorted)
        topics = _refine_topics(title, summary, topics)
        if builder_profile is not None:
            title = _apply_aliases(title, builder_profile.alias_lookup)
            summary = _apply_aliases(summary, builder_profile.alias_lookup)
            normalized_entities: list[str] = []
            seen_entities: set[str] = set()
            for value in list(entities or []):
                canonical = builder_profile.alias_lookup.get(str(value).lower(), str(value))
                key = str(canonical).lower().strip()
                if not key or key in builder_profile.exclude_entities or key in seen_entities:
                    continue
                seen_entities.add(key)
                normalized_entities.append(str(canonical))
            text_blob = f"{title} {summary}".lower()
            for key, display in list(builder_profile.include_entities.items()):
                if key in text_blob and key not in seen_entities and key not in builder_profile.exclude_entities:
                    seen_entities.add(key)
                    normalized_entities.append(display)
            entities = normalized_entities
        message_ids: list[str] = []
        seen_message_ids: set[str] = set()
        for entry in cluster.entries:
            for message_id in entry.message_ids:
                if message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)
                message_ids.append(message_id)
        event_shape_score = round(
            max(
                _event_signal_score(summary),
                _event_signal_score(title),
                sum(item.signal_score for item in cluster.entries) / max(1, len(cluster.entries)),
            ),
            4,
        )
        anchor_strength = round(
            _anchor_strength(
                entries=cluster.entries,
                entities=entities,
                topics=topics,
                citations=citations,
                message_ids=message_ids,
                day_key=cluster.day_key,
                source_id=cluster.source_id,
            ),
            4,
        )
        has_timeline = bool(start_at and end_at and start_at != end_at)
        quality_flags = _quality_flags(
            summary=summary,
            title=title,
            atom_count=len(atoms_sorted),
            evidence_strength=evidence_strength,
            event_shape_score=event_shape_score,
            anchor_strength=anchor_strength,
            source_id=cluster.source_id,
            day_key=cluster.day_key,
            entities=entities,
            topics=topics,
            meaningful_token_count=meaningful_token_count,
            min_meaningful_tokens=min_meaningful_tokens,
        )
        if promoted and any(
            flag in {"low_information_summary", "weak_event_shape", "low_anchor_strength", "unknown_source_anchor"}
            for flag in quality_flags
        ):
            promoted = False
        if promoted and not has_timeline and evidence_strength < 0.72:
            promoted = False
        promotion_status = "promoted" if promoted else "candidate"
        promotion_reason = "event_shape_and_anchors"
        if not promoted:
            if "low_information_summary" in quality_flags:
                promotion_reason = "demoted_low_information"
            elif "weak_event_shape" in quality_flags:
                promotion_reason = "demoted_weak_event_shape"
            elif "low_anchor_strength" in quality_flags:
                promotion_reason = "demoted_low_anchor_strength"
            elif not has_timeline:
                promotion_reason = "demoted_missing_timeline"
            else:
                promotion_reason = "candidate_review_required"

        card_domain = cluster.entries[0].domain if cluster.entries else "episode"
        if builder_profile is not None and builder_profile.domain_rules:
            domain_text = f"{title}\n{summary}"
            for rule in list(builder_profile.domain_rules):
                compiled = rule.get("compiled")
                if not hasattr(compiled, "search"):
                    continue
                if not bool(compiled.search(domain_text)):
                    continue
                status = str(rule.get("status") or "include").strip().lower() or "include"
                if status == "exclude":
                    continue
                card_domain = str(rule.get("domain") or card_domain).strip() or card_domain
                break

        cue_terms = _cue_terms_from_values(
            [title, summary, cluster.source_id, cluster.day_key, card_domain]
            + entities
            + topics
            + message_ids
        )
        if builder_profile is not None:
            merged_cues = list(cue_terms)
            merged_cues.extend(builder_profile.cue_include)
            cue_terms = [
                item
                for item in _cue_terms_from_values(merged_cues)
                if str(item).lower() not in builder_profile.cue_exclude
            ]

        retrieval_weight = round(max(0.0, min(1.0, 0.55 * confidence + 0.45 * evidence_strength)), 4)
        if builder_profile is not None and any(str(item).lower() in builder_profile.include_entities for item in list(entities or [])):
            retrieval_weight = round(_clamp01(float(retrieval_weight) + 0.08), 4)

        card_key = _episode_key(cluster.source_id, cluster.day_key, index)
        cards.append(
            {
                "episode_id": _episode_id_from_key(card_key),
                "card_type": "episode_event",
                "promotion_status": promotion_status,
                "promotion_reason": promotion_reason,
                "title": _compact_text(title, max_chars=96),
                "summary": summary,
                "source_id": cluster.source_id,
                "day_key": cluster.day_key,
                "domain": card_domain,
                "atom_count": len(atoms_sorted),
                "atom_ids": [str(item.atom_id) for item in atoms_sorted],
                "message_ids": message_ids,
                "actors": entities,
                "entities": entities,
                "topic_tags": topics,
                "topics": topics,
                "cue_terms": cue_terms,
                "citations": citations,
                "citation_count": len(citations),
                "timestamp_start": start_at,
                "start_at": start_at,
                "timestamp_end": end_at,
                "end_at": end_at,
                "event_window": _event_window(cluster.entries, citations_chrono, start_at, end_at),
                "confidence": confidence,
                "salience_score": salience_score,
                "evidence_strength": evidence_strength,
                "event_shape_score": event_shape_score,
                "anchor_strength": anchor_strength,
                "retrieval_weight": retrieval_weight,
                "meaningful_token_count": meaningful_token_count,
                "quality_flags": quality_flags,
                "question_seed": _question_seed(entities, topics, title, summary),
            }
        )

    cards.sort(
        key=lambda item: (
            str(item.get("start_at") or ""),
            str(item.get("source_id") or ""),
            str(item.get("episode_id") or ""),
        )
    )
    return cards


def _load_store(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path)
    if suffix == ".json":
        return load_inmemory_store_from_json(path)
    raise ValueError("memories path must be .sqlite3/.sqlite/.db/.json")


def _include_atom(atom: MemoryAtom, include_non_active: bool) -> bool:
    raw_status = getattr(atom, "status", "") or ""
    status = str(getattr(raw_status, "value", raw_status) or "").strip().lower()
    if include_non_active:
        return status not in {AtomStatus.TOMBSTONED.value, AtomStatus.ARCHIVED.value}
    return status == AtomStatus.ACTIVE.value


def main() -> int:
    parser = argparse.ArgumentParser(description="Build event-style episode cards from memory atoms.")
    parser.add_argument(
        "--memories",
        default=str(REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3"),
        help="Path to memory store (.sqlite3/.sqlite/.db/.json).",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output JSON path. Default: runtime/episodes/episode_cards_<stamp>.json",
    )
    parser.add_argument(
        "--include-non-active",
        action="store_true",
        help="Include superseded/conflicted atoms (still excludes tombstoned/archived).",
    )
    parser.add_argument(
        "--min-atoms",
        type=int,
        default=2,
        help="Minimum atom count required to auto-promote an episode card.",
    )
    parser.add_argument(
        "--min-meaningful-tokens",
        type=int,
        default=30,
        help="Minimum meaningful token count across a cluster required for auto-promotion.",
    )
    parser.add_argument(
        "--max-gap-minutes",
        type=int,
        default=45,
        help="Maximum timestamp gap to keep atoms in the same event cluster.",
    )
    parser.add_argument(
        "--min-evidence-strength",
        type=float,
        default=0.35,
        help="Minimum evidence strength [0..1] required to auto-promote card.",
    )
    parser.add_argument(
        "--allow-single-strong",
        action="store_true",
        help="Allow single-atom events to auto-promote when evidence is strong.",
    )
    parser.add_argument(
        "--rejects-out",
        default="",
        help="Optional rejects artifact path. Default: sibling episode_cards_<stamp>.rejects.json",
    )
    parser.add_argument(
        "--builder-profile",
        default="",
        help="Optional builder profile path (runtime/builder_profiles/profile_<id>.json).",
    )
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2

    try:
        store = _load_store(memories_path)
    except Exception as exc:
        print(f"error=failed to load memory store: {exc}")
        return 2

    try:
        atoms_all = list(store.list_atoms())  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"error=failed to list atoms: {exc}")
        return 2

    atoms = [atom for atom in atoms_all if _include_atom(atom, include_non_active=bool(args.include_non_active))]
    builder_profile_path = Path(str(args.builder_profile).strip()).expanduser().resolve() if str(args.builder_profile).strip() else None
    builder_profile: _BuilderProfile | None = None
    if builder_profile_path is not None:
        if not builder_profile_path.exists():
            print(f"error=builder profile path not found: {builder_profile_path}")
            return 2
        try:
            builder_profile = _load_builder_profile(builder_profile_path)
        except Exception as exc:
            print(f"error=failed to load builder profile: {exc}")
            return 2

    cards = _build_cards(
        atoms,
        min_atoms=max(1, int(args.min_atoms)),
        max_gap_minutes=max(1, int(args.max_gap_minutes)),
        min_meaningful_tokens=max(1, int(args.min_meaningful_tokens)),
        min_evidence_strength=max(0.0, min(1.0, float(args.min_evidence_strength))),
        allow_single_strong=bool(args.allow_single_strong),
        builder_profile=builder_profile,
    )

    promoted_count = sum(1 for card in cards if str(card.get("promotion_status") or "") == "promoted")
    candidate_count = max(0, len(cards) - promoted_count)

    out_path = (
        Path(args.out).expanduser().resolve()
        if str(args.out).strip()
        else REPO_ROOT / "runtime" / "episodes" / f"episode_cards_{_stamp()}.json"
    )
    rejects_out_path = (
        Path(args.rejects_out).expanduser().resolve()
        if str(args.rejects_out).strip()
        else out_path.with_name(f"{out_path.stem}.rejects.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rejects_out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "numquamoblita.episode_cards.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_store": str(memories_path),
        "memories_path": str(memories_path),
        "atom_count": len(atoms),
        "episode_count": len(cards),
        "promoted_count": promoted_count,
        "candidate_count": candidate_count,
        "counts": {
            "atom_count": len(atoms),
            "episode_count": len(cards),
            "promoted_count": promoted_count,
            "candidate_count": candidate_count,
            "rejected_count": candidate_count,
        },
        "build_policy": {
            "min_atoms": max(1, int(args.min_atoms)),
            "min_meaningful_tokens": max(1, int(args.min_meaningful_tokens)),
            "max_gap_minutes": max(1, int(args.max_gap_minutes)),
            "min_evidence_strength": max(0.0, min(1.0, float(args.min_evidence_strength))),
            "allow_single_strong": bool(args.allow_single_strong),
            "builder_profile_path": str(builder_profile_path) if builder_profile_path is not None else "",
            "builder_profile_id": str(getattr(builder_profile, "profile_id", "") or ""),
        },
        "cards": cards,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rejects_payload = _build_rejects_payload(
        cards=cards,
        source_cards=out_path,
        min_atoms=max(1, int(args.min_atoms)),
        min_meaningful_tokens=max(1, int(args.min_meaningful_tokens)),
        min_evidence_strength=max(0.0, min(1.0, float(args.min_evidence_strength))),
    )
    rejects_out_path.write_text(json.dumps(rejects_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"episode_cards_json={out_path}")
    print(f"episode_rejects_json={rejects_out_path}")
    print(f"atom_count={len(atoms)}")
    print(f"episode_count={len(cards)}")
    print(f"promoted_count={promoted_count}")
    print(f"candidate_count={candidate_count}")
    if builder_profile_path is not None:
        print(f"builder_profile_path={builder_profile_path}")
        if builder_profile is not None:
            print(f"builder_profile_id={builder_profile.profile_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
