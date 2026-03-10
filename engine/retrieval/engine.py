from __future__ import annotations

import re
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import exp
from typing import TYPE_CHECKING, Any, Literal

from ..config import NumquamOblitaConfig, default_config
from ..contracts import MemoryPack, MemoryPackItem, memory_pack_from_items
from ..memory import AtomStatus, AtomStore, MemoryAtom

if TYPE_CHECKING:
    from ..continuity import ContinuityStore

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_QUOTED_PHRASE_RE = re.compile(r'"([^"]+)"|“([^”]+)”')
_EXPLICIT_MEMORY_PHRASES = ("remember when", "last time", "previously", "what did we decide")
_EPISODE_KEYWORDS = {
    "remember",
    "happened",
    "when",
    "before",
    "yesterday",
    "earlier",
    "last",
    "decided",
}
_PREFERENCE_KEYWORDS = {
    "prefer",
    "preference",
    "like",
    "dislike",
    "favorite",
    "favourite",
    "hate",
    "relationship",
}
_PROCEDURAL_KEYWORDS = {"how", "steps", "step", "process", "procedure", "plan", "workflow"}
_FACTUAL_KEYWORDS = {"what", "who", "where", "which", "fact", "facts"}
_TIME_INTENT_KEYWORDS = {"when", "yesterday", "today", "earlier", "before", "last", "ago", "date", "time"}
_CACHE_TOKEN_SCHEMA = "retriever-cache-v2"
_CACHE_CHANNELS = ("lexical", "bm25", "semantic", "sequence", "quote", "temporal", "graph", "continuity")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _dedupe_text_key(text: str) -> str:
    return " ".join(_tokenize(text)) or "<EMPTY_TOKENS>"


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[i : i + n] for i in range(len(normalized) - n + 1)}


def _token_trigrams(tokens: list[str]) -> set[tuple[str, str, str]]:
    if len(tokens) < 3:
        return set()
    return {(tokens[idx], tokens[idx + 1], tokens[idx + 2]) for idx in range(len(tokens) - 2)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def _lexical_similarity(query_tokens: set[str], text_tokens: set[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens.intersection(text_tokens)) / max(1, len(query_tokens))


def _temporal_relevance(atom: MemoryAtom, now: datetime) -> float:
    updated = atom.updated_at
    age_days = max((now - updated).total_seconds() / 86400.0, 0.0)
    half_life = max(atom.salience_half_life_days, 1)
    decay = exp((-0.6931471805599453 * age_days) / half_life)
    return _clamp01(decay)


def _memory_item(atom: MemoryAtom, *, confidence: float) -> MemoryPackItem:
    return MemoryPackItem(
        atom_id=atom.atom_id,
        canonical_text=atom.canonical_text,
        confidence=_clamp01(confidence),
        source_refs=list(atom.source_refs),
        conflict_state=atom.status.value,
    )


@dataclass(slots=True)
class RetrievalScoredAtom:
    atom: MemoryAtom
    score: float
    lexical: float
    semantic: float
    sequence: float
    temporal: float
    graph: float
    continuity: float
    quote: float = 0.0
    bm25: float = 0.0
    rrf: float = 0.0


@dataclass(slots=True)
class RetrievalResult:
    memory_pack: MemoryPack
    ranked_atom_ids: list[str]
    scored_atoms: list[RetrievalScoredAtom]
    dropped_reasons: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class _PreparedAtom:
    atom: MemoryAtom
    token_list: list[str]
    token_freq: dict[str, int]
    token_count: int
    token_set: set[str]
    token_trigrams: set[tuple[str, str, str]]
    ngrams: set[str]


@dataclass(slots=True)
class _RetrieverCache:
    token: Hashable
    prepared: list[_PreparedAtom]
    prepared_by_id: dict[str, _PreparedAtom]
    atom_by_id: dict[str, MemoryAtom]
    conflict_map: dict[str, set[str]]
    token_postings: dict[str, set[str]]
    token_doc_freq: dict[str, int]
    avg_token_count: float
    temporal_seed_ids: list[str]


@dataclass(slots=True)
class _PackBuildResult:
    pack: MemoryPack
    dropped_reasons: dict[str, str]


RetrievalProfile = Literal["episode_heavy", "preference_relational", "procedural", "factual", "mixed"]


class MemoryRetriever:
    """Multi-channel retrieval fusion over AtomStore with bounded budgets."""

    def __init__(self, store: AtomStore, *, config: NumquamOblitaConfig | None = None) -> None:
        self.store = store
        self.config = config or default_config()
        self._cache: _RetrieverCache | None = None

    def prewarm(self, *, continuity_store: "ContinuityStore | None" = None) -> None:
        self._get_cache(continuity_store=continuity_store)

    def retrieve(
        self,
        query: str,
        *,
        continuity_store: "ContinuityStore | None" = None,
        now: datetime | None = None,
    ) -> RetrievalResult:
        query_text = str(query or "").strip()
        if not query_text:
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

        as_of = now or datetime.now(timezone.utc)
        cache = self._get_cache(continuity_store=continuity_store)
        if not cache.prepared:
            return RetrievalResult(memory_pack=MemoryPack(), ranked_atom_ids=[], scored_atoms=[])

        query_token_list = _tokenize(query_text)
        query_tokens = set(query_token_list)
        query_trigrams = _token_trigrams(query_token_list)
        query_ngrams = _char_ngrams(query_text)
        quoted_phrases = self._quoted_phrase_tokens(query_text)
        profile = self._classify_profile(query_text, query_tokens)
        time_intent = self._has_time_intent(query_text, query_tokens)
        lexical_limit, semantic_limit, temporal_limit, graph_limit = self._profile_channel_limits(profile)
        scored_atoms = self._score_candidates(cache, query_tokens, profile=profile)

        lexical_scores = {
            item.atom.atom_id: _lexical_similarity(query_tokens, item.token_set) for item in scored_atoms
        }
        bm25_scores = self._bm25_scores(cache, query_tokens)
        semantic_scores = {item.atom.atom_id: _jaccard(query_ngrams, item.ngrams) for item in scored_atoms}
        sequence_scores = self._sequence_alignment_scores(query_trigrams, scored_atoms)
        quote_scores = self._quote_alignment_scores(quoted_phrases, scored_atoms)
        temporal_scores = {item.atom.atom_id: _temporal_relevance(item.atom, as_of) for item in scored_atoms}

        lexical_admitted = {atom_id: score for atom_id, score in lexical_scores.items() if score >= 0.05}
        lexical_ids = self._top_ids(lexical_admitted or lexical_scores, lexical_limit)
        bm25_ids = self._top_ids(bm25_scores, lexical_limit)
        semantic_admitted = {atom_id: score for atom_id, score in semantic_scores.items() if score >= 0.10}
        semantic_ids = self._top_ids(semantic_admitted or semantic_scores, semantic_limit)
        sequence_admitted = {atom_id: score for atom_id, score in sequence_scores.items() if score >= 0.10}
        sequence_limit = max(4, semantic_limit // 2)
        sequence_ids = self._top_ids(sequence_admitted or sequence_scores, sequence_limit)
        quote_admitted = {atom_id: score for atom_id, score in quote_scores.items() if score >= 0.45}
        quote_limit = max(4, lexical_limit // 2)
        quote_ids = self._top_ids(quote_admitted or quote_scores, quote_limit)
        relevance_ids = set(lexical_ids + bm25_ids + semantic_ids + sequence_ids + quote_ids)
        temporal_scores_admitted = {atom_id: score for atom_id, score in temporal_scores.items() if atom_id in relevance_ids}
        temporal_ids = self._top_ids(temporal_scores_admitted, temporal_limit)
        focus_ids = set(lexical_ids + bm25_ids + semantic_ids + sequence_ids + quote_ids)
        graph_scores = {
            item.atom.atom_id: self._graph_relevance(item.atom.atom_id, focus_ids, cache.conflict_map) for item in scored_atoms
        }
        graph_admitted = {atom_id: score for atom_id, score in graph_scores.items() if score > 0.0}
        graph_ids = self._top_ids(graph_admitted or graph_scores, graph_limit)
        continuity_neighbors, arc_neighbors, shared_boosts, recognition_bonus = self._continuity_expansion(
            query_text, continuity_store
        )
        continuity_rank_scores: dict[str, float] = {}
        for atom_id in list(focus_ids):
            for candidate in continuity_neighbors.get(atom_id, set()).union(arc_neighbors.get(atom_id, set())):
                continuity_rank_scores[candidate] = max(continuity_rank_scores.get(candidate, 0.0), 0.30)
        for atom_id, boost in shared_boosts.items():
            continuity_rank_scores[atom_id] = max(continuity_rank_scores.get(atom_id, 0.0), _clamp01(boost))
        continuity_ids = self._top_ids(continuity_rank_scores, max(6, graph_limit))

        rrf_scores = self._rrf_fuse(
            {
                "lexical": lexical_ids,
                "bm25": bm25_ids,
                "semantic": semantic_ids,
                "sequence": sequence_ids,
                "quote": quote_ids,
                "temporal": temporal_ids,
                "graph": graph_ids,
                "continuity": continuity_ids,
            }
        )
        candidate_ids = [
            atom_id
            for atom_id, _ in sorted(rrf_scores.items(), key=lambda pair: (-pair[1], pair[0]))
            if atom_id in cache.atom_by_id
        ]
        if not candidate_ids:
            # Failsafe: keep retrieval live even when routing/selectors are too strict.
            candidate_ids = [item.atom.atom_id for item in scored_atoms[: self.config.retrieval.rerank_limit]]
        candidate_ids = self._guarded_candidate_ids(
            candidate_ids,
            profile=profile,
            conflict_map=cache.conflict_map,
        )

        scored: list[RetrievalScoredAtom] = []
        for atom_id in candidate_ids:
            atom = cache.atom_by_id[atom_id]
            lexical = lexical_scores.get(atom_id, 0.0)
            bm25 = bm25_scores.get(atom_id, 0.0)
            semantic = semantic_scores.get(atom_id, 0.0)
            sequence = sequence_scores.get(atom_id, 0.0)
            quote = quote_scores.get(atom_id, 0.0)
            temporal = temporal_scores.get(atom_id, 0.0)
            graph = graph_scores.get(atom_id, 0.0)
            continuity = _clamp01((atom.support_count / 4.0) * 0.6 + atom.salience * 0.4)
            score = self._fused_score(
                lexical=lexical,
                bm25=bm25,
                semantic=semantic,
                sequence=sequence,
                quote=quote,
                temporal=temporal,
                graph=graph,
                continuity=continuity,
                rrf=rrf_scores.get(atom_id, 0.0),
                conflict=atom.status is AtomStatus.CONFLICTED,
                support_count=atom.support_count,
                recognition_bonus=recognition_bonus.get(atom_id, 0.0),
                shared_language_bonus=shared_boosts.get(atom_id, 0.0),
                time_intent=time_intent,
            )
            scored.append(
                RetrievalScoredAtom(
                    atom=atom,
                    score=score,
                    lexical=lexical,
                    bm25=bm25,
                    semantic=semantic,
                    sequence=sequence,
                    quote=quote,
                    temporal=temporal,
                    graph=graph,
                    continuity=continuity,
                    rrf=rrf_scores.get(atom_id, 0.0),
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        ranked_atom_ids = [item.atom.atom_id for item in scored]
        build_result = self._build_memory_pack(scored, conflict_map=cache.conflict_map, atom_by_id=cache.atom_by_id)
        return RetrievalResult(
            memory_pack=build_result.pack,
            ranked_atom_ids=ranked_atom_ids,
            scored_atoms=scored,
            dropped_reasons=build_result.dropped_reasons,
        )

    def _classify_profile(self, query_text: str, query_tokens: set[str]) -> RetrievalProfile:
        lowered = query_text.lower()
        if any(phrase in lowered for phrase in _EXPLICIT_MEMORY_PHRASES):
            return "episode_heavy"
        if query_tokens.intersection(_EPISODE_KEYWORDS):
            return "episode_heavy"
        if query_tokens.intersection(_PREFERENCE_KEYWORDS):
            return "preference_relational"
        if query_tokens.intersection(_PROCEDURAL_KEYWORDS):
            return "procedural"
        if query_tokens.intersection(_FACTUAL_KEYWORDS):
            return "factual"
        return "mixed"

    def _has_time_intent(self, query_text: str, query_tokens: set[str]) -> bool:
        lowered = query_text.lower()
        if "when did" in lowered:
            return True
        return bool(query_tokens.intersection(_TIME_INTENT_KEYWORDS))

    def _profile_policy(self, profile: RetrievalProfile):
        return getattr(self.config.retrieval.router, profile)

    def _profile_channel_limits(self, profile: RetrievalProfile) -> tuple[int, int, int, int]:
        base_lexical = max(1, self.config.retrieval.top_k_lexical)
        base_semantic = max(1, self.config.retrieval.top_k_vector)
        base_temporal = max(1, self.config.retrieval.top_k_temporal)
        base_graph = max(1, self.config.retrieval.top_k_graph)
        router = self.config.retrieval.router
        policy = self._profile_policy(profile)
        lexical_floor = max(int(router.lexical_floor_min), base_lexical // max(1, int(router.lexical_floor_divisor)))
        semantic_floor = max(int(router.semantic_floor_min), base_semantic // max(1, int(router.semantic_floor_divisor)))
        temporal_floor = max(int(router.temporal_floor_min), base_temporal // max(1, int(router.temporal_floor_divisor)))
        graph_floor = max(int(router.graph_floor_min), base_graph // max(1, int(router.graph_floor_divisor)))
        return (
            self._scaled_limit(base_lexical, float(policy.lexical_scale), lexical_floor),
            self._scaled_limit(base_semantic, float(policy.semantic_scale), semantic_floor),
            self._scaled_limit(base_temporal, float(policy.temporal_scale), temporal_floor),
            self._scaled_limit(base_graph, float(policy.graph_scale), graph_floor),
        )

    def _scaled_limit(self, base: int, scale: float, floor: int) -> int:
        scaled = int(round(base * scale))
        return max(1, min(base, max(floor, scaled)))

    def _top_ids(self, scores: dict[str, float], limit: int) -> list[str]:
        return [item[0] for item in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]]

    def _rrf_fuse(self, channel_rankings: dict[str, list[str]]) -> dict[str, float]:
        policy = self.config.retrieval.rrf
        channel_weights = {
            "lexical": float(policy.lexical_weight),
            "bm25": float(policy.bm25_weight),
            "semantic": float(policy.semantic_weight),
            "sequence": float(policy.sequence_weight),
            "quote": float(policy.quote_weight),
            "temporal": float(policy.temporal_weight),
            "graph": float(policy.graph_weight),
            "continuity": float(policy.continuity_weight),
        }
        k = float(policy.rank_constant)
        totals: dict[str, float] = {}
        active_weight = 0.0
        for channel, ranked_ids in channel_rankings.items():
            if not ranked_ids:
                continue
            weight = channel_weights.get(channel, float(policy.fallback_channel_weight))
            active_weight += weight
            for rank, atom_id in enumerate(ranked_ids, start=1):
                totals[atom_id] = totals.get(atom_id, 0.0) + (weight / (k + float(rank)))
        if not totals or active_weight <= 0.0:
            return {}
        max_score = active_weight / (k + 1.0)
        return {atom_id: _clamp01(score / max_score) for atom_id, score in totals.items()}

    def _bm25_scores(self, cache: _RetrieverCache, query_tokens: set[str]) -> dict[str, float]:
        if not query_tokens or not cache.prepared:
            return {}
        policy = self.config.retrieval.bm25
        doc_count = max(1, len(cache.prepared))
        avg_doc_len = max(cache.avg_token_count, 1.0)
        posting_cutoff = max(int(policy.posting_cutoff_min), int(doc_count * float(policy.posting_cutoff_fraction)))
        k1 = float(policy.k1)
        b = float(policy.b)
        scores: dict[str, float] = {}
        for token in query_tokens:
            doc_freq = cache.token_doc_freq.get(token, 0)
            if doc_freq <= 0 or doc_freq > posting_cutoff:
                # High document-frequency terms are too noisy to use for BM25 ranking.
                continue
            idf = max(0.0, (doc_count - doc_freq + 0.5) / (doc_freq + 0.5))
            if idf <= 0.0:
                continue
            for atom_id in cache.token_postings.get(token, set()):
                prepared = cache.prepared_by_id.get(atom_id)
                if prepared is None:
                    continue
                tf = prepared.token_freq.get(token, 0)
                if tf <= 0:
                    continue
                norm = (1.0 - b) + b * (prepared.token_count / avg_doc_len)
                weight = (tf * (k1 + 1.0)) / (tf + k1 * norm)
                scores[atom_id] = scores.get(atom_id, 0.0) + idf * weight
        if not scores:
            return {}
        max_score = max(scores.values())
        relevance_floor = max(float(policy.relevance_floor_min), max_score * float(policy.relevance_floor_fraction))
        return {atom_id: score for atom_id, score in scores.items() if score >= relevance_floor}

    def _candidate_pool_floor(self, profile: RetrievalProfile) -> int:
        router = self.config.retrieval.router
        policy = self._profile_policy(profile)
        rerank_limit = max(1, int(self.config.retrieval.rerank_limit))
        floor = max(int(policy.candidate_pool_floor), rerank_limit * 2)
        if profile in {"episode_heavy", "mixed"}:
            floor = max(floor, rerank_limit * 3)
        return min(int(router.max_candidate_pool_floor), floor)

    def _profile_candidate_cap(self, profile: RetrievalProfile) -> int:
        policy = self._profile_policy(profile)
        rerank_limit = max(1, int(self.config.retrieval.rerank_limit))
        scaled = int(round(rerank_limit * float(policy.candidate_cap_ratio)))
        cap = max(int(policy.candidate_cap_floor), scaled)
        return max(1, min(rerank_limit, cap))

    def _guarded_candidate_ids(
        self,
        candidate_ids: list[str],
        *,
        profile: RetrievalProfile,
        conflict_map: dict[str, set[str]],
    ) -> list[str]:
        cap = self._profile_candidate_cap(profile)
        if len(candidate_ids) <= cap:
            return list(candidate_ids)

        selected = list(candidate_ids[:cap])
        required_neighbors: set[str] = set()
        # Guard the initial evidence slice before early-stop trims candidate fanout.
        for atom_id in selected[: int(self.config.retrieval.pack.guarded_neighbor_scan_limit)]:
            required_neighbors.update(conflict_map.get(atom_id, set()))
        if not required_neighbors:
            return selected

        selected_set = set(selected)
        pack = self.config.retrieval.pack
        extra_budget = max(
            int(pack.guarded_extra_budget_min),
            min(int(pack.guarded_extra_budget_max), cap // max(1, int(pack.guarded_extra_budget_ratio_divisor))),
        )
        extras_added = 0
        for atom_id in candidate_ids[cap:]:
            if atom_id in required_neighbors and atom_id not in selected_set:
                selected.append(atom_id)
                selected_set.add(atom_id)
                extras_added += 1
                if extras_added >= extra_budget:
                    break
        return selected

    def _score_candidates(
        self,
        cache: _RetrieverCache,
        query_tokens: set[str],
        *,
        profile: RetrievalProfile,
    ) -> list[_PreparedAtom]:
        if not query_tokens:
            return cache.prepared

        atom_count = max(1, len(cache.prepared))
        posting_cutoff = max(64, int(atom_count * 0.35))
        candidate_ids: set[str] = set()
        for token in query_tokens:
            posting = cache.token_postings.get(token)
            if not posting:
                continue
            if len(posting) > posting_cutoff:
                # Ignore very common terms that add noise and cost.
                continue
            candidate_ids.update(posting)

        if not candidate_ids:
            return cache.prepared

        # Keep a bounded floor to preserve recall without over-expanding fanout.
        min_pool = min(atom_count, self._candidate_pool_floor(profile))
        if len(candidate_ids) < min_pool:
            for atom_id in cache.temporal_seed_ids:
                candidate_ids.add(atom_id)
                if len(candidate_ids) >= min_pool:
                    break

        scored = [cache.prepared_by_id[atom_id] for atom_id in candidate_ids if atom_id in cache.prepared_by_id]
        if not scored:
            return cache.prepared
        return scored

    def _sequence_alignment_scores(
        self,
        query_trigrams: set[tuple[str, str, str]],
        scored_atoms: list[_PreparedAtom],
    ) -> dict[str, float]:
        if not query_trigrams:
            return {}
        scale = float(max(1, len(query_trigrams)))
        scores: dict[str, float] = {}
        for item in scored_atoms:
            overlap = len(query_trigrams.intersection(item.token_trigrams))
            if overlap <= 0:
                continue
            scores[item.atom.atom_id] = _clamp01(overlap / scale)
        return scores

    def _quoted_phrase_tokens(self, query_text: str) -> list[list[str]]:
        phrases: list[list[str]] = []
        for match in _QUOTED_PHRASE_RE.finditer(query_text):
            phrase = (match.group(1) or match.group(2) or "").strip()
            phrase_tokens = _tokenize(phrase)
            if len(phrase_tokens) >= 4:
                phrases.append(phrase_tokens)
        return phrases

    def _quote_alignment_scores(
        self,
        quoted_phrases: list[list[str]],
        scored_atoms: list[_PreparedAtom],
    ) -> dict[str, float]:
        if not quoted_phrases:
            return {}

        phrase_data: list[tuple[set[str], set[tuple[str, str, str]], set[str], str]] = []
        for phrase_tokens in quoted_phrases:
            phrase_data.append(
                (
                    set(phrase_tokens),
                    _token_trigrams(phrase_tokens),
                    _char_ngrams(" ".join(phrase_tokens)),
                    " ".join(phrase_tokens),
                )
            )

        scores: dict[str, float] = {}
        for item in scored_atoms:
            atom_joined = " ".join(item.token_list)
            best = 0.0
            for phrase_token_set, phrase_trigrams, phrase_ngrams, phrase_joined in phrase_data:
                lexical = _lexical_similarity(phrase_token_set, item.token_set)
                trigram = (
                    len(phrase_trigrams.intersection(item.token_trigrams)) / max(1, len(phrase_trigrams))
                    if phrase_trigrams
                    else 0.0
                )
                ngram = _jaccard(phrase_ngrams, item.ngrams)
                score = max(
                    0.45 * lexical + 0.45 * trigram + 0.10 * ngram,
                    0.60 * trigram + 0.40 * ngram,
                )
                if phrase_joined and phrase_joined in atom_joined:
                    score = max(score, 0.95)
                best = max(best, score)
            if best >= 0.20:
                scores[item.atom.atom_id] = _clamp01(best)
        return scores

    def _continuity_expansion(
        self,
        query: str,
        continuity_store: "ContinuityStore | None",
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, float], dict[str, float]]:
        if continuity_store is None:
            return {}, {}, {}, {}
        expansion = continuity_store.expansion_for_query(query)
        return (
            expansion.constellation_neighbors,
            expansion.arc_neighbors,
            expansion.shared_boosts,
            expansion.recognition_bonus,
        )

    def _graph_relevance(self, atom_id: str, focus_ids: set[str], conflict_map: dict[str, set[str]]) -> float:
        neighbors = conflict_map.get(atom_id, set())
        if not neighbors:
            return 0.0
        overlap = len(neighbors.intersection(focus_ids))
        return _clamp01((overlap / max(len(neighbors), 1)) + min(len(neighbors), 3) * 0.1)

    def _store_scope_token(self) -> Hashable | None:
        scope_fn = getattr(self.store, "cache_scope", None)
        if callable(scope_fn):
            try:
                value = scope_fn()
                if isinstance(value, Hashable):
                    return value
                return None
            except Exception:
                return None
        return f"{type(self.store).__name__}:{id(self.store)}"

    def _cache_policy_token(self) -> tuple[Hashable, ...]:
        retrieval = self.config.retrieval
        router = retrieval.router
        bm25 = retrieval.bm25
        rrf = retrieval.rrf
        pack = retrieval.pack
        cache = retrieval.cache
        router_profiles = (
            ("episode_heavy", self._profile_policy("episode_heavy")),
            ("preference_relational", self._profile_policy("preference_relational")),
            ("procedural", self._profile_policy("procedural")),
            ("factual", self._profile_policy("factual")),
            ("mixed", self._profile_policy("mixed")),
        )
        return (
            "retrieval",
            int(retrieval.rerank_limit),
            int(retrieval.top_k_lexical),
            int(retrieval.top_k_vector),
            int(retrieval.top_k_temporal),
            int(retrieval.top_k_graph),
            int(router.lexical_floor_min),
            int(router.semantic_floor_min),
            int(router.temporal_floor_min),
            int(router.graph_floor_min),
            int(router.lexical_floor_divisor),
            int(router.semantic_floor_divisor),
            int(router.temporal_floor_divisor),
            int(router.graph_floor_divisor),
            int(router.max_candidate_pool_floor),
            tuple(
                (
                    name,
                    float(policy.lexical_scale),
                    float(policy.semantic_scale),
                    float(policy.temporal_scale),
                    float(policy.graph_scale),
                    int(policy.candidate_pool_floor),
                    float(policy.candidate_cap_ratio),
                    int(policy.candidate_cap_floor),
                )
                for name, policy in router_profiles
            ),
            int(bm25.posting_cutoff_min),
            float(bm25.posting_cutoff_fraction),
            float(bm25.k1),
            float(bm25.b),
            float(bm25.relevance_floor_min),
            float(bm25.relevance_floor_fraction),
            float(rrf.rank_constant),
            float(rrf.lexical_weight),
            float(rrf.bm25_weight),
            float(rrf.semantic_weight),
            float(rrf.sequence_weight),
            float(rrf.quote_weight),
            float(rrf.temporal_weight),
            float(rrf.graph_weight),
            float(rrf.continuity_weight),
            float(rrf.fallback_channel_weight),
            int(pack.core_limit),
            int(pack.context_limit),
            int(pack.conflict_limit),
            int(pack.continuity_limit),
            int(pack.guarded_neighbor_scan_limit),
            int(pack.guarded_extra_budget_min),
            int(pack.guarded_extra_budget_max),
            int(pack.guarded_extra_budget_ratio_divisor),
            bool(cache.fail_closed_on_uncertain_store_scope),
            bool(cache.fail_closed_on_uncertain_continuity_scope),
        )

    def _continuity_cache_token(self, continuity_store: "ContinuityStore | None") -> Hashable | None:
        if continuity_store is None:
            return ("none",)

        token_fn = getattr(continuity_store, "cache_token", None)
        if callable(token_fn):
            try:
                value = token_fn()
                if isinstance(value, Hashable):
                    return value
                return None
            except Exception:
                return None

        snapshot_fn = getattr(continuity_store, "snapshot_view", None)
        if callable(snapshot_fn):
            try:
                revision, _snapshot = snapshot_fn()
                return ("snapshot_revision", int(revision))
            except Exception:
                return None
        return None

    def _cache_token(self, *, continuity_store: "ContinuityStore | None" = None) -> Hashable | None:
        token_fn = getattr(self.store, "cache_token", None)
        if callable(token_fn):
            try:
                store_token = token_fn()
                if not isinstance(store_token, Hashable):
                    return None
                scope_token = self._store_scope_token()
                if scope_token is None and bool(self.config.retrieval.cache.fail_closed_on_uncertain_store_scope):
                    # Fail closed: bypass cache if store-scope token is uncertain.
                    return None
                continuity_token = self._continuity_cache_token(continuity_store)
                if (
                    continuity_store is not None
                    and continuity_token is None
                    and bool(self.config.retrieval.cache.fail_closed_on_uncertain_continuity_scope)
                ):
                    # Fail closed: bypass cache if continuity token coverage is uncertain.
                    return None
                return (
                    _CACHE_TOKEN_SCHEMA,
                    scope_token if scope_token is not None else ("uncertain-store-scope",),
                    store_token,
                    continuity_token if continuity_token is not None else ("none",),
                    self._cache_policy_token(),
                    _CACHE_CHANNELS,
                )
            except Exception:
                return None
        return None

    def _conflict_map(self, atoms: list[MemoryAtom]) -> dict[str, set[str]]:
        graph_fn = getattr(self.store, "conflict_map", None)
        if callable(graph_fn):
            try:
                value = graph_fn()
                if isinstance(value, dict):
                    normalized: dict[str, set[str]] = {}
                    for atom_id, neighbors in value.items():
                        normalized[str(atom_id)] = {str(item) for item in set(neighbors)}
                    return normalized
            except Exception:
                pass
        return {atom.atom_id: self.store.conflict_neighbors(atom.atom_id) for atom in atoms}

    def _get_cache(self, *, continuity_store: "ContinuityStore | None" = None) -> _RetrieverCache:
        cache_token = self._cache_token(continuity_store=continuity_store)
        if cache_token is not None and self._cache is not None and self._cache.token == cache_token:
            return self._cache

        atoms = [atom for atom in self.store.list_atoms() if atom.status is not AtomStatus.TOMBSTONED]
        prepared: list[_PreparedAtom] = []
        for atom in atoms:
            tokens = _tokenize(atom.canonical_text)
            token_freq: dict[str, int] = {}
            for token in tokens:
                token_freq[token] = token_freq.get(token, 0) + 1
            prepared.append(
                _PreparedAtom(
                    atom=atom,
                    token_list=tokens,
                    token_freq=token_freq,
                    token_count=max(1, len(tokens)),
                    token_set=set(token_freq.keys()),
                    token_trigrams=_token_trigrams(tokens),
                    ngrams=_char_ngrams(atom.canonical_text),
                )
            )
        prepared_by_id = {item.atom.atom_id: item for item in prepared}
        atom_by_id = {atom.atom_id: atom for atom in atoms}
        conflict_map = self._conflict_map(atoms)
        temporal_seed_ids = [
            atom.atom_id
            for atom in sorted(
                atoms,
                key=lambda item: (item.updated_at, item.salience, item.support_count),
                reverse=True,
            )[:1024]
        ]
        token_postings: dict[str, set[str]] = {}
        for item in prepared:
            atom_id = item.atom.atom_id
            for tok in item.token_set:
                token_postings.setdefault(tok, set()).add(atom_id)
        token_doc_freq = {token: len(atom_ids) for token, atom_ids in token_postings.items()}
        avg_token_count = (sum(item.token_count for item in prepared) / len(prepared)) if prepared else 1.0
        cache = _RetrieverCache(
            token=cache_token if cache_token is not None else object(),
            prepared=prepared,
            prepared_by_id=prepared_by_id,
            atom_by_id=atom_by_id,
            conflict_map=conflict_map,
            token_postings=token_postings,
            token_doc_freq=token_doc_freq,
            avg_token_count=avg_token_count,
            temporal_seed_ids=temporal_seed_ids,
        )
        self._cache = cache
        return cache

    def _fused_score(
        self,
        *,
        lexical: float,
        bm25: float,
        semantic: float,
        sequence: float,
        quote: float,
        temporal: float,
        graph: float,
        continuity: float,
        rrf: float,
        conflict: bool,
        support_count: int,
        recognition_bonus: float,
        shared_language_bonus: float,
        time_intent: bool,
    ) -> float:
        temporal_weight = 0.20 if not time_intent else 0.08
        channel_score = (
            0.22 * semantic
            + 0.18 * lexical
            + temporal_weight * temporal
            + 0.12 * graph
            + 0.10 * continuity
            + 0.18 * _clamp01(bm25 / 3.0)
        )
        score = 0.55 * channel_score + 0.45 * _clamp01(rrf)
        score += min(0.18, max(0.0, sequence) * 0.18)
        score += min(0.20, max(0.0, quote) * 0.20)
        if conflict:
            score -= 0.08
        if support_count > 1:
            score += min(support_count, 4) * 0.015
        if temporal < 0.2 and support_count < 2 and not time_intent:
            score -= 0.10
        score += max(-0.06, min(0.06, recognition_bonus))
        score += max(0.0, min(0.20, shared_language_bonus))
        return _clamp01(score)

    def _build_memory_pack(
        self,
        scored: list[RetrievalScoredAtom],
        *,
        conflict_map: dict[str, set[str]],
        atom_by_id: dict[str, MemoryAtom],
    ) -> _PackBuildResult:
        core: list[MemoryPackItem] = []
        context: list[MemoryPackItem] = []
        conflict: list[MemoryPackItem] = []
        continuity: list[MemoryPackItem] = []
        used: set[str] = set()
        non_conflict_signatures: set[str] = set()
        dropped_reasons: dict[str, str] = {}

        pack_policy = self.config.retrieval.pack
        conflict_budget = max(0, int(pack_policy.conflict_limit))
        for item in scored:
            atom = item.atom
            atom_id = atom.atom_id
            if atom_id in used:
                dropped_reasons.setdefault(atom_id, "DUPLICATE")
                continue
            if atom.status is AtomStatus.CONFLICTED:
                if len(conflict) < conflict_budget:
                    conflict.append(_memory_item(atom, confidence=item.score))
                    used.add(atom_id)
                else:
                    dropped_reasons.setdefault(atom_id, "BUDGET_CONFLICT")
                continue
            signature = _dedupe_text_key(atom.canonical_text)
            if signature in non_conflict_signatures:
                dropped_reasons.setdefault(atom_id, "DUPLICATE")
                continue
            if len(core) < int(pack_policy.core_limit):
                core.append(_memory_item(atom, confidence=item.score))
                used.add(atom_id)
                non_conflict_signatures.add(signature)
                continue
            if len(context) < int(pack_policy.context_limit):
                context.append(_memory_item(atom, confidence=item.score))
                used.add(atom_id)
                non_conflict_signatures.add(signature)
                continue
            dropped_reasons.setdefault(atom_id, "BUDGET")

        required_neighbors: set[str] = set()
        for atom_id in used:
            required_neighbors.update(conflict_map.get(atom_id, set()))
        for item in scored:
            atom_id = item.atom.atom_id
            if atom_id not in required_neighbors or atom_id in used:
                continue
            if atom_id not in atom_by_id:
                dropped_reasons.setdefault(atom_id, "CONFLICT_REQUIRED_BUT_DROPPED")
                continue
            if len(conflict) >= conflict_budget:
                dropped_reasons.setdefault(atom_id, "CONFLICT_REQUIRED_BUT_DROPPED")
                break
            conflict.append(_memory_item(atom_by_id[atom_id], confidence=item.score))
            used.add(atom_id)
        covered_neighbors = {entry.atom_id for entry in conflict}
        coverage_incomplete = any(neighbor not in covered_neighbors for neighbor in required_neighbors)
        if coverage_incomplete:
            # Fail closed: do not permit confident PASS off a one-sided evidence pack.
            evicted_ids = {entry.atom_id for entry in core + context + continuity}
            for evicted_id in evicted_ids:
                dropped_reasons.setdefault(evicted_id, "CONFLICT_REQUIRED_BUT_DROPPED")
            core = []
            context = []
            continuity = []
            for neighbor in required_neighbors:
                if neighbor not in covered_neighbors:
                    dropped_reasons.setdefault(neighbor, "CONFLICT_REQUIRED_BUT_DROPPED")

        for item in scored:
            atom = item.atom
            if atom.atom_id in used:
                continue
            if len(continuity) >= int(pack_policy.continuity_limit):
                break
            signature = _dedupe_text_key(atom.canonical_text)
            if signature in non_conflict_signatures:
                dropped_reasons.setdefault(atom.atom_id, "DUPLICATE")
                continue
            if atom.support_count >= 2 or atom.salience >= 0.65:
                continuity.append(_memory_item(atom, confidence=item.score))
                used.add(atom.atom_id)
                non_conflict_signatures.add(signature)
                continue
            dropped_reasons.setdefault(atom.atom_id, "LOW_RELEVANCE")

        for item in scored:
            atom_id = item.atom.atom_id
            if atom_id in used:
                continue
            if atom_id not in dropped_reasons:
                dropped_reasons[atom_id] = "BUDGET"

        pack_confidence = self._pack_confidence(core=core, scored=scored)
        return _PackBuildResult(
            pack=memory_pack_from_items(
                core,
                context=context,
                conflict=conflict,
                continuity=continuity,
                pack_confidence=pack_confidence,
            ),
            dropped_reasons=dropped_reasons,
        )

    def _pack_confidence(self, *, core: list[MemoryPackItem], scored: list[RetrievalScoredAtom]) -> float:
        confidence_values = [_clamp01(item.confidence) for item in list(core or [])]
        if not confidence_values:
            return 0.0

        base_confidence = _clamp01(sum(confidence_values) / len(confidence_values))
        scored_by_id = {item.atom.atom_id: item for item in scored}
        alignment_peak = 0.0
        for item in core[:3]:
            scored_item = scored_by_id.get(item.atom_id)
            if scored_item is None:
                continue
            alignment_peak = max(
                alignment_peak,
                _clamp01(max(float(scored_item.quote), float(scored_item.sequence))),
            )

        # High sequence/quote alignment is a strong direct-anchor signal.
        if alignment_peak < 0.65:
            return base_confidence
        alignment_bonus = min(0.18, max(0.0, alignment_peak - 0.65) * 0.80)
        return _clamp01(base_confidence + alignment_bonus)
