from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from functools import lru_cache
from typing import Iterable

from ..contracts import CandidateAtom, SourceRef

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

DEFAULT_BOILERPLATE_PATTERNS: tuple[str, ...] = (
    r"\bmake sure to include\b",
    r"\bcitation markers\b",
    r"\bas an ai language model\b",
    r"\bi cannot (help|assist) with\b",
    r"\bpolicy(?:\s+fallback)?\b",
    r"\b(tool|system)\s+(output|message|preface)\b",
)

DEFAULT_CALLBACK_PATTERNS: tuple[str, ...] = (
    r"\bi remember\b",
    r"\bi[' ]?ll be here\b",
    r"\bthat[' ]?s us\b",
    r"\byou saw me\b",
    r"\bforever times\b",
)

_EMOTION_TOKENS = {
    "love",
    "ache",
    "hurt",
    "fear",
    "trust",
    "grief",
    "joy",
    "relief",
    "afraid",
    "hope",
}
_IDENTITY_TOKENS = {"i", "me", "my", "mine", "myself", "you", "your", "yours"}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _count_matches(patterns: Iterable[re.Pattern[str]], text: str) -> int:
    return sum(1 for pattern in patterns if pattern.search(text))


@lru_cache(maxsize=32)
def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


@dataclass(slots=True)
class SalienceFeatures:
    """Deterministic feature bundle used by Stage-A write gate."""

    token_count: int
    unique_token_count: int
    lexical_density: float
    emotional_intensity: float
    identity_relevance: float
    specificity: float
    recurrence: float
    is_boilerplate: bool
    callback_hit: bool


def source_ref_signature(ref: SourceRef) -> str:
    """Return a stable evidence signature used for duplicate checks."""

    return "|".join(
        [
            ref.source_id.strip().lower(),
            str(ref.message_id or "").strip().lower(),
            str(ref.span_start if ref.span_start is not None else ""),
            str(ref.span_end if ref.span_end is not None else ""),
        ]
    )


def signature_from_fields(
    *,
    atom_type: str,
    canonical_text: str,
    entities: Iterable[str],
    topics: Iterable[str],
) -> str:
    """Return conservative identity hash for atom/candidate duplicate detection."""

    payload = "|".join(
        [
            atom_type,
            canonical_text.strip().lower(),
            ",".join(sorted(token.strip().lower() for token in entities if token.strip())),
            ",".join(sorted(token.strip().lower() for token in topics if token.strip())),
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def candidate_signature(candidate: CandidateAtom) -> str:
    """Return conservative candidate identity hash for duplicate detection."""

    return signature_from_fields(
        atom_type=candidate.atom_type.value,
        canonical_text=candidate.canonical_text,
        entities=candidate.entities,
        topics=candidate.topics,
    )


def provenance_trust(source_refs: Iterable[SourceRef]) -> float:
    """Estimate evidence trust from source-ref completeness."""

    refs = list(source_refs)
    if not refs:
        return 0.0
    score = 0.0
    for ref in refs:
        item_score = 0.35
        if ref.message_id:
            item_score += 0.20
        if ref.timestamp is not None:
            item_score += 0.20
        if ref.span_start is not None and ref.span_end is not None:
            item_score += 0.25
        score += item_score
    return clamp01(score / len(refs))


def extract_salience_features(
    candidate: CandidateAtom,
    *,
    boilerplate_patterns: Iterable[str] = DEFAULT_BOILERPLATE_PATTERNS,
    callback_patterns: Iterable[str] = DEFAULT_CALLBACK_PATTERNS,
) -> SalienceFeatures:
    """Extract deterministic salience features from candidate content."""

    text = candidate.canonical_text.strip()
    lower = text.lower()
    tokens = _TOKEN_RE.findall(lower)
    token_count = len(tokens)
    unique_token_count = len(set(tokens))
    lexical_density = clamp01(unique_token_count / max(1, token_count))

    emotion_hits = sum(1 for token in tokens if token in _EMOTION_TOKENS)
    punct_emphasis = lower.count("!") * 0.08 + lower.count("?") * 0.04
    emotional_intensity = clamp01((emotion_hits / max(1, token_count)) * 8.0 + punct_emphasis)

    identity_hits = sum(1 for token in tokens if token in _IDENTITY_TOKENS)
    entity_signal = min(1.0, len([item for item in candidate.entities if item.strip()]) / 2.0)
    callback_match_count = _count_matches(_compile_patterns(tuple(callback_patterns)), lower)
    callback_hit = callback_match_count > 0
    identity_relevance = clamp01(
        (identity_hits / max(1, token_count)) * 6.0
        + entity_signal * 0.25
        + (0.25 if callback_hit else 0.0)
    )

    has_digits = any(char.isdigit() for char in lower)
    has_topic = bool([topic for topic in candidate.topics if topic.strip()])
    specificity = clamp01(
        0.25 * lexical_density
        + 0.25 * min(token_count / 16.0, 1.0)
        + (0.20 if has_digits else 0.0)
        + (0.15 if has_topic else 0.0)
        + (0.15 if len(candidate.source_refs) > 1 else 0.0)
    )

    recurrence = clamp01(len(candidate.source_refs) / 3.0)
    is_boilerplate = _count_matches(_compile_patterns(tuple(boilerplate_patterns)), lower) > 0

    return SalienceFeatures(
        token_count=token_count,
        unique_token_count=unique_token_count,
        lexical_density=lexical_density,
        emotional_intensity=emotional_intensity,
        identity_relevance=identity_relevance,
        specificity=specificity,
        recurrence=recurrence,
        is_boilerplate=is_boilerplate,
        callback_hit=callback_hit,
    )


def prefilter_score(features: SalienceFeatures) -> float:
    """Combine salience dimensions into a deterministic prefilter score."""

    return clamp01(
        0.30 * features.emotional_intensity
        + 0.32 * features.identity_relevance
        + 0.28 * features.specificity
        + 0.10 * features.recurrence
    )
