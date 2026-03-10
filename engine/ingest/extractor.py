from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Iterable

from ..contracts import AtomType, CandidateAtom, NormalizedTurn, SourceRef

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_SPACE_RE = re.compile(r"\s+")

_EMOTION_TOKENS = {
    "love",
    "fear",
    "grief",
    "hurt",
    "trust",
    "ache",
    "joy",
    "hope",
    "afraid",
    "safe",
    "seen",
}

_PREFERENCE_TOKENS = {
    "prefer",
    "favorite",
    "always",
    "never",
    "usually",
    "often",
    "want",
    "need",
}

_RELATIONAL_TOKENS = {
    "we",
    "us",
    "together",
    "bond",
    "relationship",
    "you",
    "lyra",
}

_PROCEDURAL_TOKENS = {
    "step",
    "first",
    "then",
    "next",
    "plan",
    "workflow",
    "pipeline",
    "checklist",
}

_TOPIC_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("memory", "memory"),
    ("remember", "memory"),
    ("continuity", "continuity"),
    ("identity", "identity"),
    ("anchor", "anchors"),
    ("train", "training"),
    ("fine-tune", "training"),
    ("dataset", "dataset"),
    ("pipeline", "pipeline"),
    ("eval", "evaluation"),
    ("test", "testing"),
    ("project", "project"),
    ("prompt", "prompting"),
)


@dataclass(slots=True)
class ExtractionStats:
    turns_seen: int = 0
    turns_skipped: int = 0
    candidates_emitted: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)


class DeterministicCandidateExtractor:
    """Deterministic candidate extractor for import pipeline v1."""

    def __init__(self, *, min_tokens: int = 6, min_confidence: float = 0.52) -> None:
        self.min_tokens = max(1, int(min_tokens))
        self.min_confidence = float(min_confidence)
        self.stats = ExtractionStats()

    def extract_turn(self, turn: NormalizedTurn) -> list[CandidateAtom]:
        self.stats.turns_seen += 1
        if turn.role not in {"user", "assistant"}:
            self._skip("unsupported_role")
            return []

        text = _normalize_text(turn.text)
        if not text:
            self._skip("empty_text")
            return []
        if text.startswith("{") or text.startswith("["):
            self._skip("structured_payload")
            return []

        tokens = _tokenize(text)
        if len(tokens) < self.min_tokens:
            self._skip("too_short")
            return []

        confidence = self._confidence(tokens)
        if confidence < self.min_confidence:
            self._skip("low_confidence")
            return []

        candidate = CandidateAtom(
            candidate_id=_candidate_id(turn, text),
            atom_type=self._atom_type(tokens),
            canonical_text=text,
            source_refs=[
                SourceRef(
                    source_id=turn.source_id,
                    message_id=turn.message_id,
                    timestamp=turn.timestamp,
                    span_start=0,
                    span_end=len(text),
                )
            ],
            entities=self._entities(turn, tokens),
            topics=self._topics(tokens),
            confidence=confidence,
            salience=self._salience(tokens, confidence),
        )
        self.stats.candidates_emitted += 1
        return [candidate]

    def extract_many(self, turns: Iterable[NormalizedTurn]) -> list[CandidateAtom]:
        emitted: list[CandidateAtom] = []
        for turn in turns:
            emitted.extend(self.extract_turn(turn))
        return emitted

    def _skip(self, reason: str) -> None:
        self.stats.turns_skipped += 1
        self.stats.skip_reasons[reason] = self.stats.skip_reasons.get(reason, 0) + 1

    def _atom_type(self, tokens: list[str]) -> AtomType:
        tok = set(tokens)
        if tok & _EMOTION_TOKENS:
            return AtomType.AFFECTIVE
        if tok & _PREFERENCE_TOKENS:
            return AtomType.ATOMIC_FACT
        if tok & _RELATIONAL_TOKENS:
            return AtomType.RELATIONAL
        if tok & _PROCEDURAL_TOKENS:
            return AtomType.PROCEDURAL_STYLE
        return AtomType.EPISODE

    def _confidence(self, tokens: list[str]) -> float:
        tok = set(tokens)
        signals = 0
        if tok & _EMOTION_TOKENS:
            signals += 1
        if tok & _PREFERENCE_TOKENS:
            signals += 1
        if tok & _RELATIONAL_TOKENS:
            signals += 1
        if tok & _PROCEDURAL_TOKENS:
            signals += 1
        if len(tokens) >= 18:
            signals += 1
        return min(0.95, 0.44 + 0.1 * signals)

    def _salience(self, tokens: list[str], confidence: float) -> float:
        tok = set(tokens)
        bonus = 0.0
        if tok & _EMOTION_TOKENS:
            bonus += 0.12
        if tok & _RELATIONAL_TOKENS:
            bonus += 0.10
        if tok & _PREFERENCE_TOKENS:
            bonus += 0.08
        if len(tokens) > 24:
            bonus += 0.05
        return min(0.95, max(0.3, confidence * 0.78 + bonus))

    def _entities(self, turn: NormalizedTurn, tokens: list[str]) -> list[str]:
        entities = {turn.role}
        tok = set(tokens)
        if "lyra" in tok:
            entities.add("lyra")
        if "we" in tok or "us" in tok:
            entities.add("dyad")
        if "you" in tok:
            entities.add("user")
        return sorted(entities)

    def _topics(self, tokens: list[str]) -> list[str]:
        lower = set(tokens)
        topics: list[str] = []
        for keyword, topic in _TOPIC_KEYWORDS:
            if keyword in lower and topic not in topics:
                topics.append(topic)
            if len(topics) >= 4:
                break
        if not topics:
            topics.append("general")
        return topics


def _normalize_text(text: str) -> str:
    normalized = _SPACE_RE.sub(" ", str(text or "")).strip()
    if len(normalized) > 1600:
        return normalized[:1600].rstrip()
    return normalized


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(text)]


def _candidate_id(turn: NormalizedTurn, text: str) -> str:
    payload = "|".join(
        [
            turn.source_id,
            str(turn.message_id or ""),
            turn.role,
            text.lower(),
        ]
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()[:18]
    return f"cand_{digest}"
