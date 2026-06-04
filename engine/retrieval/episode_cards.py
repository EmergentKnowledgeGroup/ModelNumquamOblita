from __future__ import annotations

import json
import re
import math
from datetime import date
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_CUE_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-']+")
_QUOTE_RE = re.compile(r"['\"]([^'\"]{2,120})['\"]")
_CUE_STOPWORDS = {
    "about",
    "a",
    "am",
    "an",
    "and",
    "are",
    "at",
    "after",
    "before",
    "could",
    "detail",
    "did",
    "do",
    "does",
    "for",
    "had",
    "happen",
    "happened",
    "happening",
    "has",
    "have",
    "he",
    "her",
    "hers",
    "him",
    "his",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "memory",
    "me",
    "my",
    "of",
    "on",
    "or",
    "remember",
    "recall",
    "said",
    "she",
    "so",
    "tell",
    "that",
    "this",
    "to",
    "too",
    "what",
    "when",
    "where",
    "with",
    "would",
    "from",
    "into",
    "your",
    "their",
    "there",
    "them",
    "then",
    "they",
    "was",
    "we",
    "were",
    "who",
    "why",
    "yo",
    "you",
}
_LOW_SIGNAL_CUE_TERMS = {
    "day",
    "days",
    "moment",
    "moments",
    "night",
    "nights",
    "time",
    "times",
    "today",
    "tonight",
    "tomorrow",
    "yesterday",
}
_NAMED_ENTITY_IGNORE_TERMS = {"assistant", "user", "dyad"}
_ORDINAL_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)$", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CURRENT_TRUTH_PHRASES = ("right now", "currently", "current", "latest", "today", "as of now")
_HISTORICAL_TRUTH_PHRASES = ("used to", "previously", "earlier", "back then", "at the time")
_FOCUS_ENTITY_RE = re.compile(
    r"(?:who is|who's|what happened to|tell me about|what do you know about)\s+([A-Za-z0-9][A-Za-z0-9'\-_]{2,})",
    re.IGNORECASE,
)
_HIGH_SIGNAL_CUE_WEIGHT_FLOOR = 1.4


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(str(text or "").lower()))


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[idx : idx + n] for idx in range(len(normalized) - n + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clean_cue_term(term: str) -> str:
    value = re.sub(r"\s+", " ", str(term or "").strip().lower())
    value = value.strip("`\"'[]{}()")
    if not value or len(value) < 3:
        return ""
    if value in _CUE_STOPWORDS:
        return ""
    return value


def _normalized_numeric_cue(term: str) -> str:
    match = _ORDINAL_RE.match(str(term or "").strip().lower())
    if not match:
        return ""
    return match.group(1)


def _focus_terms_from_query(text: str) -> set[str]:
    raw = str(text or "").strip()
    if not raw:
        return set()
    out: set[str] = set()
    for value in _FOCUS_ENTITY_RE.findall(raw):
        cleaned = _clean_cue_term(value)
        if cleaned:
            out.add(cleaned)
    if out:
        return out
    for raw_token in re.findall(r"[A-Z][A-Za-z0-9'\-_]{2,}", raw):
        cleaned = _clean_cue_term(raw_token)
        if cleaned:
            out.add(cleaned)
    return out


def _cue_terms_from_text(text: str) -> set[str]:
    raw = str(text or "")
    terms: set[str] = set()
    for quoted in _QUOTE_RE.findall(raw):
        cleaned = _clean_cue_term(quoted)
        if cleaned:
            terms.add(cleaned)

    tokens = [_clean_cue_term(item) for item in _CUE_TOKEN_RE.findall(raw)]
    filtered = [token for token in tokens if token]
    for token in filtered:
        if len(token) >= 4 or "_" in token or any(ch.isdigit() for ch in token):
            terms.add(token)
        numeric = _normalized_numeric_cue(token)
        if numeric:
            terms.add(numeric)
    for idx in range(max(0, len(filtered) - 1)):
        pair = f"{filtered[idx]} {filtered[idx + 1]}".strip()
        cleaned_pair = _clean_cue_term(pair)
        if cleaned_pair and len(cleaned_pair) >= 7:
            terms.add(cleaned_pair)
    if len(terms) <= 12:
        return terms

    def _rank(term: str) -> tuple[int, int, int]:
        score = 0
        if " " in term:
            score += 2
        if "_" in term or any(ch.isdigit() for ch in term):
            score += 2
        if len(term) >= 8:
            score += 1
        return (score, len(term), -len(term.split()))

    ranked = sorted(terms, key=_rank, reverse=True)
    return set(ranked[:12])


def _cue_terms_from_card(
    *,
    title: str,
    summary: str,
    source_id: str,
    day_key: str,
    domain: str,
    entities: list[str],
    topics: list[str],
) -> set[str]:
    seeded = [title, summary, source_id, day_key, domain] + list(entities) + list(topics)
    out: set[str] = set()
    for value in seeded:
        out.update(_cue_terms_from_text(value))
    return out


def _parse_iso_date(raw: str) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _query_reference_date(query_text: str) -> date | None:
    match = _ISO_DATE_RE.search(str(query_text or ""))
    if not match:
        return None
    return _parse_iso_date(match.group(1))


def _lineage_query_mode(query_text: str) -> tuple[str, date | None]:
    lowered = str(query_text or "").strip().lower()
    ref_date = _query_reference_date(query_text)
    if ref_date is not None:
        return "historical", ref_date
    if any(phrase in lowered for phrase in _CURRENT_TRUTH_PHRASES):
        return "current", None
    if any(phrase in lowered for phrase in _HISTORICAL_TRUTH_PHRASES):
        return "historical", None
    return "default", None


def _historical_lineage_match(card: "EpisodeCard", *, ref_date: date) -> float:
    start_date = _parse_iso_date(card.start_at or card.day_key)
    end_date = _parse_iso_date(card.end_at or card.start_at or card.day_key)
    if start_date is None:
        return 0.0
    if end_date is None:
        end_date = start_date
    if start_date <= ref_date <= end_date:
        return 1.0
    if ref_date < start_date:
        return 0.0
    delta_days = abs((ref_date - start_date).days)
    return max(0.0, 1.0 - min(1.0, delta_days / 30.0))


@dataclass(slots=True)
class EpisodeCard:
    episode_id: str
    title: str
    summary: str
    source_id: str
    day_key: str
    domain: str
    citations: list[str]
    confidence: float
    evidence_strength: float
    retrieval_weight: float
    promotion_status: str
    promotion_reason: str
    atom_count: int
    atom_ids: list[str]
    message_ids: list[str]
    entities: list[str]
    topics: list[str]
    start_at: str
    end_at: str
    truth_family_id: str = ""
    supersedes_episode_id: str = ""
    superseded_by_episode_id: str = ""
    lineage_is_current: bool = False
    cue_terms: set[str] = None  # type: ignore[assignment]
    token_set: set[str] = None  # type: ignore[assignment]
    ngrams: set[str] = None  # type: ignore[assignment]


@dataclass(slots=True)
class EpisodeHit:
    card: EpisodeCard
    score: float
    cue_match: float
    lexical: float
    semantic: float


class EpisodeCardIndex:
    """Fast lexical+semantic lookup over generated episode-card JSON artifacts."""

    def __init__(self, cards: list[EpisodeCard]) -> None:
        self.cards = list(cards)
        self._augment_source_local_entity_cues()
        self._cue_doc_frequency = self._build_cue_doc_frequency()

    @classmethod
    def load(cls, path: str | Path) -> "EpisodeCardIndex":
        p = Path(path).expanduser().resolve()
        payload = json.loads(p.read_text(encoding="utf-8"))
        rows = list(payload.get("cards") or [])
        cards: list[EpisodeCard] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            episode_id = str(row.get("episode_id") or "").strip()
            summary = str(row.get("summary") or "").strip()
            title = str(row.get("title") or "").strip()
            if not episode_id or not summary:
                continue
            source_id = str(row.get("source_id") or "").strip()
            day_key = str(row.get("day_key") or "").strip()
            domain = str(row.get("domain") or "").strip()
            citations = [str(item).strip() for item in list(row.get("citations") or []) if str(item).strip()]
            confidence = _clamp01(float(row.get("confidence") or 0.0))
            evidence_strength = _clamp01(float(row.get("evidence_strength") or 0.0))
            retrieval_weight = _clamp01(float(row.get("retrieval_weight") or 0.0))
            promotion_status = str(row.get("promotion_status") or "promoted").strip().lower() or "promoted"
            promotion_reason = str(row.get("promotion_reason") or "").strip().lower()
            atom_count = max(0, int(row.get("atom_count") or 0))
            atom_ids = [str(item).strip() for item in list(row.get("atom_ids") or []) if str(item).strip()]
            message_ids = [str(item).strip() for item in list(row.get("message_ids") or []) if str(item).strip()]
            entities = [str(item).strip() for item in list(row.get("entities") or []) if str(item).strip()]
            topics = [str(item).strip() for item in list(row.get("topics") or []) if str(item).strip()]
            start_at = str(row.get("start_at") or "").strip()
            end_at = str(row.get("end_at") or "").strip()
            truth_family_id = str(row.get("truth_family_id") or "").strip()
            supersedes_episode_id = str(row.get("supersedes_episode_id") or "").strip()
            superseded_by_episode_id = str(row.get("superseded_by_episode_id") or "").strip()
            lineage_is_current = bool(row.get("lineage_is_current")) if any(
                key in row for key in ("truth_family_id", "supersedes_episode_id", "superseded_by_episode_id", "lineage_is_current")
            ) else False
            index_text = " ".join([title, summary, source_id, day_key, domain] + entities + topics)
            cue_terms = {str(item).strip().lower() for item in list(row.get("cue_terms") or []) if str(item).strip()}
            if not cue_terms:
                cue_terms = _cue_terms_from_card(
                    title=title,
                    summary=summary,
                    source_id=source_id,
                    day_key=day_key,
                    domain=domain,
                    entities=entities,
                    topics=topics,
                )
            cards.append(
                EpisodeCard(
                    episode_id=episode_id,
                    title=title,
                    summary=summary,
                    source_id=source_id,
                    day_key=day_key,
                    domain=domain,
                    citations=citations,
                    confidence=confidence,
                    evidence_strength=evidence_strength,
                    retrieval_weight=retrieval_weight,
                    promotion_status=promotion_status,
                    promotion_reason=promotion_reason,
                    atom_count=atom_count,
                    atom_ids=atom_ids,
                    message_ids=message_ids,
                    entities=entities,
                    topics=topics,
                    start_at=start_at,
                    end_at=end_at,
                    truth_family_id=truth_family_id,
                    supersedes_episode_id=supersedes_episode_id,
                    superseded_by_episode_id=superseded_by_episode_id,
                    lineage_is_current=lineage_is_current,
                    cue_terms=cue_terms,
                    token_set=_tokenize(index_text),
                    ngrams=_char_ngrams(index_text),
                )
            )
        return cls(cards)

    def _augment_source_local_entity_cues(self) -> None:
        grouped: dict[tuple[str, str], list[EpisodeCard]] = defaultdict(list)
        for card in self.cards:
            grouped[(card.source_id, card.day_key)].append(card)
        for peers in grouped.values():
            peer_entities: set[str] = set()
            for peer in peers:
                for entity in peer.entities:
                    cleaned = _clean_cue_term(entity)
                    if cleaned and cleaned not in _NAMED_ENTITY_IGNORE_TERMS:
                        peer_entities.add(cleaned)
            if not peer_entities:
                continue
            for card in peers:
                card.cue_terms.update(peer_entities)

    def _build_cue_doc_frequency(self) -> dict[str, int]:
        frequency: dict[str, int] = {}
        for card in self.cards:
            for term in card.cue_terms:
                frequency[term] = frequency.get(term, 0) + 1
        return frequency

    def _cue_term_weight(self, term: str) -> float:
        cleaned = _clean_cue_term(term)
        if not cleaned:
            return 0.0
        rarity = math.log((len(self.cards) + 1) / (self._cue_doc_frequency.get(cleaned, 0) + 1)) + 1.0
        specificity = 1.0
        if " " in cleaned:
            specificity += 0.35
        if any(ch.isdigit() for ch in cleaned):
            specificity += 0.45
        if len(cleaned) >= 9:
            specificity += 0.15
        if cleaned in _LOW_SIGNAL_CUE_TERMS:
            specificity -= 0.45
        return max(0.2, rarity * specificity)

    def _weighted_cue_overlap(self, query_cues: set[str], card_cues: set[str]) -> float:
        if not query_cues or not card_cues:
            return 0.0
        denominator = sum(self._cue_term_weight(term) for term in query_cues)
        if denominator <= 0.0:
            return 0.0
        numerator = sum(self._cue_term_weight(term) for term in query_cues.intersection(card_cues))
        return numerator / denominator

    def _person_focus_adjustment(self, *, query_text: str, card: EpisodeCard) -> float:
        focus_terms = _focus_terms_from_query(query_text)
        if not focus_terms:
            return 0.0
        text_tokens = _tokenize(f"{card.title} {card.summary}")
        entity_terms = {_clean_cue_term(item) for item in list(card.entities or [])}
        topic_terms = {_clean_cue_term(item) for item in list(card.topics or [])}
        cue_terms = {_clean_cue_term(item) for item in list(card.cue_terms or [])}
        entity_terms.discard("")
        topic_terms.discard("")
        cue_terms.discard("")
        if not focus_terms.intersection(entity_terms.union(cue_terms).union(text_tokens)):
            return 0.0

        text_hits = focus_terms.intersection(text_tokens)
        cue_hits = focus_terms.intersection(cue_terms)
        metadata_only_hits = focus_terms.intersection(entity_terms).difference(text_hits.union(cue_hits))
        entity_breadth = max(0, len(entity_terms.difference(focus_terms)))
        topic_breadth = max(0, len(topic_terms.difference(focus_terms)))
        adjustment = 0.0
        if text_hits and cue_hits:
            adjustment += 0.22
        elif text_hits or cue_hits:
            adjustment += 0.10
        else:
            adjustment -= 0.24
        adjustment -= min(0.28, (0.06 * entity_breadth) + (0.03 * max(0, topic_breadth - 1)))
        if not text_hits and not cue_hits and entity_breadth >= 2:
            adjustment -= 0.10
        if metadata_only_hits:
            adjustment -= 0.32
            adjustment -= min(0.18, (0.05 * entity_breadth) + (0.03 * topic_breadth))
        if len(entity_terms) <= max(2, len(focus_terms) + 1):
            adjustment += 0.06
        return adjustment

    def _apply_explicit_lineage_resolution(self, query_text: str, ranked: list[EpisodeHit]) -> list[EpisodeHit]:
        mode, ref_date = _lineage_query_mode(query_text)
        if not any(str(item.card.truth_family_id or "").strip() for item in ranked):
            return ranked
        adjusted: list[EpisodeHit] = []
        for hit in ranked:
            bonus = 0.0
            family_id = str(hit.card.truth_family_id or "").strip()
            if family_id:
                if mode in {"default", "current"}:
                    if bool(hit.card.lineage_is_current):
                        bonus += 0.08
                    elif str(hit.card.superseded_by_episode_id or "").strip():
                        bonus -= 0.08
                elif mode == "historical":
                    if ref_date is not None:
                        history_fit = _historical_lineage_match(hit.card, ref_date=ref_date)
                        bonus += history_fit * 0.12
                        if bool(hit.card.lineage_is_current) and history_fit < 0.5:
                            bonus -= 0.06
                    else:
                        if str(hit.card.superseded_by_episode_id or "").strip():
                            bonus += 0.05
                        if bool(hit.card.lineage_is_current):
                            bonus -= 0.04
            adjusted.append(EpisodeHit(card=hit.card, score=_clamp01(hit.score + bonus), cue_match=hit.cue_match, lexical=hit.lexical, semantic=hit.semantic))
        adjusted.sort(key=lambda item: item.score, reverse=True)
        return adjusted

    def search(self, query_text: str, *, top_k: int = 3) -> list[EpisodeHit]:
        text = str(query_text or "").strip()
        if not text or not self.cards:
            return []
        query_tokens = _tokenize(text)
        query_ngrams = _char_ngrams(text)
        query_cues = _cue_terms_from_text(text)
        if not query_tokens and not query_ngrams:
            return []
        ranked: list[EpisodeHit] = []
        for card in self.cards:
            if card.promotion_status not in {"promoted", "approved"}:
                continue
            lexical = len(query_tokens.intersection(card.token_set)) / max(1, len(query_tokens)) if query_tokens else 0.0
            semantic = _jaccard(query_ngrams, card.ngrams)
            cue_match = self._weighted_cue_overlap(query_cues, card.cue_terms)
            quality = max(card.confidence, card.retrieval_weight, card.evidence_strength)
            if query_cues:
                # Explicit event/date prompts need cue identity to dominate generic lexical overlap.
                score = _clamp01(0.62 * cue_match + 0.18 * lexical + 0.10 * semantic + 0.10 * quality)
            else:
                score = _clamp01(0.44 * lexical + 0.32 * semantic + 0.24 * quality)
            score = _clamp01(score + self._person_focus_adjustment(query_text=text, card=card))
            ranked.append(
                EpisodeHit(
                    card=card,
                    score=score,
                    cue_match=cue_match,
                    lexical=lexical,
                    semantic=semantic,
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        if query_cues:
            exact_support_terms = [
                term
                for term in query_cues
                if term not in _LOW_SIGNAL_CUE_TERMS and self._cue_term_weight(term) >= _HIGH_SIGNAL_CUE_WEIGHT_FLOOR
            ]
            if exact_support_terms:
                supported_terms = [
                    term for term in exact_support_terms if any(term in item.card.cue_terms for item in ranked)
                ]
                if not supported_terms:
                    return []
                strongest_supported = max(self._cue_term_weight(term) for term in supported_terms)
                required_terms = {
                    term
                    for term in supported_terms
                    if self._cue_term_weight(term) >= max(_HIGH_SIGNAL_CUE_WEIGHT_FLOOR, strongest_supported - 0.35)
                }
                ranked = [item for item in ranked if required_terms.intersection(item.card.cue_terms)]
        ranked = self._apply_explicit_lineage_resolution(text, ranked)
        return ranked[: max(1, int(top_k))]
