from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_CUE_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-']+")
_QUOTE_RE = re.compile(r"['\"]([^'\"]{2,120})['\"]")
_CUE_STOPWORDS = {
    "about",
    "after",
    "before",
    "could",
    "detail",
    "happen",
    "happened",
    "happening",
    "memory",
    "remember",
    "recall",
    "said",
    "tell",
    "that",
    "this",
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
}


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
    cue_terms: set[str]
    token_set: set[str]
    ngrams: set[str]


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
                    cue_terms=cue_terms,
                    token_set=_tokenize(index_text),
                    ngrams=_char_ngrams(index_text),
                )
            )
        return cls(cards)

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
            cue_match = len(query_cues.intersection(card.cue_terms)) / max(1, len(query_cues)) if query_cues else 0.0
            quality = max(card.confidence, card.retrieval_weight, card.evidence_strength)
            if query_cues:
                score = _clamp01(0.46 * cue_match + 0.26 * lexical + 0.18 * semantic + 0.10 * quality)
            else:
                score = _clamp01(0.44 * lexical + 0.32 * semantic + 0.24 * quality)
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
        return ranked[: max(1, int(top_k))]
