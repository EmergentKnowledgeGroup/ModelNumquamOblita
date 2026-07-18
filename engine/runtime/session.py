from __future__ import annotations

import re
import threading
import time
import logging
import inspect
import json
import hashlib
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..continuity import ContinuityStore
from ..config import NumquamOblitaConfig, default_config
from ..contracts import (
    AtomType,
    CandidateAtom,
    MemoryPack,
    MemoryPackItem,
    RetrievalDiagnosticsContract,
    RetrievalDroppedAtomContract,
    RetrievalHelperLaneContract,
    RetrievalOverrideAuditContract,
    RetrievalOverrideRequestContract,
    RetrievalSelectedAtomContract,
    SourceRef,
    contract_to_dict,
    memory_pack_from_items,
)
from ..memory import (
    EvidenceRegistration,
    InMemoryProvisionalMemoryStore,
    ProvisionalMemoryCandidate,
    ProvisionalMemoryEvent,
    ProvisionalMemoryEventType,
    ProvisionalMemoryKind,
    ProvisionalMemoryRecord,
    ProvisionalMemoryStatus,
    ProvisionalSearchHit,
    SqliteAtomStore,
    SqliteProvisionalMemoryStore,
    MutationReviewQueue,
    MaintenancePolicy,
    run_maintenance,
)
from ..memory.proposal_store import (
    InMemoryProposalStore,
    ProposalCandidate,
    ProposalKind,
    ProposalRecord,
    SqliteProposalStore,
)
from ..retrieval import (
    ClaimCheck,
    ClaimVerifier,
    EpisodeCardIndex,
    EpisodeHit,
    MemoryRetriever,
    RetrievalResult,
    VerificationDecision,
    VerificationResult,
)
from .scratchpad import (
    WorkSessionScope,
    WorkSessionScratchpadStore,
    build_diagnostic_task_map,
    estimate_context_tokens,
    resolve_scope,
    resolve_scratchpad_root,
)
from ..memory.content_safety import SecretDetectedError, assert_safe_content
from .integration_handles import IntegrationHandleError, IntegrationHandleSigner, normalized_content_digest

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_QUOTE_RE = re.compile(r"['\"]([^'\"]{2,120})['\"]")
_MIXING_QUOTED_OPTIONS_RE = re.compile(r"was it\s+\"([^\"]{2,120})\"\s+or\s+\"([^\"]{2,120})\"", re.IGNORECASE)
_MIXING_PLAIN_OPTIONS_RE = re.compile(
    r"was it\s+([A-Za-z0-9][A-Za-z0-9 '\-_]{1,80})\s+or\s+([A-Za-z0-9][A-Za-z0-9 '\-_]{1,80})",
    re.IGNORECASE,
)
_ABOUT_FOCUS_RE = re.compile(r"(?:about|regarding|on|re)\s+([A-Za-z0-9][A-Za-z0-9 '\-_]{2,120})", re.IGNORECASE)
_WHO_FOCUS_RE = re.compile(r"(?:who is|who's|what is|what's)\s+([A-Za-z0-9][A-Za-z0-9 '\-_]{2,96})", re.IGNORECASE)
_EVENT_FOCUS_RE = re.compile(
    r"(?:what happened to|tell me about|what do you know about|why does|why did|why is)\s+([A-Za-z0-9][A-Za-z0-9 '\-_]{2,96})",
    re.IGNORECASE,
)
_SESSION_RECALL_PHRASES = (
    "quote it",
    "quote this",
    "quote that",
    "what exactly did i say",
    "what exactly did you say",
    "what did i say",
    "what did you say",
    "did i say",
    "did you say",
    "assistant said",
    "user said",
    "who said",
    "verbatim",
    "exact wording",
    "exact quote",
    "word for word",
)
_INFO_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-_]{2,}")
_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-_]{2,}")
_DATE_LIKE_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|\d{4}|\d{1,2}(?:st|nd|rd|th)?)\b",
    re.IGNORECASE,
)
_INFO_STOPWORDS = {
    "anything",
    "about",
    "again",
    "also",
    "because",
    "could",
    "from",
    "have",
    "just",
    "memory",
    "remember",
    "should",
    "something",
    "stuff",
    "tell",
    "them",
    "there",
    "these",
    "this",
    "thing",
    "what",
    "when",
    "where",
    "with",
    "would",
    "your",
    "question",
    "quick",
    "joke",
    "hear",
    "want",
}
_NAME_FREQ_IGNORE_TOKENS = _INFO_STOPWORDS.union(
    {
        "user",
        "assistant",
        "developer",
        "system",
        "tool",
        "dyad",
        "project",
        "projects",
        "topic",
        "topics",
        "thing",
        "things",
        "someone",
        "anyone",
        "everyone",
        "day",
        "today",
        "talk",
        "mood",
        "feeling",
        "feelings",
        "things",
        "going",
        "share",
        "before",
        "continue",
        "fun",
        "none",
        "here",
        "there",
        "this",
        "that",
    }
)
_FOCUS_CANDIDATE_IGNORE_TOKENS = _NAME_FREQ_IGNORE_TOKENS.union(
    {
        "does",
        "did",
        "happened",
        "matter",
        "he",
        "her",
        "hers",
        "him",
        "his",
        "she",
        "they",
        "them",
        "their",
        "why",
    }
)
_SMALLTALK_PREFIX_RE = re.compile(r"^(hi|hello|hey|yo|sup)\b", re.IGNORECASE)
_CASUAL_PREFIX_RE = re.compile(
    r"^(can i|could i|do you want to|want to|i heard|i saw|i read|by the way|btw)\b",
    re.IGNORECASE,
)
_SMALLTALK_PHRASES = (
    "how are you",
    "good morning",
    "good afternoon",
    "good evening",
    "thank you",
    "thanks",
    "want to hear it",
    "heard a joke",
    "tell me a joke",
    "just checking in",
    "quick check-in",
    "quick check in",
    "keep this light",
    "simple chat turn",
    "no recall required",
    "normal reply",
    "small talk",
)
_ROUTINE_SKIP_PHRASES = (
    "just checking in",
    "quick check-in",
    "quick check in",
    "keep this light",
    "simple chat turn",
    "no recall required",
    "normal reply",
    "quick small talk",
)
_STM_ONLY_PHRASES = (
    "in this chat",
    "in this thread",
    "continue from above",
    "continue this thread",
    "as i said",
    "as we said",
    "what i just said",
)
_LTM_DEEP_PHRASES = (
    "remember",
    "recall",
    "what did we",
    "did we ever",
    "last time",
    "you said",
    "from before",
    "previously",
)
_MEMORY_SIGNAL_PHRASES = (
    "we talked about",
    "we discussed",
    "you mentioned",
    "you told me",
    "status of",
    "update me on",
    "our conversation",
    "from earlier",
    "back then",
    "last week",
    "last month",
    "last year",
)
_FORCE_LTM_LIGHT_PHRASES = (
    "what do i know about",
    "do i know anything about",
    "what did i say about",
    "what did we say about",
    "what happened before",
    "what happened after",
    "have we talked about",
    "have i been here before",
    "what was our last conversation",
    "what's my relationship with",
    "what is my relationship with",
    "my relationship with",
    "what's my history with",
    "what is my history with",
    "my history with",
    "what matters to me",
    "what do i care about",
    "what have i written",
    "what projects are we working on",
    "who am i",
    "how did ",
    "has anyone told me",
)
_DESCRIPTIVE_RECALL_ANCHOR_TOKENS = {
    "build",
    "built",
    "called",
    "chose",
    "line",
    "moment",
    "named",
    "origin",
    "phrase",
    "promise",
    "quote",
    "start",
    "started",
    "story",
}
_CONSUMER_META_SYSTEM_TOKENS = {
    "anchor",
    "anchors",
    "atom",
    "atoms",
    "citation",
    "citations",
    "evidence",
    "ltm",
    "memory",
    "mcp",
    "orient",
    "pack",
    "query",
    "queries",
    "recall",
    "retrieval",
    "route",
    "routing",
    "search",
    "session",
    "sessions",
    "stm",
    "tool",
    "tools",
}
_CONSUMER_META_INSTRUCTION_TOKENS = {
    "answer",
    "call",
    "exclude",
    "include",
    "must",
    "need",
    "needs",
    "prefer",
    "return",
    "search",
    "should",
    "use",
}
_CONSUMER_META_PHRASES = (
    "any query about",
    "any question about",
    "should search memory first",
    "search memory first",
    "search the atom store",
    "use explore.orient",
    "evidence pack",
    "retrieval behavior",
)
_CONSUMER_META_CONVERSATION_TOKENS = {
    "atom",
    "atoms",
    "continuity",
    "evaluation",
    "lexical",
    "prompt",
    "prompts",
    "pull",
    "query",
    "queries",
    "retrieval",
    "semantic",
    "test",
    "testing",
    "unit",
}
_CONSUMER_META_CONVERSATION_PHRASES = (
    "semantic pull",
    "lexical match",
    "retrieval test",
    "testing the system",
    "unit test",
)
_PROVISIONAL_NOISE_PHRASES = (
    "yeah i dunno",
    "yeah i don't know",
    "yeah whatever",
    "i dunno man",
    "not sure man",
)
_PROVISIONAL_PREFERENCE_HINTS = (
    " like ",
    " likes ",
    " love ",
    " loves ",
    " prefer ",
    " prefers ",
    " favorite ",
    " favourite ",
    " hate ",
    " hates ",
    " dislike ",
    " dislikes ",
    " doesn't want ",
    " does not want ",
    " wants ",
)
_PROVISIONAL_PLAN_HINTS = (
    "tomorrow",
    "later",
    "next",
    "going to",
    "gonna",
    "we will",
    "i will",
    "we should",
)
_PROVISIONAL_CORRECTION_HINTS = (
    "actually",
    "finally",
    "came around",
    "changed",
    "instead",
    "no longer",
    "not anymore",
    "used to",
)
_PROVISIONAL_SELF_CLAIM_HINTS = (
    "i am",
    "i'm",
    "i feel",
    "i felt",
    "i love",
    "i trust",
    "i want",
    "i remember",
    "i'm becoming",
    "i am becoming",
)
_PROPOSAL_OTHER_PERSON_STATE_HINTS = (
    " he feels ",
    " she feels ",
    " they feel ",
    " feels defeated",
    " feels hurt",
    " feels broken",
    " feels scared",
    " feels lost",
    " feels unsafe",
    " seems defeated",
    " seems hurt",
    " seems broken",
    " seems scared",
    " seems lost",
    " seems unsafe",
    " maybe that's why ",
    " maybe thats why ",
)
_PROPOSAL_IDENTITY_HINTS = (
    " is the kind of person ",
    " is the kind of guy ",
    " is the kind of woman ",
    " who he is ",
    " who she is ",
    " who they are ",
)
_PROPOSAL_RELATIONSHIP_HINTS = (
    " relationship with ",
    " means to me ",
    " means that much to me ",
    " what he is to me ",
    " what she is to me ",
    " what they are to me ",
)
_PROPOSAL_MOTIVE_HINTS = (
    " because he cares ",
    " because she cares ",
    " because they care ",
    " because he wants ",
    " because she wants ",
    " because they want ",
    " because he's trying ",
    " because she is trying ",
    " because they are trying ",
)
_PROPOSAL_LIFE_STORY_HINTS = (
    " this is the story of ",
    " has always been the kind of person ",
    " defines who ",
    " defines what ",
)
_SOFT_CLOSE_HINTS = (
    "going to bed",
    "go to bed",
    "go crash",
    "going to crash",
    "call it a night",
    "pick this up tomorrow",
    "wrap this tomorrow",
    "catch this tomorrow",
    "wrapping up",
)
_NAMED_ENTITY_QUESTION_RE = re.compile(
    r"\b(?i:(?:what(?:'s| is)|who(?:'s| is)|tell me about))\s+([A-Z][A-Za-z0-9'\-_]{2,})"
)
_ROUTE_REASON_TEXT = {
    "smalltalk_routine": "Routine chat detected; memory retrieval skipped.",
    "casual_prompt_no_recall": "Casual prompt detected with no memory signal; memory retrieval skipped.",
    "routine_hard_cap": "Routine chat guardrail blocked memory retrieval because no explicit memory request was found.",
    "ambiguous_low_signal_skip": "Prompt is low-signal and ambiguous; memory retrieval skipped.",
    "thread_local_reference": "Prompt references recent thread context; STM route selected.",
    "explicit_memory_request": "Prompt explicitly asks for memory recall; deep route selected.",
    "memory_signal_probe": "Prompt carries memory-like signals; light retrieval route selected.",
    "default_memory_probe": "Default memory probe route selected for non-routine prompts.",
    "verbatim_session_recall": "Quote/session-recall cue detected; deep retrieval route selected.",
    "retrieval_query_override": "Caller provided retrieval query override; light retrieval route selected.",
    "high_risk_escalation": "High-risk signal escalated retrieval to deep route.",
    "memory_preference_chat_first": "Memory preference is chat-first; retrieval was reduced.",
    "memory_preference_memory_assist": "Memory preference is memory-assist; retrieval was expanded.",
    "memory_preference_session_recall": "Memory preference is session-recall; deep quote/session retrieval was forced.",
    "identity_relationship_probe": "Identity/relationship query detected; retrieval forced to memory assist.",
    "name_frequency_trigger": "Known recurring name/entity detected; retrieval forced to memory assist.",
}

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_estimate(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped.split()))


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[idx : idx + n] for idx in range(len(normalized) - n + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def _mixing_options_from_text(text: str) -> tuple[str, str] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    quoted = _MIXING_QUOTED_OPTIONS_RE.search(raw)
    if quoted:
        left = str(quoted.group(1) or "").strip()
        right = str(quoted.group(2) or "").strip()
        if left and right:
            return left, right
    plain = _MIXING_PLAIN_OPTIONS_RE.search(raw)
    if plain:
        left = str(plain.group(1) or "").strip(" ,.?")
        right = str(plain.group(2) or "").strip(" ,.?")
        if left and right:
            return left, right
    return None


def _option_support_score(option_text: str, evidence_text: str) -> float:
    option_tokens = [token for token in _tokenize(option_text) if len(token) >= 3 and token not in _INFO_STOPWORDS]
    if not option_tokens:
        return 0.0
    evidence_tokens = set(_tokenize(evidence_text))
    if not evidence_tokens:
        return 0.0
    hit_count = float(sum(1 for token in option_tokens if token in evidence_tokens))
    return hit_count / float(len(option_tokens))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(slots=True)
class TurnTelemetry:
    retrieval_ms: float
    verifier_ms: float
    total_ms: float
    input_tokens: int
    output_tokens: int
    turn_cost_usd: float
    cumulative_tokens: int
    cumulative_cost_usd: float


@dataclass(slots=True)
class WritebackEvent:
    event_id: str
    turn_id: str
    status: str
    created_at: datetime
    processed_at: datetime | None = None
    error: str | None = None


@dataclass(slots=True)
class TurnTrace:
    turn_id: str
    session_id: str
    timestamp: datetime
    user_text: str
    response_text: str
    decision: str
    citations: list[str]
    pack_confidence: float
    retrieved_atom_ids: list[str]
    memory_mode: str
    memory_route: str
    route_reason: str
    route_reason_text: str
    retrieval_passes: int
    retrieval_query_tokens: int
    retrieval_stop_reason: str
    retrieval_override: RetrievalOverrideAuditContract
    retrieval_diagnostics: dict[str, Any]
    memory_preference: str
    short_term_hits: int
    memory_cards: list[dict[str, Any]]
    telemetry: TurnTelemetry
    claim_checks: list[dict[str, Any]]
    writeback_event_id: str | None = None


@dataclass(slots=True)
class RuntimeStats:
    turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    p95_latency_ms: float = 0.0
    stm_primary_turns: int = 0
    hybrid_turns: int = 0
    ltm_only_turns: int = 0
    route_none_turns: int = 0
    route_stm_only_turns: int = 0
    route_ltm_light_turns: int = 0
    route_ltm_deep_turns: int = 0
    recognition_events: int = 0
    recognition_rate: float = 0.0


@dataclass(slots=True)
class ShortTermNote:
    note_id: str
    turn_id: str
    role: str
    text: str
    created_at: datetime


@dataclass(slots=True)
class FrontDeskDecision:
    route: str
    reason: str


@dataclass(slots=True)
class SessionState:
    session_id: str
    label: str
    label_auto: bool
    created_at: datetime
    updated_at: datetime
    short_term: deque[ShortTermNote]
    turn_ids: list[str] = field(default_factory=list)
    rolling_summary: str = ""
    summary_segments: deque[str] = field(default_factory=deque)
    soft_close_hint_at: datetime | None = None
    soft_close_hint_text: str = ""
    last_provisional_sweep_at: datetime | None = None
    provisional_write_count: int = 0


@dataclass(slots=True)
class MemoryCard:
    card_id: str
    kind: str
    summary: str
    confidence: float
    contradiction: bool
    citations: list[str]
    atom_ids: list[str]
    cluster_size: int = 1
    summary_abstractive: str = ""
    raw_excerpt: str = ""
    section: str = ""
    pack_rank: int = 0
    memory_layer: str = ""
    trust_tier: str = ""
    conflict_state: str = "active"
    conflict_visible: bool = False
    conflict_winner: bool = False
    conflict_with: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalPassResult:
    retrieval: Any
    passes_used: int
    stop_reason: str


@dataclass(slots=True)
class ResolvedRetrievalOverride:
    retrieval_text: str
    decision: FrontDeskDecision
    audit: RetrievalOverrideAuditContract


class RuntimeSession:
    """Stateless-call runtime that adds memory continuity and telemetry."""

    def __init__(
        self,
        *,
        retriever: MemoryRetriever,
        verifier: ClaimVerifier,
        continuity_store: ContinuityStore | None = None,
        config: NumquamOblitaConfig | None = None,
        model_name: str = "local-continuity-stub",
        input_cost_per_mtok: float = 3.75,
        output_cost_per_mtok: float = 15.0,
        short_term_enabled: bool = True,
        short_term_capacity: int = 32,
        short_term_top_k: int = 6,
        short_term_note_max_chars: int = 320,
        short_term_min_overlap: float = 0.34,
        short_term_min_ngram: float = 0.18,
        short_term_min_score: float = 0.36,
        short_term_primary_score: float = 0.58,
        short_term_token_weight: float = 0.6,
        short_term_ngram_weight: float = 0.4,
        short_term_summary_enabled: bool = True,
        short_term_summary_max_chars: int = 900,
        short_term_summary_segments: int = 18,
        short_term_working_set_token_limit: int = 900,
        short_term_summary_match_floor: float = 0.12,
        ltm_multi_pass_enabled: bool | None = None,
        ltm_max_passes: int | None = None,
        ltm_followup_min_match_max: float | None = None,
        ltm_followup_min_pack_confidence: float | None = None,
        ltm_followup_time_budget_ms: float | None = None,
        ltm_followup_max_query_tokens: int | None = None,
        episode_cards_path: str | None = None,
        episode_top_k: int | None = None,
        episode_min_score: float | None = None,
        episode_primary_min_score: float | None = None,
        episode_primary_min_cue_match: float | None = None,
        episode_primary_min_lexical: float | None = None,
        memory_signal_min_score: float | None = None,
        name_frequency_min_mentions: int = 3,
        routine_hard_cap_enabled: bool | None = None,
        enable_writeback: bool = True,
        min_query_match_max: float | None = None,
        min_query_match_mean: float | None = None,
        min_query_informative_overlap: float | None = None,
        min_query_token_hits: int | None = None,
        turn_latency_warn_ms: float = 2800.0,
        turn_token_warn_limit: int = 850,
        turn_cost_warn_limit_usd: float = 0.015,
        prewarm_caches: bool | None = None,
        project_root: str | Path | None = None,
        runtime_state_root: str | Path | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self.retriever = retriever
        self.config = config or getattr(retriever, "config", None) or default_config()
        self.config_path = Path(config_path).expanduser().resolve() if config_path else None
        if config is not None and hasattr(self.retriever, "config"):
            try:
                setattr(self.retriever, "config", self.config)
            except Exception as exc:
                _LOGGER.exception(
                    "failed to apply explicit runtime config to retriever %s",
                    type(self.retriever).__name__,
                )
                raise RuntimeError(
                    f"failed to apply explicit runtime config to retriever {type(self.retriever).__name__}"
                ) from exc
        self.verifier = verifier
        self.continuity_store = continuity_store or ContinuityStore()
        self.project_root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[2]
        self.runtime_state_root = Path(runtime_state_root).expanduser().resolve() if runtime_state_root else None
        self._scratchpad_store: WorkSessionScratchpadStore | None = None
        self._scratchpad_init_error = ""
        if bool(getattr(self.config.work_session_scratchpad, "enabled", False)):
            try:
                resolve_scratchpad_root(self.project_root, self.runtime_state_root)
                self._scratchpad_store = WorkSessionScratchpadStore(
                    project_root=self.project_root,
                    runtime_state_root=self.runtime_state_root,
                    policy=self.config.work_session_scratchpad,
                )
            except Exception as exc:
                self._scratchpad_init_error = str(exc)
                _LOGGER.warning("work session scratchpad init failed: %s", exc)
        retrieval_policy = self.config.runtime.retrieval
        self.model_name = model_name
        self.input_cost_per_mtok = input_cost_per_mtok
        self.output_cost_per_mtok = output_cost_per_mtok
        self.short_term_enabled = bool(short_term_enabled)
        self.short_term_capacity = max(4, int(short_term_capacity))
        self.short_term_top_k = max(1, min(int(short_term_top_k), self.short_term_capacity))
        self.short_term_note_max_chars = max(80, int(short_term_note_max_chars))
        self.short_term_min_overlap = _clamp01(short_term_min_overlap)
        self.short_term_min_ngram = _clamp01(short_term_min_ngram)
        self.short_term_min_score = _clamp01(short_term_min_score)
        self.short_term_primary_score = max(
            self.short_term_min_score,
            _clamp01(short_term_primary_score),
        )
        token_weight = max(0.0, float(short_term_token_weight))
        ngram_weight = max(0.0, float(short_term_ngram_weight))
        total_weight = token_weight + ngram_weight
        if total_weight <= 0.0:
            token_weight, ngram_weight = 1.0, 0.0
            total_weight = 1.0
        self.short_term_token_weight = token_weight / total_weight
        self.short_term_ngram_weight = ngram_weight / total_weight
        self.short_term_summary_enabled = bool(short_term_summary_enabled)
        self.short_term_summary_max_chars = max(240, int(short_term_summary_max_chars))
        self.short_term_summary_segments = max(1, int(short_term_summary_segments))
        self.short_term_working_set_token_limit = max(64, int(short_term_working_set_token_limit))
        self.short_term_summary_match_floor = _clamp01(short_term_summary_match_floor)
        if ltm_multi_pass_enabled is None:
            ltm_multi_pass_enabled = bool(retrieval_policy.ltm_multi_pass_enabled)
        if ltm_max_passes is None:
            ltm_max_passes = int(retrieval_policy.ltm_max_passes)
        if ltm_followup_min_match_max is None:
            ltm_followup_min_match_max = float(retrieval_policy.ltm_followup_min_match_max)
        if ltm_followup_min_pack_confidence is None:
            ltm_followup_min_pack_confidence = float(retrieval_policy.ltm_followup_min_pack_confidence)
        if ltm_followup_time_budget_ms is None:
            ltm_followup_time_budget_ms = float(retrieval_policy.ltm_followup_time_budget_ms)
        if ltm_followup_max_query_tokens is None:
            ltm_followup_max_query_tokens = int(retrieval_policy.ltm_followup_max_query_tokens)
        self.ltm_multi_pass_enabled = bool(ltm_multi_pass_enabled)
        self.ltm_max_passes = max(1, int(ltm_max_passes))
        self.ltm_followup_min_match_max = max(0.0, float(ltm_followup_min_match_max))
        self.ltm_followup_min_pack_confidence = _clamp01(ltm_followup_min_pack_confidence)
        self.ltm_followup_time_budget_ms = max(1.0, float(ltm_followup_time_budget_ms))
        self.ltm_followup_max_query_tokens = max(8, int(ltm_followup_max_query_tokens))
        self.episode_cards_path = str(episode_cards_path or "").strip()
        if episode_top_k is None:
            episode_top_k = int(retrieval_policy.episode_top_k)
        if episode_min_score is None:
            episode_min_score = float(retrieval_policy.episode_min_score)
        if episode_primary_min_score is None:
            episode_primary_min_score = float(retrieval_policy.episode_primary_min_score)
        if episode_primary_min_cue_match is None:
            episode_primary_min_cue_match = float(retrieval_policy.episode_primary_min_cue_match)
        if episode_primary_min_lexical is None:
            episode_primary_min_lexical = float(retrieval_policy.episode_primary_min_lexical)
        self.episode_top_k = max(1, int(episode_top_k))
        self.episode_min_score = _clamp01(episode_min_score)
        self.episode_primary_min_score = _clamp01(max(episode_min_score, episode_primary_min_score))
        self.episode_primary_min_cue_match = _clamp01(episode_primary_min_cue_match)
        self.episode_primary_min_lexical = _clamp01(episode_primary_min_lexical)
        self._episode_index = self._load_episode_index(self.episode_cards_path)
        if memory_signal_min_score is None:
            memory_signal_min_score = float(retrieval_policy.memory_signal_min_score)
        self.memory_signal_min_score = _clamp01(memory_signal_min_score)
        self.name_frequency_min_mentions = max(1, int(name_frequency_min_mentions))
        if routine_hard_cap_enabled is None:
            routine_hard_cap_enabled = bool(retrieval_policy.routine_hard_cap_enabled)
        self.routine_hard_cap_enabled = bool(routine_hard_cap_enabled)
        self.enable_writeback = bool(enable_writeback)
        if min_query_match_max is None:
            min_query_match_max = float(retrieval_policy.min_query_match_max)
        if min_query_match_mean is None:
            min_query_match_mean = float(retrieval_policy.min_query_match_mean)
        if min_query_informative_overlap is None:
            min_query_informative_overlap = float(retrieval_policy.min_query_informative_overlap)
        if min_query_token_hits is None:
            min_query_token_hits = int(retrieval_policy.min_query_token_hits)
        self.min_query_match_max = max(0.0, float(min_query_match_max))
        self.min_query_match_mean = max(0.0, float(min_query_match_mean))
        self.min_query_informative_overlap = max(0.0, float(min_query_informative_overlap))
        self.min_query_token_hits = max(1, int(min_query_token_hits))
        self.turn_latency_warn_ms = max(1.0, float(turn_latency_warn_ms))
        self.turn_token_warn_limit = max(1, int(turn_token_warn_limit))
        self.turn_cost_warn_limit_usd = max(0.0, float(turn_cost_warn_limit_usd))
        if prewarm_caches is None:
            prewarm_caches = bool(retrieval_policy.prewarm_caches)
        self.prewarm_caches = bool(prewarm_caches)
        self._lock = threading.RLock()
        self._executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="runtime-writeback")
            if self.enable_writeback
            else None
        )
        self._turns: list[TurnTrace] = []
        self._writebacks: dict[str, WritebackEvent] = {}
        self._writeback_futures: dict[str, Future[Any]] = {}
        self._latencies: list[float] = []
        self._stats = RuntimeStats()
        self._sessions: dict[str, SessionState] = {}
        self._memory_capture_dropped_reason_counts: dict[str, int] = {}
        self._memory_capture_provisional_accepted_count = 0
        self._memory_capture_proposal_only_count = 0
        self._memory_capture_sweep_promotion_count = 0
        self._memory_capture_duplicate_suspected_count = 0
        self._note_seq = 0
        self._name_frequency_counts: dict[str, int] = {}
        self._processed_boundary_keys: set[str] = set()
        provisional_policy = self.config.provisional_memory
        self._provisional_policy = provisional_policy
        self._provisional_memory_enabled = bool(provisional_policy.enabled)
        self._provisional_retrieval_enabled = self._provisional_memory_enabled and bool(provisional_policy.retrieval_enabled)
        self._provisional_stm_sweep_enabled = self._provisional_memory_enabled and bool(provisional_policy.stm_sweep_enabled)
        self._proposal_capture_enabled = self._provisional_memory_enabled and bool(
            getattr(provisional_policy, "proposal_capture_enabled", False)
        )
        self._provisional_store = self._build_provisional_store() if self._provisional_memory_enabled else None
        atom_store = getattr(self.retriever, "store", None)
        self._integration_handle_signer = (
            IntegrationHandleSigner(atom_store) if isinstance(atom_store, SqliteAtomStore) else None
        )
        self._proposal_store = self._build_proposal_store() if self._proposal_capture_enabled else None
        self._sessions["default"] = self._new_session_state("default", label="default")
        self._hydrate_recognition_from_store()
        self._hydrate_name_frequency_cache()
        self._refresh_recognition_stats()
        if self.prewarm_caches:
            self._prewarm_runtime_caches()

    def close(self, *, wait_timeout_s: float = 2.0) -> None:
        if self._provisional_stm_sweep_enabled:
            with self._lock:
                session_ids = list(self._sessions.keys())
            for session_id in session_ids:
                try:
                    self.on_session_boundary(
                        event_type="runtime_close",
                        session_id=session_id,
                        observed_at_utc=_utc_now(),
                        metadata={"source": "runtime_close"},
                    )
                except Exception:
                    _LOGGER.exception("provisional STM sweep failed during runtime close for session %s", session_id)
        executor = self._executor
        if executor is None:
            closer = getattr(self._provisional_store, "close", None)
            if callable(closer):
                closer()
            proposal_closer = getattr(self._proposal_store, "close", None)
            if callable(proposal_closer):
                proposal_closer()
            return
        self._executor = None

        with self._lock:
            pending = [future for future in self._writeback_futures.values() if not future.done()]

        wait_timeout = max(0.0, float(wait_timeout_s))
        if pending:
            done, still_pending = wait(pending, timeout=wait_timeout)
            del done
            if still_pending:
                with self._lock:
                    now = _utc_now()
                    for event_id, future in list(self._writeback_futures.items()):
                        if future in still_pending:
                            event = self._writebacks.get(event_id)
                            if event is not None and event.status in {"queued", "running"}:
                                event.status = "failed"
                                event.error = "runtime closed before writeback completed"
                                event.processed_at = now
                for future in still_pending:
                    future.cancel()

        with self._lock:
            self._writeback_futures.clear()

        executor.shutdown(wait=False, cancel_futures=True)
        closer = getattr(self._provisional_store, "close", None)
        if callable(closer):
            closer()
        proposal_closer = getattr(self._proposal_store, "close", None)
        if callable(proposal_closer):
            proposal_closer()

    def _normalize_session_id(self, session_id: str | None) -> str:
        raw = str(session_id or "default").strip()
        if not raw:
            return "default"
        safe = re.sub(r"[^A-Za-z0-9_\-:.]", "_", raw)
        return safe[:96] or "default"

    def _new_session_state(self, session_id: str, *, label: str | None = None) -> SessionState:
        now = _utc_now()
        provided_label = str(label or "").strip()
        if provided_label:
            final_label = self._compact_text(provided_label, max_chars=120)
            label_auto = False
        else:
            final_label = self._auto_session_label(created_at=now, topic_hint=None)
            label_auto = True
        return SessionState(
            session_id=session_id,
            label=final_label,
            label_auto=label_auto,
            created_at=now,
            updated_at=now,
            short_term=deque(),
            summary_segments=deque(maxlen=self.short_term_summary_segments),
        )

    def _build_provisional_store(self) -> InMemoryProvisionalMemoryStore | SqliteProvisionalMemoryStore:
        store = getattr(self.retriever, "store", None)
        if isinstance(store, SqliteAtomStore):
            db_path = Path(store.db_path)
            sidecar_path = (
                db_path.with_suffix(".provisional.sqlite3")
                if db_path.suffix
                else db_path.parent / f"{db_path.name}.provisional.sqlite3"
            )
            return SqliteProvisionalMemoryStore(sidecar_path)
        return InMemoryProvisionalMemoryStore()

    def _build_proposal_store(self) -> InMemoryProposalStore | SqliteProposalStore:
        store = getattr(self.retriever, "store", None)
        if isinstance(store, SqliteAtomStore):
            db_path = Path(store.db_path)
            sidecar_path = (
                db_path.with_suffix(".proposals.sqlite3")
                if db_path.suffix
                else db_path.parent / f"{db_path.name}.proposals.sqlite3"
            )
            return SqliteProposalStore(sidecar_path)
        return InMemoryProposalStore()

    def _provisional_profile(self):
        name = str(self._provisional_policy.default_sensitivity or "balanced").strip().lower()
        return getattr(self._provisional_policy, name, self._provisional_policy.balanced)

    def provisional_diagnostics(self) -> dict[str, Any]:
        if self._provisional_store is None:
            return {
                "enabled": False,
                "retrieval_enabled": False,
                "stm_sweep_enabled": False,
                "total_count": 0,
                "active_count": 0,
                "superseded_count": 0,
                "conflicted_count": 0,
                "archived_count": 0,
                "event_count": 0,
                "accepted_count": 0,
            }
        snapshot = dict(self._provisional_store.diagnostics_snapshot())
        snapshot.update(
            {
                "enabled": bool(self._provisional_memory_enabled),
                "retrieval_enabled": bool(self._provisional_retrieval_enabled),
                "stm_sweep_enabled": bool(self._provisional_stm_sweep_enabled),
                "accepted_count": int(self._memory_capture_provisional_accepted_count),
            }
        )
        return snapshot

    def proposal_diagnostics(self) -> dict[str, Any]:
        if self._proposal_store is None:
            return {
                "enabled": False,
                "total_count": 0,
                "pending_count": 0,
                "reviewed_count": 0,
                "dismissed_count": 0,
                "event_count": 0,
                "accepted_count": 0,
            }
        snapshot = dict(self._proposal_store.diagnostics_snapshot())
        snapshot["enabled"] = bool(self._proposal_capture_enabled)
        snapshot["accepted_count"] = int(self._memory_capture_proposal_only_count)
        return snapshot

    def provisional_settings(self) -> dict[str, Any]:
        profile_name = str(self._provisional_policy.default_sensitivity or "balanced").strip().lower() or "balanced"
        profile = self._provisional_profile()
        return {
            "enabled": bool(self._provisional_memory_enabled),
            "default_sensitivity": profile_name,
            "profile": {
                "worthiness_threshold": float(profile.worthiness_threshold),
                "self_claim_threshold": float(profile.self_claim_threshold),
                "max_auto_writes_per_turn": int(profile.max_auto_writes_per_turn),
                "max_auto_writes_per_session": int(profile.max_auto_writes_per_session),
            },
            "review_worthiness_enabled": bool(getattr(self._provisional_policy.review_worthiness, "enabled", True)),
            "near_duplicate_enabled": bool(getattr(self._provisional_policy.near_duplicate, "enabled", True)),
            "inactivity_gap_seconds": int(self._provisional_policy.inactivity_gap_seconds),
            "policy_source": str(getattr(self._provisional_policy, "policy_source", "") or "built_in"),
            "config_path": str(self.config_path) if self.config_path is not None else "",
        }

    def issue_integration_source_registration(
        self,
        *,
        content: str,
        source_role: str,
        session_id: str,
        run_id: str,
        principal_id: str,
        source_id: str = "",
        message_id: str = "",
    ) -> dict[str, Any]:
        signer = self._integration_handle_signer
        store = self._provisional_store
        if signer is None or not isinstance(store, SqliteProvisionalMemoryStore):
            raise RuntimeError("signed source registration requires a SQLite runtime")
        assert_safe_content(content)
        role = str(source_role or "").strip().lower()
        resolved_source_id = str(source_id or f"src_{uuid4().hex[:20]}").strip()
        resolved_message_id = str(message_id or f"msg_{uuid4().hex[:20]}").strip()
        registration = store.register_source(
            source_id=resolved_source_id,
            message_id=resolved_message_id,
            source_role=role,
            content=content,
            session_id=session_id,
        )
        payload = {
            "source_id": registration.source_id,
            "message_id": registration.message_id,
            "source_role": registration.source_role,
            "content_digest": registration.content_digest,
            "session_id": str(session_id),
            "run_id": str(run_id),
            "principal_id": str(principal_id),
            "provisional_store_uuid": store.store_uuid,
            "registration_identity": registration.handle,
            "policy_version": str(self._provisional_policy.policy_version),
        }
        return signer.issue(
            "source_registration",
            payload,
            ttl_seconds=int(self._provisional_policy.source_registration_ttl_seconds),
        )

    def issue_integration_retrieval_receipt(
        self,
        *,
        retrieved_evidence_ids: list[str],
        session_id: str,
        run_id: str,
        principal_id: str,
    ) -> dict[str, Any]:
        signer = self._integration_handle_signer
        if signer is None:
            raise RuntimeError("signed retrieval receipts require a SQLite runtime")
        payload = {
            "retrieved_evidence_ids": [str(item) for item in retrieved_evidence_ids[:64] if str(item).strip()],
            "session_id": str(session_id),
            "run_id": str(run_id),
            "principal_id": str(principal_id),
            "policy_version": str(self._provisional_policy.policy_version),
        }
        return signer.issue(
            "retrieval_receipt",
            payload,
            ttl_seconds=int(self._provisional_policy.source_registration_ttl_seconds),
        )

    def observe_external_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        session_id: str,
        run_id: str,
        principal_id: str,
        retrieval_receipt: str = "",
        remember_intent: str = "none",
        boundary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        store = self._provisional_store
        signer = self._integration_handle_signer
        if not self._provisional_memory_enabled or not isinstance(store, SqliteProvisionalMemoryStore) or signer is None:
            raise RuntimeError("external observation requires enabled SQLite provisional memory")
        if not 1 <= len(messages) <= 8:
            raise ValueError("messages must contain 1..8 items")
        total_bytes = sum(len(str(item.get("content") or "").encode("utf-8")) for item in messages)
        if total_bytes > 131_072:
            raise ValueError("message payload exceeds 128 KiB")
        for raw in messages:
            role = str(raw.get("role") or "").strip().lower()
            content = str(raw.get("content") or "")
            if not content.strip() or len(content.encode("utf-8")) > 32_768:
                raise ValueError("each message requires content up to 32 KiB")
            if role not in {"system", "developer", "user", "tool", "external", "assistant"}:
                raise ValueError(f"unsupported source role: {role}")
            if role not in {"system", "developer"}:
                assert_safe_content(content)

        receipt_payload: dict[str, Any] | None = None
        if str(retrieval_receipt or "").strip():
            receipt_payload = signer.verify(str(retrieval_receipt), expected_kind="retrieval_receipt")
            self._validate_handle_binding(
                receipt_payload,
                session_id=session_id,
                run_id=run_id,
                principal_id=principal_id,
            )
        retrieved_ids = list((receipt_payload or {}).get("retrieved_evidence_ids") or [])
        results: list[dict[str, Any]] = []
        now = _utc_now()
        for index, raw in enumerate(messages):
            role = str(raw.get("role") or "").strip().lower()
            content = str(raw.get("content") or "")
            if not content.strip() or len(content.encode("utf-8")) > 32_768:
                raise ValueError("each message requires content up to 32 KiB")
            if role in {"system", "developer"}:
                results.append({"index": index, "support_delta": 0, "reason": "ineligible_source_role"})
                continue
            source_id = str(raw.get("source_id") or "").strip()
            message_id = str(raw.get("message_id") or "").strip()
            registration: EvidenceRegistration | None = None
            if role in {"user", "tool", "external"}:
                raw_registration = raw.get("source_registration")
                handle = str((raw_registration or {}).get("handle") if isinstance(raw_registration, dict) else raw_registration or "")
                verified = signer.verify(handle, expected_kind="source_registration")
                self._validate_handle_binding(
                    verified,
                    session_id=session_id,
                    run_id=run_id,
                    principal_id=principal_id,
                )
                if verified.get("source_role") != role or verified.get("content_digest") != normalized_content_digest(content):
                    raise IntegrationHandleError("SOURCE_REGISTRATION_MISMATCH")
                if str(verified.get("provisional_store_uuid") or "") != store.store_uuid:
                    raise IntegrationHandleError("HANDLE_STORE_MISMATCH")
                source_id = str(verified.get("source_id") or "")
                message_id = str(verified.get("message_id") or "")
                registration = EvidenceRegistration(
                    source_id=source_id,
                    message_id=message_id,
                    source_role=role,
                    content_digest=str(verified.get("content_digest") or ""),
                    session_id=str(session_id),
                    handle=str(verified.get("registration_identity") or ""),
                )
            elif role == "assistant":
                if receipt_payload is not None:
                    receipt_identity = hashlib.sha256(str(retrieval_receipt).encode("utf-8")).hexdigest()[:24]
                    source_id = f"assistant:{principal_id}"
                    message_id = f"receipt:{receipt_identity}:{index}"
            else:
                raise ValueError(f"unsupported source role: {role}")
            candidate, drop_reason = self._provisional_candidate_with_reason(
                text=content,
                source_role=role,
                source_id=source_id or f"assistant:{session_id}",
                message_id=message_id or f"assistant:{run_id}:{index}",
                timestamp=now,
                session_id=session_id,
            )
            if candidate is None:
                results.append({"index": index, "support_delta": 0, "reason": drop_reason or "not_captured"})
                continue
            candidate.source_id = source_id
            candidate.message_id = message_id
            candidate.span_start = 0
            candidate.span_end = len(content)
            candidate.content = content
            assistant_eligible = bool(role == "assistant" and receipt_payload is not None and not retrieved_ids)
            disposition = store.observe_candidate(
                candidate,
                reason="external_turn_observe",
                registration=registration,
                assistant_receipt_valid=assistant_eligible,
            )
            results.append(
                {
                    "index": index,
                    "record_id": disposition.record_id,
                    "support_delta": disposition.support_delta,
                    "reason": disposition.reason,
                }
            )

        transitions = self.maintain_provisional_memory(max_records=int(self._provisional_policy.maintenance_max_records))
        boundary_replayed = False
        if boundary:
            boundary_new = store.record_boundary(
                event_id=str(boundary.get("event_id") or ""),
                event_type=str(boundary.get("event_type") or ""),
                observed_at_utc=str(boundary.get("observed_at_utc") or ""),
                metadata={str(key): str(value) for key, value in dict(boundary.get("metadata") or {}).items()},
            )
            boundary_replayed = not boundary_new
            if boundary_new:
                transitions = self.maintain_provisional_memory(
                    max_records=int(self._provisional_policy.maintenance_max_records)
                )
        return {
            "observations": results,
            "accepted_support_count": sum(int(item.get("support_delta") or 0) for item in results),
            "maintenance": transitions,
            "boundary_replayed": boundary_replayed,
            "writeback_required": str(remember_intent or "none").strip().lower() == "user_explicit",
        }

    @staticmethod
    def _validate_handle_binding(
        payload: dict[str, Any], *, session_id: str, run_id: str, principal_id: str
    ) -> None:
        expected = {
            "session_id": str(session_id),
            "run_id": str(run_id),
            "principal_id": str(principal_id),
        }
        if any(str(payload.get(key) or "") != value for key, value in expected.items()):
            raise IntegrationHandleError("HANDLE_BINDING_MISMATCH")

    def maintain_provisional_memory(self, *, max_records: int | None = None) -> list[dict[str, str]]:
        store = self._provisional_store
        if not isinstance(store, SqliteProvisionalMemoryStore):
            return []
        if not bool(self._provisional_policy.maintenance_enabled):
            return []
        policy = MaintenancePolicy(
            dormant_days=int(self._provisional_policy.dormant_days),
            archive_days=int(self._provisional_policy.archive_days),
            plan_currentness_days=int(self._provisional_policy.plan_currentness_days),
            max_records=int(self._provisional_policy.maintenance_max_records),
            policy_version=str(self._provisional_policy.policy_version),
        )
        transitions = run_maintenance(
            store,
            policy=policy,
            max_records=max_records,
            consolidation_enabled=bool(self._provisional_policy.consolidation_enabled),
        )
        return [
            {"record_id": item.record_id, "disposition": item.disposition, "reason": item.reason}
            for item in transitions
        ]

    def set_provisional_sensitivity(
        self,
        *,
        sensitivity: str | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        valid = ["conservative", "balanced", "eager"]
        current = str(self._provisional_policy.default_sensitivity or "balanced").strip().lower() or "balanced"
        target = current
        explicit = str(sensitivity or "").strip().lower()
        if explicit:
            if explicit not in valid:
                raise ValueError("sensitivity must be one of: conservative, balanced, eager")
            target = explicit
        else:
            normalized_action = str(action or "").strip().lower()
            if normalized_action not in {"remember_more", "remember_less"}:
                raise ValueError("action must be remember_more or remember_less")
            idx = valid.index(current if current in valid else "balanced")
            if normalized_action == "remember_more":
                target = valid[min(len(valid) - 1, idx + 1)]
            else:
                target = valid[max(0, idx - 1)]
        with self._lock:
            previous = self._provisional_policy.default_sensitivity
            self._provisional_policy.default_sensitivity = target
            if self.config_path is not None:
                try:
                    self._persist_runtime_policy()
                except Exception:
                    self._provisional_policy.default_sensitivity = previous
                    raise
        return self.provisional_settings()

    def _persist_runtime_policy(self) -> None:
        path = self.config_path
        if path is None:
            raise RuntimeError("active runtime policy has no writable config path")
        payload = json.dumps(self.config.as_dict(), indent=2, ensure_ascii=False) + "\n"
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError("active runtime policy is not writable") from exc

    def list_memory_proposals(self) -> list[ProposalRecord]:
        if self._proposal_store is None:
            return []
        return list(self._proposal_store.list_records())

    def get_memory_proposal(self, record_id: str) -> ProposalRecord:
        if self._proposal_store is None:
            raise KeyError(str(record_id))
        return self._proposal_store.get_record(str(record_id))

    def dismiss_memory_proposal(self, record_id: str, *, actor: str, reason_code: str) -> ProposalRecord:
        if self._proposal_store is None:
            raise KeyError(str(record_id))
        return self._proposal_store.dismiss(str(record_id), actor=actor, reason_code=reason_code)

    def mark_memory_proposal_bridged(self, record_id: str, *, proposal_id: str, actor: str) -> ProposalRecord:
        if self._proposal_store is None:
            raise KeyError(str(record_id))
        return self._proposal_store.mark_bridged(str(record_id), proposal_id=proposal_id, actor=actor)

    def memory_capture_diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": bool(self._provisional_memory_enabled),
            "proposal_capture_enabled": bool(self._proposal_capture_enabled),
            "provisional_accepted_count": int(self._memory_capture_provisional_accepted_count),
            "proposal_only_count": int(self._memory_capture_proposal_only_count),
            "duplicate_suspected_count": int(self._memory_capture_duplicate_suspected_count),
            "dropped_count": int(sum(self._memory_capture_dropped_reason_counts.values())),
            "dropped_reason_counts": dict(self._memory_capture_dropped_reason_counts),
            "sweep_promotion_count": int(self._memory_capture_sweep_promotion_count),
            "default_sensitivity": str(self._provisional_policy.default_sensitivity or "balanced"),
            "time_source": "system_utc",
        }

    def _record_memory_capture_drop(self, reason: str) -> None:
        normalized = str(reason or "").strip().lower() or "unknown"
        with self._lock:
            self._memory_capture_dropped_reason_counts[normalized] = (
                self._memory_capture_dropped_reason_counts.get(normalized, 0) + 1
            )

    def search_provisional_memory(self, query: str, *, limit: int = 5) -> list[ProvisionalSearchHit]:
        if self._provisional_store is None:
            return []
        return list(self._provisional_store.search(str(query or ""), limit=max(1, int(limit))))

    def list_provisional_records(
        self,
        *,
        status: str = "all",
        query: str = "",
        limit: int = 60,
        offset: int = 0,
    ) -> list[ProvisionalMemoryRecord]:
        if self._provisional_store is None:
            return []
        rows = list(self._provisional_store.list_records(status=status))
        search = str(query or "").strip().lower()
        if search:
            filtered: list[ProvisionalMemoryRecord] = []
            for record in rows:
                hay = " ".join(
                    [
                        str(record.record_id or ""),
                        str(record.canonical_text or ""),
                        str(record.kind.value),
                        str(record.source_role or ""),
                        str(record.session_id or ""),
                        " ".join(str(item) for item in list(record.conflict_with_record_ids)),
                    ]
                ).lower()
                if search in hay:
                    filtered.append(record)
            rows = filtered
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        return rows[start:end]

    def mark_provisional_conflict(
        self,
        record_id: str,
        other_record_id: str,
        *,
        reason: str = "runtime_operator_conflict",
    ) -> tuple[ProvisionalMemoryRecord, ProvisionalMemoryRecord]:
        if self._provisional_store is None:
            raise RuntimeError("provisional memory is disabled")
        return self._provisional_store.mark_conflict(record_id, other_record_id, reason=reason)

    def list_provisional_record_payloads(
        self,
        *,
        status: str = "all",
        query: str = "",
        limit: int = 60,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            self._serialize_provisional_record(record)
            for record in self.list_provisional_records(status=status, query=query, limit=limit, offset=offset)
        ]

    def list_provisional_review_candidates(
        self,
        *,
        query: str = "",
        limit: int = 60,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        records = self.list_provisional_records(status="live", query=query, limit=limit, offset=offset)
        payloads = [self._provisional_review_candidate_payload(record) for record in records]
        payloads.sort(
            key=lambda item: (
                bool(item.get("review_worthy")),
                float(item.get("review_worthy_score") or 0.0),
                min(8, int(item.get("reinforcement_count") or 0)),
                float(item.get("stability") or 0.0),
                float(item.get("salience") or 0.0),
                str(item.get("updated_at") or ""),
                str(item.get("record_id") or ""),
            ),
            reverse=True,
        )
        return payloads

    def get_provisional_record_detail(self, record_id: str) -> dict[str, Any]:
        if self._provisional_store is None:
            raise RuntimeError("provisional memory is disabled")
        record = self._provisional_store.get_record(str(record_id or "").strip())
        payload = self._provisional_review_candidate_payload(record)
        duplicate_suspicions = self.list_provisional_duplicate_suspicions(record_id=record.record_id, limit=200, offset=0)
        payload["duplicate_suspicions"] = duplicate_suspicions
        payload["duplicate_suspicion_count"] = len(duplicate_suspicions)
        return payload

    @staticmethod
    def _provisional_distinct_session_count(record: ProvisionalMemoryRecord) -> int:
        stored = int(getattr(record, "distinct_session_count", 0) or 0)
        if stored > 0:
            return stored
        raw = str(dict(record.metadata or {}).get("distinct_session_count") or "").strip()
        try:
            value = int(raw)
        except Exception:
            value = 1
        return max(1, value)

    @staticmethod
    def _provisional_review_threshold(kind: ProvisionalMemoryKind, policy: Any) -> float:
        mapping = {
            ProvisionalMemoryKind.FACT: "fact_min_score",
            ProvisionalMemoryKind.PREFERENCE: "preference_min_score",
            ProvisionalMemoryKind.PLAN: "plan_min_score",
            ProvisionalMemoryKind.EVENT_NOTE: "event_note_min_score",
            ProvisionalMemoryKind.SELF_CLAIM: "self_claim_min_score",
            ProvisionalMemoryKind.CORRECTION: "correction_min_score",
        }
        return float(getattr(policy, mapping[kind], 1.0))

    def _provisional_review_worthiness(self, record: ProvisionalMemoryRecord) -> dict[str, Any]:
        policy = self._provisional_policy.review_worthiness
        distinct_session_count = self._provisional_distinct_session_count(record)
        reinforcement_score = min(1.0, float(record.reinforcement_count) / 4.0)
        session_score = min(1.0, float(distinct_session_count) / 3.0)
        score = (
            float(record.stability) * float(policy.stability_weight)
            + float(record.salience) * float(policy.salience_weight)
            + reinforcement_score * float(policy.reinforcement_weight)
            + session_score * float(policy.distinct_session_weight)
        )
        conflict_penalty_applied = bool(record.status is ProvisionalMemoryStatus.CONFLICTED)
        self_claim_penalty_applied = bool(record.kind is ProvisionalMemoryKind.SELF_CLAIM)
        if conflict_penalty_applied:
            score -= float(policy.conflict_penalty)
        if self_claim_penalty_applied:
            score -= float(policy.self_claim_penalty)
        score = _clamp01(score)
        threshold = self._provisional_review_threshold(record.kind, policy)
        review_worthy = bool(policy.enabled) and score >= threshold
        return {
            "review_worthy_score": score,
            "review_worthy": review_worthy,
            "review_worthy_threshold": threshold,
            "distinct_session_count": distinct_session_count,
            "conflict_penalty_applied": conflict_penalty_applied,
            "self_claim_penalty_applied": self_claim_penalty_applied,
        }

    @staticmethod
    def _provisional_bridge_eligible(record: ProvisionalMemoryRecord) -> bool:
        return record.kind in {
            ProvisionalMemoryKind.FACT,
            ProvisionalMemoryKind.PREFERENCE,
            ProvisionalMemoryKind.PLAN,
            ProvisionalMemoryKind.EVENT_NOTE,
        }

    @staticmethod
    def _provisional_kind_to_atom_type(kind: ProvisionalMemoryKind) -> AtomType:
        if kind is ProvisionalMemoryKind.EVENT_NOTE:
            return AtomType.EPISODE
        return AtomType.ATOMIC_FACT

    def flush_session_to_provisional(self, session_id: str | None, *, reason: str = "session_boundary") -> int:
        if self._provisional_store is None or not self._provisional_stm_sweep_enabled:
            return 0
        session = self._ensure_session(session_id)
        with self._lock:
            last_sweep_at = session.last_provisional_sweep_at
            notes = [
                note
                for note in list(session.short_term)
                if last_sweep_at is None or note.created_at > last_sweep_at
            ]
        created = 0
        for note in notes:
            created += self._capture_provisional_memory_from_text(
                text=note.text,
                source_role=note.role,
                session=session,
                source_id=f"stm:{note.turn_id}",
                message_id=note.note_id,
                timestamp=note.created_at,
                reason=reason,
            )
        with self._lock:
            session.last_provisional_sweep_at = _utc_now()
            session.soft_close_hint_at = None
            session.soft_close_hint_text = ""
        return created

    def on_session_boundary(
        self,
        *,
        event_type: str,
        session_id: str | None,
        observed_at_utc: datetime | str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed = {"runtime_close", "session_timeout", "context_compaction", "manual_compact"}
        normalized_type = str(event_type or "").strip().lower()
        if normalized_type not in allowed:
            raise ValueError("event_type must be one of: runtime_close, session_timeout, context_compaction, manual_compact")
        if isinstance(observed_at_utc, datetime):
            observed_at = observed_at_utc
        else:
            observed_at = datetime.fromisoformat(str(observed_at_utc))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        else:
            observed_at = observed_at.astimezone(timezone.utc)
        session = self._ensure_session(session_id)
        boundary_key = "|".join([normalized_type, session.session_id, observed_at.isoformat()])
        with self._lock:
            duplicate = boundary_key in self._processed_boundary_keys
            if not duplicate:
                self._processed_boundary_keys.add(boundary_key)
        created = 0 if duplicate else self.flush_session_to_provisional(session.session_id, reason=normalized_type)
        return {
            "accepted": bool(self._provisional_stm_sweep_enabled),
            "duplicate": duplicate,
            "event_type": normalized_type,
            "session_id": session.session_id,
            "observed_at_utc": observed_at.isoformat(),
            "created_count": int(created),
            "metadata": dict(metadata or {}),
            "time_source": "system_utc",
        }

    def list_provisional_duplicate_suspicions(
        self,
        *,
        record_id: str | None = None,
        limit: int = 60,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._provisional_store is None:
            return []
        events = self._provisional_store.list_events(record_id=record_id, event_type=ProvisionalMemoryEventType.NEAR_DUPLICATE)
        rows: list[dict[str, Any]] = []
        for event in events:
            payload = self._serialize_provisional_event(event)
            metadata = dict(payload.get("metadata") or {})
            rows.append(
                {
                    **payload,
                    "left_record_id": str(event.record_id or ""),
                    "right_record_id": str(metadata.get("other_record_id") or ""),
                    "similarity_score": float(metadata.get("similarity_score") or 0.0),
                    "same_session": str(metadata.get("same_session") or "false").strip().lower() == "true",
                    "same_source_role": str(metadata.get("same_source_role") or "false").strip().lower() == "true",
                    "same_kind": str(metadata.get("same_kind") or "false").strip().lower() == "true",
                    "same_conflict_state": str(metadata.get("same_conflict_state") or "false").strip().lower() == "true",
                    "timestamp_order": str(metadata.get("timestamp_order") or ""),
                }
            )
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        return rows[start:end]

    def create_provisional_bridge_proposal(
        self,
        record_id: str,
        *,
        review_queue: MutationReviewQueue,
    ) -> Any:
        if self._provisional_store is None:
            raise RuntimeError("provisional memory is disabled")
        record = self._provisional_store.get_record(str(record_id or "").strip())
        if not self._provisional_bridge_eligible(record):
            raise ValueError("provisional record kind is not bridge-eligible")
        for existing in list(review_queue.list_all()):
            if (
                str(getattr(getattr(existing, "action", None), "value", getattr(existing, "action", ""))) == "PROPOSE_CREATE"
                and str((getattr(existing, "metadata", {}) or {}).get("provisional_record_id") or "").strip() == record.record_id
                and str(getattr(getattr(existing, "status", None), "value", getattr(existing, "status", ""))) in {"pending", "approved", "applied"}
            ):
                return existing
        candidate = CandidateAtom(
            candidate_id=f"cand_{record.record_id}",
            atom_type=self._provisional_kind_to_atom_type(record.kind),
            canonical_text=record.canonical_text,
            source_refs=list(record.source_refs),
            entities=[],
            topics=[],
            confidence=float(record.confidence),
            salience=float(record.salience),
        )
        return review_queue.propose_create(
            candidate=candidate,
            reason_code="provisional_bridge_create",
            metadata={
                "source": "provisional_bridge",
                "provisional_record_id": record.record_id,
                "provisional_kind": record.kind.value,
                "provisional_source_role": record.source_role,
                "provisional_session_id": record.session_id,
                "provisional_reinforcement_count": str(record.reinforcement_count),
                "provisional_distinct_session_count": str(self._provisional_distinct_session_count(record)),
                "provisional_stability": f"{float(record.stability):.4f}",
                "provisional_salience": f"{float(record.salience):.4f}",
                "provisional_conflict_with_json": json.dumps(list(record.conflict_with_record_ids), ensure_ascii=False),
                "provisional_supersedes_record_id": str(record.supersedes_record_id or ""),
            },
        )

    def _provisional_lineage_record_ids(self, record: ProvisionalMemoryRecord) -> list[str]:
        if self._provisional_store is None:
            return [record.record_id]
        lineage: list[str] = []
        current: ProvisionalMemoryRecord | None = record
        seen: set[str] = set()
        while current is not None and current.record_id not in seen:
            seen.add(current.record_id)
            lineage.append(current.record_id)
            previous_id = str(current.supersedes_record_id or "").strip()
            if not previous_id:
                break
            try:
                current = self._provisional_store.get_record(previous_id)
            except Exception:
                current = None
        lineage.reverse()
        return lineage

    def _serialize_provisional_event(self, event: ProvisionalMemoryEvent) -> dict[str, Any]:
        source_refs: list[dict[str, Any]] = []
        for ref in list(event.source_refs):
            payload = dict(contract_to_dict(ref))
            timestamp = payload.get("timestamp")
            if timestamp is not None and hasattr(timestamp, "isoformat"):
                payload["timestamp"] = timestamp.isoformat()
            source_refs.append(payload)
        return {
            "event_id": str(event.event_id or ""),
            "event_type": str(getattr(event.event_type, "value", event.event_type) or ""),
            "record_id": str(event.record_id or ""),
            "timestamp": event.timestamp.isoformat() if getattr(event, "timestamp", None) else None,
            "reason": str(event.reason or ""),
            "metadata": dict(event.metadata or {}),
            "source_refs": source_refs,
        }

    def _serialize_provisional_record(self, record: ProvisionalMemoryRecord) -> dict[str, Any]:
        source_refs: list[dict[str, Any]] = []
        for ref in list(record.source_refs):
            payload = dict(contract_to_dict(ref))
            timestamp = payload.get("timestamp")
            if timestamp is not None and hasattr(timestamp, "isoformat"):
                payload["timestamp"] = timestamp.isoformat()
            source_refs.append(payload)
        return {
            "record_id": str(record.record_id or ""),
            "kind": str(getattr(record.kind, "value", record.kind) or ""),
            "canonical_text": str(record.canonical_text or ""),
            "source_role": str(record.source_role or ""),
            "session_id": str(record.session_id or ""),
            "confidence": float(record.confidence),
            "salience": float(record.salience),
            "stability": float(record.stability),
            "reinforcement_count": int(record.reinforcement_count),
            "independent_support_count": int(record.independent_support_count),
            "distinct_session_count": int(self._provisional_distinct_session_count(record)),
            "status": str(getattr(record.status, "value", record.status) or ""),
            "authority_tier": str(getattr(record.authority_tier, "value", record.authority_tier) or ""),
            "maturity": str(getattr(record.maturity, "value", record.maturity) or ""),
            "lifecycle": str(getattr(record.lifecycle, "value", record.lifecycle) or ""),
            "human_reviewed": False,
            "derived": bool(record.derived),
            "input_record_ids": list(record.input_record_ids),
            "claim_key": str(record.claim_key or ""),
            "policy_version": str(record.policy_version or ""),
            "supersedes_record_id": str(record.supersedes_record_id or "") or None,
            "superseded_by_record_id": str(record.superseded_by_record_id or "") or None,
            "conflict_with_record_ids": list(record.conflict_with_record_ids),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "last_reinforced_at": record.last_reinforced_at.isoformat() if record.last_reinforced_at else None,
            "memory_layer": "provisional",
            "trust_tier": "provisional",
            "source_refs": source_refs,
            "metadata": dict(record.metadata or {}),
        }

    def _provisional_review_candidate_payload(self, record: ProvisionalMemoryRecord) -> dict[str, Any]:
        if self._provisional_store is None:
            raise RuntimeError("provisional memory is disabled")
        events = [self._serialize_provisional_event(event) for event in self._provisional_store.list_events(record_id=record.record_id)]
        payload = self._serialize_provisional_record(record)
        worthiness = self._provisional_review_worthiness(record)
        bridge_eligible = self._provisional_bridge_eligible(record)
        payload.update(
            {
                "review_candidate_id": f"prc_{record.record_id}",
                "bridge_state": "candidate_only",
                "review_path": "existing_review_pipeline",
                "lineage_record_ids": self._provisional_lineage_record_ids(record),
                "history": events,
                "history_event_count": len(events),
                "human_review_required": True,
                "bridge_eligible": bridge_eligible,
                "bridge_action": "PROPOSE_CREATE" if bridge_eligible else None,
                **worthiness,
            }
        )
        return payload

    def _auto_session_label(self, *, created_at: datetime, topic_hint: str | None) -> str:
        local = created_at.astimezone(timezone.utc)
        stamp = local.strftime("%Y-%m-%d %H:%MZ")
        topic = str(topic_hint or "").strip() or "general"
        topic_clean = self._compact_text(topic, max_chars=64)
        return f"{stamp} · {topic_clean}"

    def _session_topic_hint(self, text: str) -> str:
        informative = self._ordered_informative_tokens(text)
        ranked: list[str] = []
        for token in informative:
            if token in _NAME_FREQ_IGNORE_TOKENS:
                continue
            if len(token) < 3:
                continue
            ranked.append(token)
            if len(ranked) >= 2:
                break
        if not ranked:
            return "general"
        return " ".join(ranked)

    def _ensure_session(self, session_id: str | None, *, label: str | None = None) -> SessionState:
        normalized = self._normalize_session_id(session_id)
        with self._lock:
            session = self._sessions.get(normalized)
            if session is None:
                session = self._new_session_state(normalized, label=label)
                self._sessions[normalized] = session
        return session

    def _prewarm_runtime_caches(self) -> None:
        try:
            warm_retriever = getattr(self.retriever, "prewarm", None)
            if callable(warm_retriever):
                supports_continuity = False
                try:
                    signature = inspect.signature(warm_retriever)
                    params = signature.parameters
                    supports_continuity = "continuity_store" in params or any(
                        param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()
                    )
                except (TypeError, ValueError):
                    supports_continuity = False
                if supports_continuity:
                    warm_retriever(continuity_store=self.continuity_store)
                else:
                    # Backward compatibility for retrievers with legacy prewarm() signatures.
                    warm_retriever()
        except Exception as exc:
            _LOGGER.warning("retriever prewarm failed: %s", exc)
        try:
            warm_continuity = getattr(self.continuity_store, "warm_snapshot_cache", None)
            if callable(warm_continuity):
                warm_continuity()
        except Exception as exc:
            _LOGGER.warning("continuity cache prewarm failed: %s", exc)

    def _load_episode_index(self, path: str) -> EpisodeCardIndex | None:
        cleaned = str(path or "").strip()
        if not cleaned:
            return None
        try:
            return EpisodeCardIndex.load(cleaned)
        except Exception as exc:
            _LOGGER.warning("episode card index load failed: %s", exc)
            return None

    def _episode_query_candidates(self, user_text: str, retrieval_text: str) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def _push(value: str) -> None:
            cleaned = str(value or "").strip()
            if not cleaned:
                return
            key = cleaned.lower()
            if key in seen:
                return
            seen.add(key)
            ordered.append(cleaned)

        for quoted in _QUOTE_RE.findall(user_text):
            _push(quoted)
        for quoted in _QUOTE_RE.findall(retrieval_text):
            _push(quoted)
        for focus in _ABOUT_FOCUS_RE.findall(user_text):
            _push(focus)
        for focus in _WHO_FOCUS_RE.findall(user_text):
            _push(focus)
        for focus in _ABOUT_FOCUS_RE.findall(retrieval_text):
            _push(focus)
        for focus in _WHO_FOCUS_RE.findall(retrieval_text):
            _push(focus)
        _push(user_text)
        _push(retrieval_text)
        informative = self._ordered_informative_tokens(user_text)
        if informative:
            _push(" ".join(informative[:3]))
            if len(informative) >= 2:
                _push(" ".join(informative[:2]))
        for token in informative[:8]:
            if "_" in token or any(ch.isdigit() for ch in token) or len(token) >= 6:
                _push(token)
        retrieval_tokens = self._ordered_informative_tokens(retrieval_text)
        if retrieval_tokens and len(retrieval_tokens) <= 8:
            _push(" ".join(retrieval_tokens))
        return ordered[:6]

    def _episode_hits(self, *, user_text: str, retrieval_text: str) -> list[EpisodeHit]:
        index = self._episode_index
        if index is None:
            return []
        merged: dict[str, EpisodeHit] = {}
        for query in self._episode_query_candidates(user_text, retrieval_text):
            try:
                hits = index.search(query, top_k=self.episode_top_k)
            except Exception as exc:
                _LOGGER.warning("episode card query failed: %s", exc)
                continue
            for item in hits:
                if item.score < self.episode_min_score:
                    continue
                episode_id = str(item.card.episode_id or "").strip()
                if not episode_id:
                    continue
                current = merged.get(episode_id)
                if current is None or item.score > current.score:
                    merged[episode_id] = item
        out = sorted(merged.values(), key=lambda item: item.score, reverse=True)
        return out[: self.episode_top_k]

    def _episode_hits_to_pack(self, hits: list[EpisodeHit]) -> MemoryPack:
        if not hits:
            return MemoryPack()

        def _ref_timestamp(raw_value: str) -> datetime:
            text = str(raw_value or "").strip()
            if not text:
                return _utc_now()
            try:
                parsed = datetime.fromisoformat(text)
            except Exception:
                return _utc_now()
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        core: list[MemoryPackItem] = []
        context: list[MemoryPackItem] = []
        confidence_values: list[float] = []
        for idx, hit in enumerate(hits):
            card = hit.card
            refs: list[SourceRef] = []
            timestamp = _ref_timestamp(str(card.start_at or card.end_at or ""))
            for citation in list(card.citations):
                source, sep, message = str(citation).partition("#")
                source_id = source.strip()
                message_id = message.strip() if sep else ""
                if not source_id:
                    continue
                refs.append(
                    SourceRef(
                        source_id=source_id,
                        message_id=message_id,
                        timestamp=timestamp,
                        span_start=0,
                        span_end=max(1, len(card.summary)),
                    )
                )
            if not refs:
                refs.append(
                    SourceRef(
                        source_id=str(card.source_id or "episode"),
                        message_id=str(card.episode_id or ""),
                        timestamp=timestamp,
                        span_start=0,
                        span_end=max(1, len(card.summary)),
                    )
                )

            item = MemoryPackItem(
                atom_id=f"episode_card:{card.episode_id}",
                canonical_text=(
                    f"{str(card.title or '').strip()}: {str(card.summary or '').strip()}"
                    if str(card.title or "").strip()
                    else str(card.summary or "").strip()
                ),
                confidence=_clamp01(float(hit.score)),
                source_refs=refs,
                record_updated_at=timestamp,
                conflict_state="active",
                memory_layer="published_episode",
                trust_tier="published",
            )
            confidence_values.append(item.confidence)
            if idx == 0:
                core.append(item)
            else:
                context.append(item)

        pack_confidence = _clamp01(sum(confidence_values) / max(1, len(confidence_values)))
        return memory_pack_from_items(core, context=context, pack_confidence=pack_confidence)

    @staticmethod
    def _pack_retrieved_ids(pack: MemoryPack) -> list[str]:
        """Return the bounded evidence-set IDs actually carried in the pack.

        This intentionally excludes broad rerank candidate lists so eval + readouts reflect what
        the verifier/response layer actually consumed.
        """

        out: list[str] = []
        seen: set[str] = set()
        for item in list(pack.core) + list(pack.context) + list(pack.continuity) + list(pack.conflict):
            atom_id = str(getattr(item, "atom_id", "") or "").strip()
            if not atom_id or atom_id in seen:
                continue
            seen.add(atom_id)
            out.append(atom_id)
        return out

    def _build_retrieval_diagnostics(self, *, pack: MemoryPack, retrieval: Any | None) -> dict[str, Any]:
        score_by_id: dict[str, float] = {}
        dropped_reason_counts: dict[str, int] = {}
        dropped_order: list[str] = []
        dropped_seen: set[str] = set()
        dropped_raw = getattr(retrieval, "dropped_reasons", {}) if retrieval is not None else {}
        scored_atoms = list(getattr(retrieval, "scored_atoms", []) or []) if retrieval is not None else []
        profile_used = str(getattr(retrieval, "profile_used", "") or "").strip()
        ann = getattr(retrieval, "ann", None)
        helper_lanes = list(getattr(retrieval, "helper_lanes", []) or []) if retrieval is not None else []

        for scored in scored_atoms:
            atom = getattr(scored, "atom", None)
            atom_id = str(getattr(atom, "atom_id", "") or "").strip()
            if not atom_id:
                continue
            score_by_id.setdefault(atom_id, _clamp01(float(getattr(scored, "score", 0.0) or 0.0)))
            if atom_id in dropped_raw and atom_id not in dropped_seen:
                dropped_seen.add(atom_id)
                dropped_order.append(atom_id)

        for atom_id_raw, reason_raw in dict(dropped_raw or {}).items():
            atom_id = str(atom_id_raw or "").strip()
            reason = str(reason_raw or "").strip()
            if not atom_id or not reason:
                continue
            dropped_reason_counts[reason] = dropped_reason_counts.get(reason, 0) + 1
            if atom_id not in dropped_seen:
                dropped_seen.add(atom_id)
                dropped_order.append(atom_id)

        selected: list[RetrievalSelectedAtomContract] = []
        for section, items in (
            ("core", list(pack.core)),
            ("context", list(pack.context)),
            ("continuity", list(pack.continuity)),
            ("conflict", list(pack.conflict)),
        ):
            for item in items:
                atom_id = str(getattr(item, "atom_id", "") or "").strip()
                if not atom_id:
                    continue
                selected.append(
                    RetrievalSelectedAtomContract(
                        atom_id=atom_id,
                        section=section,
                        score=score_by_id.get(atom_id, _clamp01(float(getattr(item, "confidence", 0.0) or 0.0))),
                    )
                )

        dropped: list[RetrievalDroppedAtomContract] = []
        for atom_id in dropped_order[:24]:
            reason = str(dict(dropped_raw or {}).get(atom_id) or "").strip()
            if not reason:
                continue
            dropped.append(
                RetrievalDroppedAtomContract(
                    atom_id=atom_id,
                    reason_code=reason,
                    score=score_by_id.get(atom_id),
                )
            )

        diagnostics = RetrievalDiagnosticsContract(
            selected=selected[:24],
            dropped=dropped,
            dropped_reason_counts=dropped_reason_counts,
            profile_used=profile_used,
            selected_count=len(selected),
            dropped_count=sum(dropped_reason_counts.values()),
            raw_text_included=False,
            helper_lanes=[
                lane
                for lane in helper_lanes
                if isinstance(lane, RetrievalHelperLaneContract)
            ],
            ann_enabled=bool(getattr(ann, "enabled", False)),
            ann_used=bool(getattr(ann, "used", False)),
            ann_candidate_count=int(getattr(ann, "candidate_count", 0) or 0),
            ann_latency_ms=float(getattr(ann, "latency_ms", 0.0) or 0.0),
            ann_fallback_reason=str(getattr(ann, "fallback_reason", "") or "").strip(),
            ann_store_fingerprint=str(getattr(ann, "store_fingerprint", "") or "").strip(),
            ann_backend_version=str(getattr(ann, "backend_version", "") or "").strip(),
        )
        return contract_to_dict(diagnostics)

    def _augment_pack_with_episode_context(
        self,
        pack: MemoryPack,
        hits: list[EpisodeHit],
        *,
        recall_priority: bool = False,
        max_injected: int = 2,
    ) -> MemoryPack:
        """Allow episode cards to contribute without forcing an all-or-nothing short-circuit."""

        if not hits:
            return pack
        episode_pack = self._episode_hits_to_pack(hits)
        if not episode_pack.core:
            return pack

        existing = {item.atom_id for item in list(pack.core) + list(pack.context) + list(pack.continuity) + list(pack.conflict)}
        injected: list[MemoryPackItem] = []
        candidates = list(episode_pack.core) + list(episode_pack.context)
        for item in candidates[: max(1, int(max_injected))]:
            if item.atom_id in existing:
                continue
            injected.append(item)
            existing.add(item.atom_id)
        if not injected:
            return pack

        if recall_priority:
            primary = injected[:1]
            secondary = injected[1:]
            primary_ids = {item.atom_id for item in primary}
            retained_core: list[MemoryPackItem] = []
            demoted_fragments: list[MemoryPackItem] = []
            for item in list(pack.core):
                if item.atom_id in primary_ids:
                    continue
                if self._is_fragmentary_atom_detail(item):
                    demoted_fragments.append(item)
                    continue
                retained_core.append(item)
            pack.core = primary + retained_core
            if len(pack.core) > 4:
                spill = list(pack.core)[4:]
                demoted_fragments.extend(spill)
                pack.core = list(pack.core)[:4]
            pack.context = secondary + demoted_fragments + list(pack.context)
        else:
            pack.context = injected + list(pack.context)
        if len(pack.context) > 8:
            pack.context = list(pack.context)[:8]
        pack.pack_confidence = _clamp01(pack.pack_confidence * 0.85 + episode_pack.pack_confidence * 0.15)
        return pack

    def _is_fragmentary_atom_detail(self, item: MemoryPackItem) -> bool:
        atom_id = str(getattr(item, "atom_id", "") or "").strip()
        if atom_id.startswith("episode_card:"):
            return False
        text = str(getattr(item, "canonical_text", "") or "").strip().lower()
        if not text:
            return True
        tokens = [token for token in _tokenize(text) if token]
        informative = [token for token in tokens if len(token) >= 4 and token not in _INFO_STOPWORDS]
        has_event_signal = any(
            token in {
                "before",
                "after",
                "then",
                "later",
                "next",
                "reviewed",
                "planned",
                "decided",
                "built",
                "confirmed",
                "launched",
                "shipped",
                "updated",
            }
            for token in tokens
        )
        if has_event_signal:
            return False
        if len(informative) < 8:
            return True
        if len(tokens) < 12 and float(getattr(item, "confidence", 0.0) or 0.0) < 0.72:
            return True
        return False

    def _episode_retrieved_ids(self, hits: list[EpisodeHit]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for hit in hits:
            episode_id = str(hit.card.episode_id or "").strip()
            if episode_id:
                wrapped = f"episode_card:{episode_id}"
                if wrapped not in seen:
                    seen.add(wrapped)
                    out.append(wrapped)
            for atom_id in list(hit.card.atom_ids or []):
                clean = str(atom_id or "").strip()
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                out.append(clean)
        return out

    def _can_short_circuit_episode_primary(
        self,
        hits: list[EpisodeHit],
        *,
        user_text: str = "",
        retrieval_text: str = "",
    ) -> bool:
        if not hits:
            return False
        if self._has_specific_recall_anchor(text=user_text) or self._has_specific_recall_anchor(text=retrieval_text):
            return False
        top = hits[0]
        if float(top.score) < float(self.episode_primary_min_score):
            return False
        if float(top.cue_match) >= float(self.episode_primary_min_cue_match):
            return True
        return float(top.lexical) >= float(self.episode_primary_min_lexical) and float(top.semantic) >= 0.14

    def _get_session(self, session_id: str | None) -> SessionState | None:
        normalized = self._normalize_session_id(session_id)
        with self._lock:
            return self._sessions.get(normalized)

    def start_session(self, *, label: str | None = None) -> dict[str, Any]:
        session_id = f"sess_{uuid4().hex[:12]}"
        session = self._ensure_session(session_id, label=label)
        return {
            "session_id": session.session_id,
            "label": session.label,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "turn_count": len(session.turn_ids),
            "rolling_summary": session.rolling_summary,
        }

    def rename_session(self, session_id: str, *, label: str) -> dict[str, Any]:
        normalized = self._normalize_session_id(session_id)
        cleaned = self._compact_text(str(label or "").strip(), max_chars=120)
        if not cleaned:
            raise ValueError("label is required")
        with self._lock:
            session = self._sessions.get(normalized)
            if session is None:
                raise KeyError(normalized)
            session.label = cleaned
            session.label_auto = False
            session.updated_at = _utc_now()
            return {
                "session_id": session.session_id,
                "label": session.label,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "turn_count": len(session.turn_ids),
                "rolling_summary": session.rolling_summary,
            }

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return [
            {
                "session_id": item.session_id,
                "label": item.label,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
                "turn_count": len(item.turn_ids),
                "rolling_summary": item.rolling_summary,
                "short_term_notes": len(item.short_term),
                "working_set_tokens": self._session_working_set_tokens(item),
            }
            for item in sessions
        ]

    def get_session_history(self, session_id: str) -> list[TurnTrace]:
        session = self._get_session(session_id)
        if session is None:
            raise KeyError(self._normalize_session_id(session_id))
        with self._lock:
            turn_ids = list(session.turn_ids)
            traces = {trace.turn_id: trace for trace in self._turns}
        return [traces[item] for item in turn_ids if item in traces]

    def get_session_telemetry(self, session_id: str) -> dict[str, Any]:
        history = self.get_session_history(session_id)
        session = self._get_session(session_id)
        if session is None:
            raise KeyError(self._normalize_session_id(session_id))
        if not history:
            return {
                "session_id": session.session_id,
                "label": session.label,
                "turn_count": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "p95_latency_ms": 0.0,
                "route_counts": {
                    "none": 0,
                    "stm_only": 0,
                    "ltm_light": 0,
                    "ltm_deep": 0,
                },
                "memory_preference_counts": {
                    "auto": 0,
                    "chat_first": 0,
                    "memory_assist": 0,
                    "session_recall": 0,
                },
                "rolling_summary": session.rolling_summary,
                "short_term_notes": len(session.short_term),
                "working_set_tokens": self._session_working_set_tokens(session),
            }
        latencies = sorted(float(item.telemetry.total_ms) for item in history)
        idx = max(0, min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1)))))
        route_counts = {
            "none": 0,
            "stm_only": 0,
            "ltm_light": 0,
            "ltm_deep": 0,
        }
        memory_preference_counts = {
            "auto": 0,
            "chat_first": 0,
            "memory_assist": 0,
            "session_recall": 0,
        }
        total_tokens = 0
        total_cost = 0.0
        for item in history:
            total_tokens += int(item.telemetry.input_tokens) + int(item.telemetry.output_tokens)
            total_cost += float(item.telemetry.turn_cost_usd)
            route = str(item.memory_route or "ltm_light")
            if route in route_counts:
                route_counts[route] += 1
            preference = str(item.memory_preference or "auto")
            if preference in memory_preference_counts:
                memory_preference_counts[preference] += 1
        return {
            "session_id": session.session_id,
            "label": session.label,
            "turn_count": len(history),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "p95_latency_ms": latencies[idx],
            "route_counts": route_counts,
            "memory_preference_counts": memory_preference_counts,
            "rolling_summary": session.rolling_summary,
            "short_term_notes": len(session.short_term),
            "working_set_tokens": self._session_working_set_tokens(session),
        }

    def get_runtime_telemetry_summary(self, *, limit: int = 200) -> dict[str, Any]:
        window = max(1, int(limit))
        with self._lock:
            traces = list(self._turns[-window:])
        if not traces:
            return {
                "turns_considered": 0,
                "total_turns_seen": 0,
                "avg_total_ms": 0.0,
                "avg_retrieval_ms": 0.0,
                "avg_verifier_ms": 0.0,
                "avg_retrieval_passes": 0.0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "route_counts": {"none": 0, "stm_only": 0, "ltm_light": 0, "ltm_deep": 0},
                "memory_preference_counts": {"auto": 0, "chat_first": 0, "memory_assist": 0, "session_recall": 0},
                "mode_counts": {"none": 0, "stm_primary": 0, "hybrid": 0, "ltm_only": 0},
                "route_reason_counts": {},
                "stop_reason_counts": {},
                "warning_code_counts": {},
                "warn_turns": 0,
            }

        route_counts = {"none": 0, "stm_only": 0, "ltm_light": 0, "ltm_deep": 0}
        memory_preference_counts = {"auto": 0, "chat_first": 0, "memory_assist": 0, "session_recall": 0}
        mode_counts = {"none": 0, "stm_primary": 0, "hybrid": 0, "ltm_only": 0}
        route_reason_counts: dict[str, int] = {}
        stop_reason_counts: dict[str, int] = {}
        warning_code_counts: dict[str, int] = {}
        warn_turns = 0
        total_tokens = 0
        total_cost_usd = 0.0
        total_ms = 0.0
        retrieval_ms = 0.0
        verifier_ms = 0.0
        retrieval_pass_total = 0

        for trace in traces:
            route = str(trace.memory_route or "ltm_light")
            if route in route_counts:
                route_counts[route] += 1
            preference = str(trace.memory_preference or "auto")
            if preference in memory_preference_counts:
                memory_preference_counts[preference] += 1
            mode = str(trace.memory_mode or "none")
            if mode in mode_counts:
                mode_counts[mode] += 1
            route_reason = str(trace.route_reason or "unknown")
            route_reason_counts[route_reason] = int(route_reason_counts.get(route_reason, 0)) + 1
            stop_reason = str(trace.retrieval_stop_reason or "unknown")
            stop_reason_counts[stop_reason] = int(stop_reason_counts.get(stop_reason, 0)) + 1
            budget = self._budget_ledger_for_trace(trace)
            warnings = list(budget.get("warnings") or [])
            if warnings:
                warn_turns += 1
            for warning in warnings:
                code = str((warning or {}).get("code") or "").strip()
                if not code:
                    continue
                warning_code_counts[code] = int(warning_code_counts.get(code, 0)) + 1
            total_tokens += int(trace.telemetry.input_tokens) + int(trace.telemetry.output_tokens)
            total_cost_usd += float(trace.telemetry.turn_cost_usd)
            total_ms += float(trace.telemetry.total_ms)
            retrieval_ms += float(trace.telemetry.retrieval_ms)
            verifier_ms += float(trace.telemetry.verifier_ms)
            retrieval_pass_total += int(trace.retrieval_passes)

        turns = len(traces)
        with self._lock:
            total_turns_seen = len(self._turns)
        return {
            "turns_considered": turns,
            "total_turns_seen": total_turns_seen,
            "avg_total_ms": total_ms / max(1, turns),
            "avg_retrieval_ms": retrieval_ms / max(1, turns),
            "avg_verifier_ms": verifier_ms / max(1, turns),
            "avg_retrieval_passes": retrieval_pass_total / max(1, turns),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost_usd,
            "route_counts": route_counts,
            "memory_preference_counts": memory_preference_counts,
            "mode_counts": mode_counts,
            "route_reason_counts": route_reason_counts,
            "stop_reason_counts": stop_reason_counts,
            "warning_code_counts": warning_code_counts,
            "warn_turns": warn_turns,
        }

    def get_runtime_telemetry_turns(self, *, limit: int = 40) -> list[dict[str, Any]]:
        window = max(1, int(limit))
        with self._lock:
            traces = list(self._turns[-window:])
        rows: list[dict[str, Any]] = []
        for trace in reversed(traces):
            budget = self._budget_ledger_for_trace(trace)
            warnings = [str((item or {}).get("code") or "").strip() for item in list(budget.get("warnings") or [])]
            warning_codes = [code for code in warnings if code]
            rows.append(
                {
                    "turn_id": trace.turn_id,
                    "session_id": trace.session_id,
                    "timestamp": trace.timestamp.isoformat(),
                    "decision": str(trace.decision or ""),
                    "memory_route": str(trace.memory_route or ""),
                    "route_reason": str(trace.route_reason or ""),
                    "route_reason_text": str(trace.route_reason_text or ""),
                    "memory_preference": str(trace.memory_preference or "auto"),
                    "retrieval_passes": int(trace.retrieval_passes),
                    "retrieval_stop_reason": str(trace.retrieval_stop_reason or ""),
                    "latency_ms": float(trace.telemetry.total_ms),
                    "turn_tokens": int(trace.telemetry.input_tokens) + int(trace.telemetry.output_tokens),
                    "turn_cost_usd": float(trace.telemetry.turn_cost_usd),
                    "warning_state": str(budget.get("warning_state") or "ok"),
                    "warning_codes": warning_codes,
                }
            )
        return rows

    def handle_turn(
        self,
        message: str,
        *,
        high_risk: bool = False,
        retrieval_query: str | None = None,
        retrieval_override: RetrievalOverrideRequestContract | None = None,
        memory_preference: str | None = None,
        session_id: str | None = None,
    ) -> TurnTrace:
        text = str(message or "").strip()
        if not text:
            raise ValueError("message is required")
        session = self._ensure_session(session_id)
        self._handle_soft_close_state(session=session, upcoming_text=text)
        memory_pref = self._normalize_memory_preference(memory_preference)
        turn_id = f"turn_{uuid4().hex}"
        started = time.perf_counter()
        front_desk = self._route_turn(text=text, high_risk=high_risk, memory_preference=memory_pref)
        override_resolution = self._resolve_retrieval_override(
            message=text,
            retrieval_query=retrieval_query,
            retrieval_override=retrieval_override,
            decision=front_desk,
        )
        retrieval_text = override_resolution.retrieval_text
        gate_text = retrieval_text
        retrieval_query_tokens = _token_estimate(retrieval_text)
        memory_route = override_resolution.decision.route
        route_reason = override_resolution.decision.reason
        isolate_stm_from_ltm = self._should_isolate_stm_from_ltm_evidence(
            memory_route=str(memory_route or ""),
            route_reason=str(route_reason or ""),
            user_text=text,
        )

        retrieve_start = time.perf_counter()
        stm_pack, stm_ids, stm_hits, stm_best = self._retrieve_short_term(text, session=session)
        memory_mode = "none"
        retrieved_atom_ids: list[str] = []
        retrieval = None
        pack = MemoryPack()
        retrieval_passes = 0
        retrieval_stop_reason = "route_skip"
        episode_hits: list[EpisodeHit] = []
        retrieval_override_active = bool(override_resolution.audit.applied)

        if memory_route == "none":
            pass
        elif memory_route == "stm_only":
            if stm_hits > 0:
                memory_mode = "stm_primary"
                pack = stm_pack
                retrieved_atom_ids = list(stm_ids)
        elif memory_route in {"ltm_light", "ltm_deep"}:
            if (
                memory_route == "ltm_light"
                and stm_hits > 0
                and stm_best >= self.short_term_primary_score
                and not isolate_stm_from_ltm
            ):
                memory_mode = "stm_primary"
                pack = stm_pack
                retrieved_atom_ids = list(stm_ids)
            else:
                episode_hits = self._episode_hits(user_text=text, retrieval_text=retrieval_text)
                if (
                    episode_hits
                    and not high_risk
                    and not retrieval_override_active
                    and self._can_short_circuit_episode_primary(
                        episode_hits,
                        user_text=text,
                        retrieval_text=retrieval_text,
                    )
                ):
                    memory_mode = "ltm_only"
                    retrieval_passes = 1
                    retrieval_stop_reason = "episode_primary_satisfied"
                    ltm_pack = self._episode_hits_to_pack(episode_hits)
                    ltm_ids = self._episode_retrieved_ids(episode_hits)
                else:
                    memory_mode = "ltm_only"
                    retrieval_outcome = self._retrieve_ltm(
                        retrieval_text,
                        retrieval_override_active=retrieval_override_active,
                        profile_override=self._retrieval_profile_override(memory_pref, route_reason=route_reason),
                    )
                    retrieval = retrieval_outcome.retrieval
                    retrieval_passes = retrieval_outcome.passes_used
                    retrieval_stop_reason = retrieval_outcome.stop_reason
                    ltm_pack = retrieval.memory_pack
                    ltm_ids = list(retrieval.ranked_atom_ids)
                    if episode_hits and not high_risk:
                        ltm_pack = self._augment_pack_with_episode_context(
                            ltm_pack,
                            episode_hits,
                            recall_priority=self._is_recall_style_prompt(text),
                        )
                provisional_pack, provisional_ids, _provisional_hits, _provisional_best = self._retrieve_provisional_memory(retrieval_text)
                if provisional_ids:
                    ltm_pack = self._merge_long_term_with_provisional(ltm_pack, provisional_pack)
                    ltm_seen = set(ltm_ids)
                    ltm_ids = list(ltm_ids) + [item_id for item_id in provisional_ids if item_id not in ltm_seen]
                if stm_hits > 0 and not isolate_stm_from_ltm:
                    memory_mode = "hybrid"
                    pack = self._merge_packs(stm_pack, ltm_pack)
                    stm_id_set = set(stm_ids)
                    retrieved_atom_ids = list(stm_ids) + [atom_id for atom_id in ltm_ids if atom_id not in stm_id_set]
                else:
                    pack = ltm_pack
                    retrieved_atom_ids = ltm_ids
        else:
            retrieval_outcome = self._retrieve_ltm(
                retrieval_text,
                retrieval_override_active=retrieval_override_active,
                profile_override=self._retrieval_profile_override(memory_pref, route_reason=route_reason),
            )
            retrieval = retrieval_outcome.retrieval
            retrieval_passes = retrieval_outcome.passes_used
            retrieval_stop_reason = retrieval_outcome.stop_reason
            ltm_pack = retrieval.memory_pack
            ltm_ids = list(retrieval.ranked_atom_ids)
            if stm_hits > 0 and not isolate_stm_from_ltm:
                memory_mode = "hybrid"
                pack = self._merge_packs(stm_pack, ltm_pack)
                stm_id_set = set(stm_ids)
                retrieved_atom_ids = list(stm_ids) + [atom_id for atom_id in ltm_ids if atom_id not in stm_id_set]
            else:
                pack = ltm_pack
                retrieved_atom_ids = ltm_ids

        # Keep retrieved_atom_ids aligned with the evidence pack (not broad rerank candidate lists).
        if pack.core or pack.context or pack.continuity or pack.conflict:
            pack = self._prune_consumer_meta_evidence(
                pack,
                route_reason=route_reason,
                user_text=text,
            )
            retrieved_atom_ids = self._pack_retrieved_ids(pack)

        if memory_mode == "stm_primary":
            retrieval_stop_reason = "stm_primary_satisfied"
        elif memory_mode == "none":
            retrieval_stop_reason = "route_skip"

        retrieval_ms = (time.perf_counter() - retrieve_start) * 1000.0
        retrieval_diagnostics = self._build_retrieval_diagnostics(pack=pack, retrieval=retrieval)
        claims = self._candidate_claims(pack)

        verify_start = time.perf_counter()
        if memory_route == "none":
            verification = VerificationResult(
                decision=VerificationDecision.NO_MEMORY,
                checks=[],
                unsupported_claims=[],
                needs_uncertainty=False,
            )
        elif claims:
            verification = self.verifier.verify(claims, pack, high_risk = high_risk)
        else:
            unsupported = "STM_EMPTY_ROUTE" if memory_route == "stm_only" else "NO_EVIDENCE_CLAIMS"
            verification = VerificationResult(
                decision=VerificationDecision.ABSTAIN,
                checks=[],
                unsupported_claims=[unsupported],
                needs_uncertainty=False,
            )
        if retrieval is not None:
            verification = self._apply_query_evidence_gate(
                verification,
                retrieval,
                gate_text,
                support_pack=pack,
            )
        elif memory_route != "none":
            verification = self._apply_pack_query_gate(
                verification,
                pack,
                gate_text,
                high_risk=high_risk,
            )
        verification = self._enforce_direct_citation_gate(
            verification,
            pack,
            memory_route=memory_route,
        )
        verifier_ms = (time.perf_counter() - verify_start) * 1000.0

        memory_cards = [self._card_to_dict(item) for item in self._assemble_memory_cards(pack)]
        memory_cards = self._rank_memory_cards_for_response(user_text=text, memory_cards=memory_cards)
        memory_cards = self._annotate_memory_card_conflicts(user_text=text, memory_cards=memory_cards)
        response_text, citations = self._compose_response(
            text,
            verification,
            pack,
            memory_cards=memory_cards,
            memory_route=memory_route,
        )
        total_ms = (time.perf_counter() - started) * 1000.0

        input_tokens = _token_estimate(text)
        output_tokens = _token_estimate(response_text)
        turn_cost = self._cost_usd(input_tokens=input_tokens, output_tokens=output_tokens)

        with self._lock:
            self._stats.turns += 1
            self._stats.total_input_tokens += input_tokens
            self._stats.total_output_tokens += output_tokens
            self._stats.total_cost_usd += turn_cost
            self._latencies.append(total_ms)
            self._stats.p95_latency_ms = self._p95(self._latencies)
            if memory_mode == "stm_primary":
                self._stats.stm_primary_turns += 1
            elif memory_mode == "hybrid":
                self._stats.hybrid_turns += 1
            elif memory_mode == "ltm_only":
                self._stats.ltm_only_turns += 1

            if memory_route == "none":
                self._stats.route_none_turns += 1
            elif memory_route == "stm_only":
                self._stats.route_stm_only_turns += 1
            elif memory_route == "ltm_deep":
                self._stats.route_ltm_deep_turns += 1
            else:
                self._stats.route_ltm_light_turns += 1

            telemetry = TurnTelemetry(
                retrieval_ms=retrieval_ms,
                verifier_ms=verifier_ms,
                total_ms=total_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                turn_cost_usd=turn_cost,
                cumulative_tokens=self._stats.total_input_tokens + self._stats.total_output_tokens,
                cumulative_cost_usd=self._stats.total_cost_usd,
            )
            trace = TurnTrace(
                turn_id=turn_id,
                session_id=session.session_id,
                timestamp=_utc_now(),
                user_text=text,
                response_text=response_text,
                decision=verification.decision.value,
                citations=citations,
                pack_confidence=pack.pack_confidence,
                retrieved_atom_ids=retrieved_atom_ids,
                memory_mode=memory_mode,
                memory_route=memory_route,
                route_reason=route_reason,
                route_reason_text=self._route_reason_text(route_reason),
                retrieval_passes=retrieval_passes,
                retrieval_query_tokens=retrieval_query_tokens,
                retrieval_stop_reason=retrieval_stop_reason,
                retrieval_override=override_resolution.audit,
                retrieval_diagnostics=retrieval_diagnostics,
                memory_preference=memory_pref,
                short_term_hits=stm_hits,
                memory_cards=memory_cards,
                telemetry=telemetry,
                claim_checks=[self._check_to_dict(item) for item in verification.checks],
            )
            self._turns.append(trace)
            session.turn_ids.append(turn_id)
            if session.label_auto:
                topic_hint = self._session_topic_hint(text)
                session.label = self._auto_session_label(created_at=session.created_at, topic_hint=topic_hint)
            session.updated_at = trace.timestamp

        if self.enable_writeback and self._executor is not None:
            writeback = self._enqueue_writeback(trace, verification, pack)
            with self._lock:
                trace.writeback_event_id = writeback.event_id
        self._remember_short_term(
            turn_id=turn_id,
            user_text=text,
            response_text=response_text,
            session=session,
        )
        if self._provisional_memory_enabled:
            self._capture_provisional_turn(
                turn_id=turn_id,
                session=session,
                user_text=text,
                response_text=response_text,
                timestamp=trace.timestamp,
            )
            if self._looks_like_soft_close_hint(text) or self._looks_like_soft_close_hint(response_text):
                with self._lock:
                    session.soft_close_hint_at = trace.timestamp
                    session.soft_close_hint_text = text if self._looks_like_soft_close_hint(text) else response_text
        return trace

    def list_turns(self) -> list[TurnTrace]:
        with self._lock:
            return list(self._turns)

    def get_turn(self, turn_id: str) -> TurnTrace | None:
        with self._lock:
            for turn in self._turns:
                if turn.turn_id == turn_id:
                    return turn
        return None

    def get_writeback(self, event_id: str) -> WritebackEvent | None:
        with self._lock:
            return self._writebacks.get(event_id)

    def preview_route(
        self,
        message: str,
        *,
        high_risk: bool = False,
        memory_preference: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            raise ValueError("message is required")
        memory_pref = self._normalize_memory_preference(memory_preference)
        normalized = text.lower()
        decision = self._route_turn(text=text, high_risk=high_risk, memory_preference=memory_pref)
        memory_signal_score = self._memory_signal_score(normalized)
        session = self._preview_session(session_id)
        _stm_pack, _stm_ids, stm_hits, stm_best = self._retrieve_short_term(text, session=session)
        predicted_mode, arbitration_reason, will_query_ltm = self._predict_memory_mode(
            route=decision.route,
            stm_hits=stm_hits,
            stm_best=stm_best,
        )
        return {
            "route": decision.route,
            "reason": decision.reason,
            "reason_text": self._route_reason_text(decision.reason),
            "memory_preference": memory_pref,
            "high_risk": bool(high_risk),
            "memory_signal": memory_signal_score >= self.memory_signal_min_score,
            "memory_signal_score": round(memory_signal_score, 4),
            "session_id": session.session_id,
            "stm_hit_count": int(stm_hits),
            "stm_best_score": round(float(stm_best), 4),
            "stm_primary_threshold": round(float(self.short_term_primary_score), 4),
            "predicted_memory_mode": predicted_mode,
            "will_query_ltm": bool(will_query_ltm),
            "arbitration_reason": arbitration_reason,
        }

    def build_context_package(
        self,
        message: str,
        *,
        high_risk: bool = False,
        memory_preference: str | None = None,
        session_id: str | None = None,
        package_version: str | None = None,
        retrieval_query: str | None = None,
        retrieval_override: RetrievalOverrideRequestContract | None = None,
        render_citations: bool | None = None,
        include_work_session_context: bool = True,
        include_work_session_diagnostics: bool = False,
        work_session_scope: dict[str, Any] | None = None,
        explicit_resume: bool = False,
    ) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            raise ValueError("message is required")
        version = str(package_version or "v1").strip().lower() or "v1"
        if version not in {"v1", "v2"}:
            raise ValueError(f"unsupported package_version: {package_version}")
        if version == "v2":
            return self._build_context_package_v2(
                text,
                high_risk=high_risk,
                memory_preference=memory_preference,
                session_id=session_id,
                retrieval_query=retrieval_query,
                retrieval_override=retrieval_override,
                render_citations=render_citations,
                include_work_session_context=include_work_session_context,
                include_work_session_diagnostics=include_work_session_diagnostics,
                work_session_scope=work_session_scope,
                explicit_resume=explicit_resume,
            )

        preview = self.preview_route(
            text,
            high_risk=high_risk,
            memory_preference=memory_preference,
            session_id=session_id,
        )
        session = self._preview_session(session_id)
        stm_pack, _stm_ids, stm_hits, _stm_best = self._retrieve_short_term(text, session=session)
        stm_cards_full = [self._card_to_dict(item) for item in self._assemble_memory_cards(stm_pack)[:3]]
        stm_cards = [self._compact_card_dict(item) for item in stm_cards_full]
        with self._lock:
            short_term_notes = list(session.short_term)
            rolling_summary = str(session.rolling_summary or "").strip()
        top_notes = [str(item.text or "").strip() for item in short_term_notes[-6:] if str(item.text or "").strip()]
        if len(top_notes) > 3:
            top_notes = top_notes[-3:]
        return {
            "package_version": "v1",
            "message": text,
            "preview": preview,
            "working_set": {
                "session_id": session.session_id,
                "short_term_notes": len(short_term_notes),
                "short_term_hits": int(stm_hits),
                "rolling_summary": rolling_summary,
                "top_notes": top_notes,
                "memory_cards": stm_cards,
                "memory_cards_full_count": len(stm_cards_full),
            },
            "ltm_query_plan": {
                "will_query_ltm": bool(preview.get("will_query_ltm")),
                "predicted_memory_mode": str(preview.get("predicted_memory_mode") or "none"),
                "max_passes": int(self.ltm_max_passes),
                "followup_time_budget_ms": float(self.ltm_followup_time_budget_ms),
                "followup_max_query_tokens": int(self.ltm_followup_max_query_tokens),
            },
            "responder_guidance": {
                "require_citations": True,
                "abstain_without_evidence": True,
                "memory_preference": str(preview.get("memory_preference") or "auto"),
                "render_citations": False if render_citations is None else bool(render_citations),
            },
        }

    def _build_context_package_v2(
        self,
        message: str,
        *,
        high_risk: bool,
        memory_preference: str | None,
        session_id: str | None,
        retrieval_query: str | None,
        retrieval_override: RetrievalOverrideRequestContract | None,
        render_citations: bool | None,
        include_work_session_context: bool,
        include_work_session_diagnostics: bool,
        work_session_scope: dict[str, Any] | None,
        explicit_resume: bool,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        text = str(message or "").strip()
        memory_pref = self._normalize_memory_preference(memory_preference)

        normalized = text.lower()
        decision = self._route_turn(text=text, high_risk=high_risk, memory_preference=memory_pref)
        memory_signal_score = self._memory_signal_score(normalized)

        session = self._preview_session(session_id)
        stm_start = time.perf_counter()
        stm_pack, stm_ids, stm_hits, stm_best = self._retrieve_short_term(text, session=session)
        stm_ms = (time.perf_counter() - stm_start) * 1000.0

        override_resolution = self._resolve_retrieval_override(
            message=text,
            retrieval_query=retrieval_query,
            retrieval_override=retrieval_override,
            decision=decision,
        )
        retrieval_text = override_resolution.retrieval_text
        memory_route = str(override_resolution.decision.route or "none").strip()
        route_reason = str(override_resolution.decision.reason or "").strip()
        isolate_stm_from_ltm = self._should_isolate_stm_from_ltm_evidence(
            memory_route=memory_route,
            route_reason=route_reason,
            user_text=text,
        )
        retrieval_override_active = bool(override_resolution.audit.applied)

        predicted_mode, arbitration_reason, will_query_ltm = self._predict_memory_mode(
            route=memory_route,
            stm_hits=stm_hits,
            stm_best=stm_best,
        )
        preview = {
            "route": memory_route,
            "reason": route_reason,
            "reason_text": self._route_reason_text(route_reason),
            "memory_preference": memory_pref,
            "high_risk": bool(high_risk),
            "memory_signal": memory_signal_score >= self.memory_signal_min_score,
            "memory_signal_score": round(float(memory_signal_score), 4),
            "session_id": session.session_id,
            "stm_hit_count": int(stm_hits),
            "stm_best_score": round(float(stm_best), 4),
            "stm_primary_threshold": round(float(self.short_term_primary_score), 4),
            "predicted_memory_mode": predicted_mode,
            "will_query_ltm": bool(will_query_ltm),
            "arbitration_reason": arbitration_reason,
        }

        ltm_start = time.perf_counter()
        memory_mode = "none"
        retrieved_atom_ids: list[str] = []
        retrieval = None
        pack = MemoryPack()
        retrieval_passes = 0
        retrieval_stop_reason = "route_skip"
        episode_hits: list[EpisodeHit] = []

        if memory_route == "none":
            pass
        elif memory_route == "stm_only":
            if stm_hits > 0:
                memory_mode = "stm_primary"
                pack = stm_pack
                retrieved_atom_ids = list(stm_ids)
        elif memory_route in {"ltm_light", "ltm_deep"}:
            if (
                memory_route == "ltm_light"
                and stm_hits > 0
                and stm_best >= self.short_term_primary_score
                and not isolate_stm_from_ltm
            ):
                memory_mode = "stm_primary"
                pack = stm_pack
                retrieved_atom_ids = list(stm_ids)
            else:
                episode_hits = self._episode_hits(user_text=text, retrieval_text=retrieval_text)
                if (
                    episode_hits
                    and not high_risk
                    and not retrieval_override_active
                    and self._can_short_circuit_episode_primary(
                        episode_hits,
                        user_text=text,
                        retrieval_text=retrieval_text,
                    )
                ):
                    memory_mode = "ltm_only"
                    pack = self._episode_hits_to_pack(episode_hits)
                    retrieved_atom_ids = self._episode_retrieved_ids(episode_hits)
                    retrieval_stop_reason = "episode_short_circuit"
                else:
                    retrieval_outcome = self._retrieve_ltm(
                        retrieval_text,
                        retrieval_override_active=retrieval_override_active,
                        profile_override=self._retrieval_profile_override(memory_pref, route_reason=route_reason),
                    )
                    retrieval = retrieval_outcome.retrieval
                    retrieval_passes = retrieval_outcome.passes_used
                    retrieval_stop_reason = retrieval_outcome.stop_reason
                    ltm_pack = retrieval.memory_pack
                    ltm_ids = list(retrieval.ranked_atom_ids)
                    if episode_hits:
                        ltm_pack = self._augment_pack_with_episode_context(
                            ltm_pack,
                            episode_hits,
                            recall_priority=self._is_recall_style_prompt(text),
                        )
                        ltm_ids = self._pack_retrieved_ids(ltm_pack)
                    if stm_hits > 0 and not isolate_stm_from_ltm:
                        memory_mode = "hybrid"
                        pack = self._merge_packs(stm_pack, ltm_pack)
                        stm_id_set = set(stm_ids)
                        retrieved_atom_ids = list(stm_ids) + [atom_id for atom_id in ltm_ids if atom_id not in stm_id_set]
                    else:
                        memory_mode = "ltm_only"
                        pack = ltm_pack
                        retrieved_atom_ids = ltm_ids
        else:
            retrieval_outcome = self._retrieve_ltm(
                retrieval_text,
                retrieval_override_active=retrieval_override_active,
                profile_override=self._retrieval_profile_override(memory_pref, route_reason=route_reason),
            )
            retrieval = retrieval_outcome.retrieval
            retrieval_passes = retrieval_outcome.passes_used
            retrieval_stop_reason = retrieval_outcome.stop_reason
            ltm_pack = retrieval.memory_pack
            ltm_ids = list(retrieval.ranked_atom_ids)
            if stm_hits > 0 and not isolate_stm_from_ltm:
                memory_mode = "hybrid"
                pack = self._merge_packs(stm_pack, ltm_pack)
                stm_id_set = set(stm_ids)
                retrieved_atom_ids = list(stm_ids) + [atom_id for atom_id in ltm_ids if atom_id not in stm_id_set]
            else:
                memory_mode = "ltm_only"
                pack = ltm_pack
                retrieved_atom_ids = ltm_ids

        if memory_route in {"ltm_light", "ltm_deep"} and self._provisional_retrieval_enabled:
            provisional_pack, provisional_ids, provisional_hits, _provisional_best = self._retrieve_provisional_memory(
                retrieval_text
            )
            if provisional_hits:
                pack = self._merge_long_term_with_provisional(pack, provisional_pack)
                seen_ids = set(retrieved_atom_ids)
                retrieved_atom_ids.extend(item for item in provisional_ids if item not in seen_ids)
                if memory_mode == "none":
                    memory_mode = "ltm_only"

        # Keep retrieved_atom_ids aligned with the evidence pack (not broad rerank candidate lists).
        if pack.core or pack.context or pack.continuity or pack.conflict:
            pack = self._prune_consumer_meta_evidence(
                pack,
                route_reason=route_reason,
                user_text=text,
            )
            retrieved_atom_ids = self._pack_retrieved_ids(pack)

        if memory_mode == "stm_primary":
            retrieval_stop_reason = "stm_primary_satisfied"
        elif memory_mode == "none":
            retrieval_stop_reason = "route_skip"

        ltm_ms = (time.perf_counter() - ltm_start) * 1000.0

        verify_start = time.perf_counter()
        claims = self._candidate_claims(pack)
        if memory_route == "none":
            verification = VerificationResult(
                decision=VerificationDecision.NO_MEMORY,
                checks=[],
                unsupported_claims=[],
                needs_uncertainty=False,
            )
        elif claims:
            verification = self.verifier.verify(claims, pack, high_risk=high_risk)
        else:
            unsupported = "STM_EMPTY_ROUTE" if memory_route == "stm_only" else "NO_EVIDENCE_CLAIMS"
            verification = VerificationResult(
                decision=VerificationDecision.ABSTAIN,
                checks=[],
                unsupported_claims=[unsupported],
                needs_uncertainty=False,
            )
        gate_text = retrieval_text
        if retrieval is not None:
            verification = self._apply_query_evidence_gate(
                verification,
                retrieval,
                gate_text,
                support_pack=pack,
            )
        elif memory_route != "none":
            verification = self._apply_pack_query_gate(
                verification,
                pack,
                gate_text,
                high_risk=high_risk,
            )
        verification = self._enforce_direct_citation_gate(
            verification,
            pack,
            memory_route=memory_route,
        )
        verifier_ms = (time.perf_counter() - verify_start) * 1000.0

        citations = self._rank_citations(verification=verification, pack=pack)
        stm_cards_full = [self._card_to_dict(item) for item in self._assemble_memory_cards(stm_pack)[:3]]
        stm_cards = [self._compact_card_dict(item) for item in stm_cards_full]

        ltm_evidence = self._pack_to_evidence_v2(pack)
        evidence_sections_present = self._evidence_sections_present(ltm_evidence)
        evidence_time_window = self._evidence_time_window(pack)
        episode_evidence_present = bool(evidence_sections_present.get("episode"))
        retrieval_diagnostics = self._build_retrieval_diagnostics(pack=pack, retrieval=retrieval)

        with self._lock:
            short_term_notes = list(session.short_term)
            rolling_summary = str(session.rolling_summary or "").strip()
        top_notes = [str(item.text or "").strip() for item in short_term_notes[-6:] if str(item.text or "").strip()]
        if len(top_notes) > 3:
            top_notes = top_notes[-3:]

        build_ms = (time.perf_counter() - started) * 1000.0
        requested_retrieval_query = str(
            (retrieval_override.query if retrieval_override is not None else retrieval_query) or ""
        ).strip()
        package = {
            "package_version": "v2",
            "message": text,
            "retrieval_query": requested_retrieval_query,
            "retrieval_override": contract_to_dict(override_resolution.audit),
            "preview": preview,
            "working_set": {
                "session_id": session.session_id,
                "short_term_notes": len(short_term_notes),
                "short_term_hits": int(stm_hits),
                "rolling_summary": rolling_summary,
                "top_notes": top_notes,
                "memory_cards": stm_cards,
                "memory_cards_full_count": len(stm_cards_full),
            },
            "ltm_query_plan": {
                "will_query_ltm": bool(will_query_ltm),
                "predicted_memory_mode": predicted_mode,
                "max_passes": int(self.ltm_max_passes),
                "followup_time_budget_ms": float(self.ltm_followup_time_budget_ms),
                "followup_max_query_tokens": int(self.ltm_followup_max_query_tokens),
            },
            "timing_ms": {
                "build_ms": round(float(build_ms), 3),
                "stm_ms": round(float(stm_ms), 3),
                "ltm_ms": round(float(ltm_ms), 3),
                "verifier_ms": round(float(verifier_ms), 3),
            },
            "retrieval_stats": {
                "memory_route": memory_route,
                "route_reason": route_reason,
                "memory_mode": memory_mode,
                "retrieved_atom_ids": list(retrieved_atom_ids),
                "retrieval_passes": int(retrieval_passes),
                "retrieval_stop_reason": str(retrieval_stop_reason or ""),
                "retrieval_override": contract_to_dict(override_resolution.audit),
                "retrieval_diagnostics": retrieval_diagnostics,
                "episode_hit_count": len(episode_hits),
                "episode_evidence_present": episode_evidence_present,
                "episode_evidence_in_context": any(
                    str(item).startswith("episode_card:") for item in list(retrieved_atom_ids or [])
                ),
            },
            "ltm_evidence": ltm_evidence,
            "evidence_sections_present": evidence_sections_present,
            "evidence_time_window": evidence_time_window,
            "service_verdict": {
                "decision": verification.decision.value,
                "citations": citations,
                "unsupported_claims": list(getattr(verification, "unsupported_claims", []) or []),
            },
            "responder_guidance": {
                "require_citations": True,
                "abstain_without_evidence": True,
                "memory_preference": memory_pref,
                "render_citations": False if render_citations is None else bool(render_citations),
                "citation_format": "source_id#message_id",
                "do_not_quote_verbatim_unless_asked": True,
                "ask_followup_when_evidence_weak": True,
            },
        }
        work_context = self._build_work_session_context(
            session=session,
            include_work_session_context=include_work_session_context,
            include_work_session_diagnostics=include_work_session_diagnostics,
            work_session_scope=work_session_scope,
            explicit_resume=explicit_resume,
            package=package,
        )
        if work_context:
            package["work_session_context"] = work_context
        return package

    def capture_work_session_entry(
        self,
        *,
        session_id: str | None = None,
        work_session_scope: dict[str, Any],
        kind: str,
        summary: str = "",
        raw_content: str = "",
        source_turn_id: str = "",
        source_tool_call_id: str = "",
        replaceability_score: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not bool(self.config.work_session_scratchpad.enabled):
            raise RuntimeError("work session scratchpad is disabled")
        store = self._scratchpad_store
        if store is None:
            detail = self._scratchpad_init_error or "scratchpad store unavailable"
            raise RuntimeError(detail)
        scope = self._resolve_work_session_scope(session_id=session_id, work_session_scope=work_session_scope)
        if not scope.scope_id:
            raise RuntimeError("work session scratchpad scope is disabled")
        entry = store.add_entry(
            scope,
            kind=kind,
            summary=summary,
            raw_content=raw_content,
            source_turn_id=source_turn_id,
            source_tool_call_id=source_tool_call_id,
            replaceability_score=replaceability_score,
            metadata=dict(metadata or {}),
        )
        return {
            "entry_id": entry.entry_id,
            "scope_id": entry.scope_id,
            "kind": entry.kind,
            "summary": entry.summary,
            "raw_ref": entry.raw_ref,
            "raw_ref_sha256": entry.raw_ref_sha256,
            "status": entry.status,
            "degraded": entry.degraded,
            "token_estimate": entry.token_estimate,
        }

    def _build_work_session_context(
        self,
        *,
        session: SessionState,
        include_work_session_context: bool,
        include_work_session_diagnostics: bool,
        work_session_scope: dict[str, Any] | None,
        explicit_resume: bool,
        package: dict[str, Any],
    ) -> dict[str, Any] | None:
        policy = self.config.work_session_scratchpad
        if not (bool(policy.enabled) and bool(policy.inject_enabled) and bool(include_work_session_context)):
            return None
        store = self._scratchpad_store
        if store is None:
            return None
        scope = self._resolve_work_session_scope(session_id=session.session_id, work_session_scope=work_session_scope)
        if not scope.can_inject:
            return None
        entries = store.list_entries_for_injection(scope)
        if not entries and (bool(policy.resume_injection_enabled) or bool(explicit_resume)):
            entries = store.list_entries_for_resume_injection(scope)
        selected = []
        selected_entries = []
        used_chars = 0
        max_chars = int(policy.max_injected_chars)
        for entry in entries[: int(policy.max_injected_items)]:
            summary = str(entry.summary or "").strip()
            if not summary:
                continue
            projected = used_chars + len(summary)
            if projected > max_chars and selected:
                break
            if projected > max_chars:
                summary = summary[:max_chars].rstrip()
                projected = len(summary)
            selected.append(
                {
                    "entry_id": entry.entry_id,
                    "kind": entry.kind,
                    "summary": summary,
                    "replaceability_score": round(float(entry.replaceability_score), 4),
                    "token_estimate": int(entry.token_estimate),
                    "raw_ref": entry.raw_ref,
                    "raw_ref_sha256": entry.raw_ref_sha256,
                }
            )
            selected_entries.append(entry)
            used_chars = projected
        if not selected:
            return None
        summaries = [str(item["summary"]) for item in selected if str(item.get("summary") or "").strip()]
        context = {
            "non_authoritative": True,
            "trust_tier": "scratchpad_ephemeral",
            "summary_mode": "deterministic",
            "scope": {
                "scope_id": scope.scope_id,
                "project_id": scope.project_id,
                "thread_id": scope.thread_id,
                "session_id": scope.session_id,
                "workstream_key": scope.workstream_key,
                "workstream_name": scope.workstream_name,
                "scope_mode": scope.scope_mode,
            },
            "summary": " ".join(summaries)[:max_chars],
            "items": selected,
            "budget": {
                "max_injected_items": int(policy.max_injected_items),
                "max_injected_chars": int(policy.max_injected_chars),
                "observed_injected_tokens": estimate_context_tokens(selected),
            },
        }
        context["metrics"] = {
            "observed_package_tokens": estimate_context_tokens(package),
            "observed_injected_tokens": estimate_context_tokens(context),
            "hypothetical_prompt_tokens_replaced": int(
                sum(
                    int(dict(getattr(entry, "metadata", {}) or {}).get("hypothetical_prompt_tokens_replaced") or 0)
                    for entry in selected_entries
                )
            ),
        }
        context["budget"]["observed_injected_tokens"] = context["metrics"]["observed_injected_tokens"]
        if bool(policy.diagnostics_enabled) and bool(include_work_session_diagnostics):
            try:
                all_entries = store.list_entries_for_diagnostics(scope)
                context["diagnostics"] = {
                    "scratchpad_available": bool(all_entries),
                    "scratchpad_injected": bool(selected),
                    "task_map": build_diagnostic_task_map(scope, all_entries),
                }
            except Exception as exc:
                context["diagnostics"] = {
                    "scratchpad_available": True,
                    "scratchpad_injected": bool(selected),
                    "task_map_error": str(exc),
                }
        return context

    def _resolve_work_session_scope(
        self,
        *,
        session_id: str | None,
        work_session_scope: dict[str, Any] | None,
    ) -> WorkSessionScope:
        metadata = dict(work_session_scope or {}) if isinstance(work_session_scope, dict) else {}
        session_key = self._normalize_session_id(str(session_id or "default"))
        thread_id = str(metadata.get("thread_id") or metadata.get("work_session_thread_id") or "").strip()
        workstream_key = str(metadata.get("workstream_key") or metadata.get("checkpoint_track") or "").strip()
        return resolve_scope(
            project_id=str(self.project_root),
            thread_id=thread_id,
            session_id=session_key,
            workstream_key=workstream_key,
            workstream_name=str(metadata.get("workstream_name") or workstream_key).strip(),
            runtime_store_fingerprint=self._runtime_store_fingerprint(),
        )

    def _runtime_store_fingerprint(self) -> str:
        store = getattr(self.retriever, "store", None)
        parts = [type(store).__name__]
        path_found = False
        for attr in ("db_path", "path", "store_path"):
            value = getattr(store, attr, None)
            if value:
                parts.append(str(value))
                path_found = True
                break
        if not path_found:
            cache_scope = getattr(store, "cache_scope", None)
            if callable(cache_scope):
                parts.append(str(cache_scope()))
            else:
                scope_id = getattr(store, "_cache_scope_id", None)
                if scope_id:
                    parts.append(str(scope_id))
        token = "|".join(parts)
        return "store:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

    def _pack_to_evidence_v2(self, pack: MemoryPack) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def _push(section: str, items: list[MemoryPackItem]) -> None:
            for item in list(items or []):
                atom_id = str(getattr(item, "atom_id", "") or "").strip()
                if not atom_id:
                    continue
                citations = self._citations_for_item(item)
                role_hint, anchors = self._evidence_role_and_anchors(atom_id)
                summary, verbatim = self._evidence_summaries(
                    item.canonical_text,
                    role_hint=role_hint,
                    raw_context=str(getattr(item, "raw_context_text", "") or ""),
                )
                contradiction = bool(section == "conflict" or str(item.conflict_state).lower() != "active")
                out.append(
                    {
                        "evidence_id": atom_id,
                        "section": section,
                        "kind": self._card_kind(atom_id),
                        "role_hint": role_hint,
                        "summary": summary,
                        "verbatim": verbatim,
                        "citations": citations,
                        "anchors": anchors,
                        "confidence": _clamp01(item.confidence),
                        "contradiction": contradiction,
                        "memory_layer": str(getattr(item, "memory_layer", "atom") or "atom"),
                        "trust_tier": str(getattr(item, "trust_tier", "evidence") or "evidence"),
                        "authority_tier": self._memory_item_authority_tier(item),
                        "maturity": str(getattr(item, "maturity", "evidence") or "evidence"),
                        "lifecycle": str(getattr(item, "lifecycle", "active") or "active"),
                        "conflict_state": str(getattr(item, "conflict_state", "active") or "active"),
                        "conflict_with_ids": list(getattr(item, "conflict_with_ids", []) or []),
                        "human_reviewed": bool(
                            getattr(item, "human_reviewed", False)
                            or str(getattr(item, "trust_tier", "")).lower() in {"published", "human_reviewed_canonical"}
                        ),
                        "lineage_ids": list(getattr(item, "lineage_ids", []) or []),
                    }
                )

        _push("core", list(pack.core))
        _push("context", list(pack.context))
        _push("continuity", list(pack.continuity))
        _push("conflict", list(pack.conflict))
        return out[:16]

    @staticmethod
    def _memory_item_authority_tier(item: MemoryPackItem) -> str:
        explicit = str(getattr(item, "authority_tier", "") or "").strip().lower()
        trust = str(getattr(item, "trust_tier", "") or "").strip().lower()
        if trust in {"published", "human_reviewed_canonical"}:
            return "human_reviewed_canonical"
        if trust in {"provisional_consolidated", "provisional_observed"}:
            return trust
        if trust == "provisional":
            return explicit if explicit.startswith("provisional_") else "provisional_observed"
        return explicit or "evidence_atom"

    @staticmethod
    def _evidence_sections_present(ltm_evidence: list[dict[str, Any]]) -> dict[str, bool]:
        sections = {"core": False, "context": False, "continuity": False, "conflict": False, "episode": False}
        for item in list(ltm_evidence or []):
            section = str((item or {}).get("section") or "").strip().lower()
            evidence_id = str((item or {}).get("evidence_id") or "").strip().lower()
            if section in sections:
                sections[section] = True
            if evidence_id.startswith("episode_card:"):
                sections["episode"] = True
        return sections

    @staticmethod
    def _evidence_time_window(pack: MemoryPack) -> dict[str, str]:
        timestamps: list[datetime] = []
        for item in list(pack.core) + list(pack.context) + list(pack.continuity) + list(pack.conflict):
            for ref in list(getattr(item, "source_refs", []) or []):
                raw = getattr(ref, "timestamp", None)
                if raw is None:
                    continue
                if isinstance(raw, datetime):
                    parsed = raw
                else:
                    try:
                        parsed = datetime.fromisoformat(str(raw))
                    except Exception:
                        continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                else:
                    parsed = parsed.astimezone(timezone.utc)
                timestamps.append(parsed)
        if not timestamps:
            return {"start_at": "", "end_at": "", "display": "unknown"}
        start_at = min(timestamps).astimezone(timezone.utc)
        end_at = max(timestamps).astimezone(timezone.utc)
        if start_at == end_at:
            display = start_at.strftime("%Y-%m-%d %H:%M UTC")
        else:
            display = f"{start_at.strftime('%Y-%m-%d %H:%M UTC')} -> {end_at.strftime('%Y-%m-%d %H:%M UTC')}"
        return {"start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "display": display}

    def _evidence_role_and_anchors(self, atom_id: str) -> tuple[str, list[str]]:
        cleaned = str(atom_id or "").strip()
        if cleaned.startswith("episode_card:"):
            return "unknown", []
        try:
            atom = self.retriever.store.get_atom(cleaned)
        except Exception:
            return "unknown", []
        entities = [str(item).strip().lower() for item in list(getattr(atom, "entities", []) or []) if str(item).strip()]
        topics = [str(item).strip().lower() for item in list(getattr(atom, "topics", []) or []) if str(item).strip()]
        role_hint = "assistant" if "assistant" in entities else ("user" if "user" in entities else "unknown")
        anchors: list[str] = []
        seen: set[str] = set()
        for value in entities + topics:
            if value in {"assistant", "user", "dyad"}:
                continue
            if value in seen:
                continue
            seen.add(value)
            anchors.append(value)
            if len(anchors) >= 8:
                break
        return role_hint, anchors

    @staticmethod
    def _evidence_best_clause(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        clauses = [piece.strip() for piece in re.split(r"[.\n!?;:]+", raw) if piece.strip()]
        if not clauses:
            return raw
        ranked = sorted(clauses, key=lambda piece: (len(_tokenize(piece)), len(piece)), reverse=True)
        return ranked[0]

    def _evidence_summaries(self, text: str, *, role_hint: str, raw_context: str = "") -> tuple[str, str]:
        clause = self._evidence_best_clause(text)
        clause_compact = self._compact_text(clause, max_chars=180)
        verbatim_source = str(raw_context or text or "")
        verbatim = self._compact_text(verbatim_source, max_chars=320)
        if role_hint == "user":
            return f"User: {clause_compact}", verbatim
        if role_hint == "assistant":
            return f"Assistant: {clause_compact}", verbatim
        return f"Memory: {clause_compact}", verbatim

    def stats(self) -> RuntimeStats:
        with self._lock:
            return RuntimeStats(
                turns=self._stats.turns,
                total_input_tokens=self._stats.total_input_tokens,
                total_output_tokens=self._stats.total_output_tokens,
                total_cost_usd=self._stats.total_cost_usd,
                p95_latency_ms=self._stats.p95_latency_ms,
                stm_primary_turns=self._stats.stm_primary_turns,
                hybrid_turns=self._stats.hybrid_turns,
                ltm_only_turns=self._stats.ltm_only_turns,
                route_none_turns=self._stats.route_none_turns,
                route_stm_only_turns=self._stats.route_stm_only_turns,
                route_ltm_light_turns=self._stats.route_ltm_light_turns,
                route_ltm_deep_turns=self._stats.route_ltm_deep_turns,
                recognition_events=self._stats.recognition_events,
                recognition_rate=self._stats.recognition_rate,
            )

    @staticmethod
    def _is_recall_style_prompt(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        if any(phrase in normalized for phrase in _ROUTINE_SKIP_PHRASES):
            return False
        if any(phrase in normalized for phrase in _LTM_DEEP_PHRASES):
            return True
        return any(
            marker in normalized
            for marker in (
                "do you remember",
                "remember when",
                "what happened",
                "what happened before",
                "what happened after",
                "walk me through",
                "right before",
                "right after",
                "when we were talking",
                "what came up about",
            )
        )

    def _should_isolate_stm_from_ltm_evidence(
        self,
        *,
        memory_route: str,
        route_reason: str,
        user_text: str,
    ) -> bool:
        if memory_route not in {"ltm_light", "ltm_deep"}:
            return False
        if str(route_reason or "").strip() == "explicit_memory_request":
            return True
        if self._has_specific_recall_anchor(text=user_text):
            return True
        return self._is_recall_style_prompt(user_text)

    def _should_prune_consumer_meta_evidence(self, *, route_reason: str, user_text: str) -> bool:
        reason = str(route_reason or "").strip().lower()
        if reason in {"identity_relationship_probe", "name_frequency_trigger"}:
            return True
        normalized = str(user_text or "").strip().lower()
        return self._is_identity_relationship_query(normalized)

    def _looks_like_consumer_meta_instruction_text(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        tokens = set(_tokenize(normalized))
        system_hits = len(tokens.intersection(_CONSUMER_META_SYSTEM_TOKENS))
        instruction_hits = len(tokens.intersection(_CONSUMER_META_INSTRUCTION_TOKENS))
        phrase_hit = any(phrase in normalized for phrase in _CONSUMER_META_PHRASES)
        if not phrase_hit and not (system_hits >= 2 and instruction_hits >= 1):
            return False
        if "memory system" in normalized and instruction_hits == 0:
            return False
        return True

    def _looks_like_consumer_meta_conversation_text(self, text: str, *, user_text: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        tokens = set(_tokenize(normalized))
        meta_hits = len(tokens.intersection(_CONSUMER_META_CONVERSATION_TOKENS))
        phrase_hit = any(phrase in normalized for phrase in _CONSUMER_META_CONVERSATION_PHRASES)
        if not phrase_hit and meta_hits < 2:
            return False
        query_normalized = str(user_text or "").strip().lower()
        focus_tokens = set(self._query_focus_candidates(text=user_text, normalized=query_normalized))
        focus_hit = bool(focus_tokens.intersection(tokens))
        quoted_focus = any(
            bool(focus_tokens.intersection(set(_tokenize(quoted))))
            for quoted in _QUOTE_RE.findall(str(text or ""))
        )
        if not focus_hit and not quoted_focus:
            return False
        if phrase_hit or quoted_focus:
            return True
        return meta_hits >= 3 and ("would be" in normalized or "for example" in normalized)

    def _prune_consumer_meta_evidence(
        self,
        pack: MemoryPack,
        *,
        route_reason: str,
        user_text: str,
    ) -> MemoryPack:
        if not self._should_prune_consumer_meta_evidence(route_reason=route_reason, user_text=user_text):
            return pack

        removed_any = False
        kept_any_non_meta = False

        def _filtered(items: list[MemoryPackItem]) -> list[MemoryPackItem]:
            nonlocal removed_any, kept_any_non_meta
            out: list[MemoryPackItem] = []
            for item in items:
                atom_id = str(getattr(item, "atom_id", "") or "").strip()
                if atom_id.startswith("episode_card:"):
                    out.append(item)
                    kept_any_non_meta = True
                    continue
                text = str(getattr(item, "canonical_text", "") or "").strip()
                if self._looks_like_consumer_meta_instruction_text(text) or self._looks_like_consumer_meta_conversation_text(
                    text,
                    user_text=user_text,
                ):
                    removed_any = True
                    continue
                out.append(item)
                kept_any_non_meta = True
            return out

        filtered_core = _filtered(list(pack.core))
        filtered_context = _filtered(list(pack.context))
        filtered_continuity = _filtered(list(pack.continuity))
        filtered_conflict = _filtered(list(pack.conflict))
        if not removed_any or not kept_any_non_meta:
            return pack

        confidence_values = [
            float(getattr(item, "confidence", 0.0) or 0.0)
            for item in filtered_core + filtered_context + filtered_continuity + filtered_conflict
        ]
        pack_confidence = (
            _clamp01(sum(confidence_values) / max(1, len(confidence_values)))
            if confidence_values
            else float(getattr(pack, "pack_confidence", 0.0) or 0.0)
        )
        return memory_pack_from_items(
            filtered_core,
            context=filtered_context,
            continuity=filtered_continuity,
            conflict=filtered_conflict,
            pack_confidence=pack_confidence,
        )

    def _route_turn(self, *, text: str, high_risk: bool, memory_preference: str = "auto") -> FrontDeskDecision:
        normalized = str(text or "").strip().lower()
        token_count = len(_tokenize(normalized))
        preference = self._normalize_memory_preference(memory_preference)
        memory_signal_score = self._memory_signal_score(normalized)
        has_memory_signal = memory_signal_score >= self.memory_signal_min_score
        explicit_memory_request = self._has_explicit_memory_request(normalized)
        if high_risk:
            return FrontDeskDecision(route="ltm_deep", reason="high_risk_escalation")

        route: str
        reason: str
        if any(phrase in normalized for phrase in _STM_ONLY_PHRASES):
            route, reason = "stm_only", "thread_local_reference"
        elif any(phrase in normalized for phrase in _ROUTINE_SKIP_PHRASES):
            route, reason = "none", "smalltalk_routine"
        elif explicit_memory_request:
            route, reason = "ltm_deep", "explicit_memory_request"
        elif self._has_verbatim_session_recall_intent(text=text, normalized=normalized):
            route, reason = "ltm_deep", "verbatim_session_recall"
        else:
            forced_reason = self._force_ltm_light_reason(text=text, normalized=normalized)
            if forced_reason:
                route, reason = "ltm_light", forced_reason
            elif self._is_small_talk(normalized, token_count=token_count):
                route, reason = "none", "smalltalk_routine"
            elif self._casual_prompt_should_skip(normalized, token_count=token_count):
                route, reason = "none", "casual_prompt_no_recall"
            elif has_memory_signal:
                route, reason = "ltm_light", "memory_signal_probe"
            elif token_count <= 20:
                route, reason = "none", "ambiguous_low_signal_skip"
            else:
                route, reason = "ltm_light", "default_memory_probe"

        decision = FrontDeskDecision(route=route, reason=reason)
        force_memory_lookup = decision.reason in {"identity_relationship_probe", "name_frequency_trigger"}
        if preference == "chat_first":
            if force_memory_lookup:
                decision = FrontDeskDecision(route=route, reason=reason)
            elif route == "ltm_light":
                decision = FrontDeskDecision(route="none", reason="memory_preference_chat_first")
            elif route == "ltm_deep" and reason != "explicit_memory_request":
                decision = FrontDeskDecision(route="ltm_light", reason="memory_preference_chat_first")
            else:
                decision = FrontDeskDecision(route=route, reason=reason)

        if preference == "memory_assist":
            if route == "none" and reason == "casual_prompt_no_recall":
                decision = FrontDeskDecision(route="ltm_light", reason="memory_preference_memory_assist")
            elif route == "ltm_light" and reason == "default_memory_probe":
                decision = FrontDeskDecision(route="ltm_deep", reason="memory_preference_memory_assist")
            else:
                decision = FrontDeskDecision(route=route, reason=reason)

        if preference == "session_recall":
            decision = FrontDeskDecision(route="ltm_deep", reason="memory_preference_session_recall")

        if self._should_force_routine_no_memory(
            text=text,
            normalized=normalized,
            token_count=token_count,
            explicit_memory_request=explicit_memory_request,
            force_memory_lookup=force_memory_lookup,
            memory_preference=preference,
            decision=decision,
        ):
            return FrontDeskDecision(route="none", reason="routine_hard_cap")

        return decision

    def _has_explicit_memory_request(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in _ROUTINE_SKIP_PHRASES):
            return False
        return any(phrase in normalized for phrase in _LTM_DEEP_PHRASES)

    def _resolve_retrieval_override(
        self,
        *,
        message: str,
        retrieval_query: str | None,
        retrieval_override: RetrievalOverrideRequestContract | None,
        decision: FrontDeskDecision,
    ) -> ResolvedRetrievalOverride:
        message_text = str(message or "").strip()
        raw_query = str(retrieval_query or "").strip() or None
        contract_query = str(retrieval_override.query or "").strip() if retrieval_override is not None else None
        if raw_query and contract_query and raw_query != contract_query:
            raise ValueError("retrieval override query mismatch")
        requested_query = contract_query or raw_query
        audit = RetrievalOverrideAuditContract(
            requested=bool(requested_query),
            invoker=str(retrieval_override.invoker or "").strip() if retrieval_override is not None else "",
            reason=str(retrieval_override.reason or "").strip() if retrieval_override is not None else "",
            scope=str(retrieval_override.scope or "").strip() if retrieval_override is not None else "",
            auth_context=str(retrieval_override.auth_context or "").strip() if retrieval_override is not None else "",
            requested_query_tokens=_token_estimate(requested_query or ""),
        )
        if not requested_query:
            return ResolvedRetrievalOverride(retrieval_text=message_text, decision=decision, audit=audit)
        if retrieval_override is None:
            audit.denied_reason = "missing_override_context"
            return ResolvedRetrievalOverride(retrieval_text=message_text, decision=decision, audit=audit)
        if not str(audit.auth_context or "").strip():
            audit.denied_reason = "missing_auth_context"
            return ResolvedRetrievalOverride(retrieval_text=message_text, decision=decision, audit=audit)

        audit.allowed = True
        normalized = message_text.lower()
        normalized_requested = " ".join(str(requested_query).split()).lower()
        normalized_message = " ".join(message_text.split()).lower()
        if normalized_requested == normalized_message:
            audit.denied_reason = "query_matches_user_text"
            return ResolvedRetrievalOverride(retrieval_text=message_text, decision=decision, audit=audit)
        if (
            str(decision.route or "").strip() == "none"
            and str(decision.reason or "").strip() in {"smalltalk_routine", "routine_hard_cap"}
            and not self._has_explicit_memory_request(normalized)
        ):
            audit.denied_reason = "routine_guard_requires_explicit_memory_request"
            return ResolvedRetrievalOverride(retrieval_text=message_text, decision=decision, audit=audit)

        resolved_decision = decision
        if str(resolved_decision.route or "").strip() == "none":
            resolved_decision = FrontDeskDecision(route="ltm_light", reason="retrieval_query_override")
        audit.applied = True
        return ResolvedRetrievalOverride(retrieval_text=requested_query, decision=resolved_decision, audit=audit)

    def _preview_session(self, session_id: str | None) -> SessionState:
        if session_id is None:
            return self._ensure_session("default")
        session = self._get_session(session_id)
        if session is None:
            raise KeyError(self._normalize_session_id(session_id))
        return session

    def _predict_memory_mode(self, *, route: str, stm_hits: int, stm_best: float) -> tuple[str, str, bool]:
        normalized_route = str(route or "none").strip()
        hits = int(stm_hits)
        best = float(stm_best)
        if normalized_route == "none":
            return "none", "route_skip", False
        if normalized_route == "stm_only":
            if hits > 0:
                return "stm_primary", "stm_route_hit", False
            return "none", "stm_route_miss", False
        if normalized_route == "ltm_light":
            if hits > 0 and best >= self.short_term_primary_score:
                return "stm_primary", "stm_satisfies_light_route", False
            if hits > 0:
                return "hybrid", "stm_partial_requires_ltm", True
            return "ltm_only", "no_stm_hit_requires_ltm", True
        if normalized_route == "ltm_deep":
            if hits > 0:
                return "hybrid", "deep_route_with_stm_context", True
            return "ltm_only", "deep_route_requires_ltm", True
        if hits > 0:
            return "hybrid", "fallback_with_stm", True
        return "ltm_only", "fallback_ltm_only", True

    def _normalize_memory_preference(self, memory_preference: str | None) -> str:
        raw = str(memory_preference or "").strip().lower().replace("-", "_")
        if not raw:
            return "auto"
        aliases = {
            "balanced": "auto",
            "chat": "chat_first",
            "chatfirst": "chat_first",
            "conversation_first": "chat_first",
            "assist": "memory_assist",
            "memory": "memory_assist",
            "memoryassist": "memory_assist",
            "quote": "session_recall",
            "quotes": "session_recall",
            "verbatim": "session_recall",
            "session": "session_recall",
            "benchmark": "session_recall",
            "benchmark_recall": "session_recall",
        }
        normalized = aliases.get(raw, raw)
        if normalized not in {"auto", "chat_first", "memory_assist", "session_recall"}:
            return "auto"
        return normalized

    def _is_small_talk(self, normalized: str, *, token_count: int) -> bool:
        if not normalized:
            return True
        if _SMALLTALK_PREFIX_RE.search(normalized) and token_count <= 16:
            return True
        if any(phrase in normalized for phrase in _SMALLTALK_PHRASES) and token_count <= 24:
            return True
        return False

    def _is_casual_prompt(self, normalized: str, *, token_count: int) -> bool:
        if token_count <= 6:
            return True
        if _CASUAL_PREFIX_RE.search(normalized) and token_count <= 24:
            return True
        if token_count <= 20 and "?" in normalized:
            return True
        return False

    def _should_force_routine_no_memory(
        self,
        *,
        text: str,
        normalized: str,
        token_count: int,
        explicit_memory_request: bool,
        force_memory_lookup: bool,
        memory_preference: str,
        decision: FrontDeskDecision,
    ) -> bool:
        if not self.routine_hard_cap_enabled:
            return False
        if explicit_memory_request:
            return False
        if str(decision.reason or "").strip() == "verbatim_session_recall":
            return False
        if force_memory_lookup:
            return False
        if (
            str(memory_preference or "").strip() == "memory_assist"
            and self._has_specific_recall_anchor(text=text, normalized=normalized)
        ):
            return False
        if str(memory_preference or "").strip() == "session_recall":
            return False
        route = str(decision.route or "").strip()
        if route not in {"ltm_light", "ltm_deep"}:
            return False
        if (
            token_count <= 6
            and "?" not in normalized
            and not _CASUAL_PREFIX_RE.search(normalized)
            and not _SMALLTALK_PREFIX_RE.search(normalized)
        ):
            return False
        if self._is_small_talk(normalized, token_count=token_count):
            return True
        if self._is_casual_prompt(normalized, token_count=token_count):
            return True
        return False

    def _has_specific_recall_anchor(self, *, text: str, normalized: str | None = None) -> bool:
        raw_text = str(text or "").strip()
        if not raw_text:
            return False
        if _QUOTE_RE.search(raw_text):
            return True
        normalized_text = str(normalized if normalized is not None else raw_text.lower())
        informative = self._ordered_informative_tokens(normalized_text)
        if any(self._is_high_signal_token(tok) for tok in informative[:10]):
            return True
        if len(informative) >= 2 and any(tok in _DESCRIPTIVE_RECALL_ANCHOR_TOKENS for tok in informative[:10]):
            return True
        if self._name_frequency_trigger_token(text=raw_text, normalized=normalized_text):
            return True
        for focus in list(_ABOUT_FOCUS_RE.findall(raw_text)) + list(_WHO_FOCUS_RE.findall(raw_text)):
            if self._has_title_case_anchor_token(focus):
                return True
        return False

    def _has_title_case_anchor_token(self, text: str) -> bool:
        ignored = {
            "a",
            "an",
            "and",
            "can",
            "could",
            "how",
            "i",
            "me",
            "moment",
            "story",
            "tell",
            "that",
            "the",
            "these",
            "this",
            "those",
            "we",
            "what",
            "when",
            "where",
            "who",
            "why",
            "you",
            "your",
        }
        for raw in _NAME_TOKEN_RE.findall(str(text or "")):
            token = str(raw or "").strip()
            if not token or not token[0].isupper():
                continue
            lowered = token.lower()
            if lowered in _NAME_FREQ_IGNORE_TOKENS or lowered in ignored:
                continue
            return True
        return False

    def _has_explicit_memory_cues(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in _MEMORY_SIGNAL_PHRASES):
            return True
        ordered = self._ordered_informative_tokens(normalized)
        return any(self._is_high_signal_token(tok) for tok in ordered[:10])

    def _has_verbatim_session_recall_intent(self, *, text: str, normalized: str) -> bool:
        raw_text = str(text or "").strip()
        if not raw_text:
            return False
        if any(phrase in normalized for phrase in _SESSION_RECALL_PHRASES):
            return True
        tokens = set(_tokenize(normalized))
        if "said" in tokens and tokens.intersection({"assistant", "user", "exactly", "verbatim"}):
            return True
        return False

    def _casual_prompt_should_skip(self, normalized: str, *, token_count: int) -> bool:
        if not self._is_casual_prompt(normalized, token_count=token_count):
            return False
        # Preserve terse keyword-style prompts for memory routing; they are often
        # continuity lookups rather than social chatter.
        if (
            token_count <= 6
            and "?" not in normalized
            and not _CASUAL_PREFIX_RE.search(normalized)
            and not _SMALLTALK_PREFIX_RE.search(normalized)
        ):
            return False
        if any(phrase in normalized for phrase in _LTM_DEEP_PHRASES):
            return False
        if any(phrase in normalized for phrase in _STM_ONLY_PHRASES):
            return False
        return not self._has_explicit_memory_cues(normalized)

    def _has_memory_signal(self, normalized: str) -> bool:
        return self._memory_signal_score(normalized) >= self.memory_signal_min_score

    def _memory_signal_score(self, normalized: str) -> float:
        if not normalized:
            return 0.0
        token_count = len(_tokenize(normalized))
        score = 0.0
        phrase_hits = sum(1 for phrase in _MEMORY_SIGNAL_PHRASES if phrase in normalized)
        if phrase_hits:
            score += min(0.75, 0.42 + 0.18 * phrase_hits)
        ordered = self._ordered_informative_tokens(normalized)
        long_tokens = [tok for tok in ordered if len(tok) >= 6]
        high_signal_hits = sum(1 for tok in ordered[:10] if self._is_high_signal_token(tok))
        if len(ordered) >= 2 and len(long_tokens) >= 1:
            score += 0.34
        score += min(0.24, 0.08 * len(long_tokens))
        score += min(0.36, 0.18 * high_signal_hits)
        if self._is_small_talk(normalized, token_count=token_count):
            score -= 0.35
        elif self._is_casual_prompt(normalized, token_count=token_count):
            score -= 0.12
        return _clamp01(score)

    def _force_ltm_light_reason(self, *, text: str, normalized: str) -> str | None:
        if self._is_identity_relationship_query(normalized):
            return "identity_relationship_probe"
        if _NAMED_ENTITY_QUESTION_RE.search(str(text or "").strip()):
            return "identity_relationship_probe"
        matched = self._name_frequency_trigger_token(text=text, normalized=normalized)
        if matched:
            return "name_frequency_trigger"
        return None

    def _is_identity_relationship_query(self, normalized: str) -> bool:
        if not normalized:
            return False
        if "what happened on" in normalized and _DATE_LIKE_RE.search(normalized):
            return True
        if any(phrase in normalized for phrase in _FORCE_LTM_LIGHT_PHRASES):
            return True
        if "who is " in normalized or "who's " in normalized:
            return True
        if normalized.startswith("what is ") or normalized.startswith("what's "):
            if any(token in normalized for token in (" my ", " history ", " relationship ", " matters ", " care ")):
                return True
        if normalized.startswith("how does ") and " feel about " in normalized:
            return True
        if normalized.startswith("do i know ") and (" about " in normalized or "anything" in normalized):
            return True
        return False

    def _name_frequency_trigger_token(self, *, text: str, normalized: str) -> str | None:
        if not self._name_frequency_counts:
            return None
        candidates = self._query_name_candidates(text=text, normalized=normalized)
        for token in candidates:
            if int(self._name_frequency_counts.get(token, 0)) >= self.name_frequency_min_mentions:
                return token
        return None

    def _query_name_candidates(self, *, text: str, normalized: str) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in list(_NAME_TOKEN_RE.findall(str(text or ""))) + list(_NAME_TOKEN_RE.findall(normalized)):
            token = str(raw or "").strip().lower()
            if not self._is_name_frequency_candidate(token):
                continue
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
        for focus in list(_ABOUT_FOCUS_RE.findall(text)) + list(_WHO_FOCUS_RE.findall(text)):
            for raw in _NAME_TOKEN_RE.findall(str(focus or "")):
                token = str(raw or "").strip().lower()
                if not self._is_name_frequency_candidate(token):
                    continue
                if token in seen:
                    continue
                seen.add(token)
                out.append(token)
        return out

    def _query_focus_candidates(self, *, text: str, normalized: str) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        focus_spans = (
            list(_ABOUT_FOCUS_RE.findall(text))
            + list(_WHO_FOCUS_RE.findall(text))
            + list(_EVENT_FOCUS_RE.findall(text))
        )
        for focus in focus_spans:
            for raw in _NAME_TOKEN_RE.findall(str(focus or "")):
                token = str(raw or "").strip().lower()
                if len(token) < 3 or token in _FOCUS_CANDIDATE_IGNORE_TOKENS or token.isdigit():
                    continue
                if token in seen:
                    continue
                seen.add(token)
                out.append(token)
        if out:
            return out
        for token in self._query_name_candidates(text=text, normalized=normalized):
            if token in _FOCUS_CANDIDATE_IGNORE_TOKENS:
                continue
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
        return out

    def _is_name_frequency_candidate(self, token: str) -> bool:
        cleaned = str(token or "").strip().lower()
        if len(cleaned) < 3:
            return False
        if cleaned in _NAME_FREQ_IGNORE_TOKENS:
            return False
        if cleaned.isdigit():
            return False
        return True

    def _hydrate_name_frequency_cache(self) -> None:
        try:
            atoms = list(self.retriever.store.list_atoms())
        except Exception:
            return
        counts: dict[str, int] = {}
        for atom in atoms:
            unique_tokens: set[str] = set()
            for value in list(getattr(atom, "entities", []) or []):
                token = str(value or "").strip().lower()
                if self._is_name_frequency_candidate(token):
                    unique_tokens.add(token)
            for value in list(getattr(atom, "topics", []) or []):
                token = str(value or "").strip().lower()
                if self._is_name_frequency_candidate(token):
                    unique_tokens.add(token)
            for token in unique_tokens:
                counts[token] = int(counts.get(token, 0)) + 1
        self._name_frequency_counts = counts

    def _ordered_informative_tokens(self, text: str) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for tok in _INFO_TOKEN_RE.findall(str(text or "").lower()):
            if tok in _INFO_STOPWORDS:
                continue
            if tok in seen:
                continue
            seen.add(tok)
            ordered.append(tok)
        return ordered

    def _retrieval_profile_override(
        self,
        memory_preference: str | None,
        *,
        route_reason: str | None = None,
    ) -> str | None:
        if str(memory_preference or "").strip() == "session_recall":
            return "verbatim_session_recall"
        if str(route_reason or "").strip() == "verbatim_session_recall":
            return "verbatim_session_recall"
        return None

    def _retriever_retrieve(self, query: str, *, profile_override: str | None = None) -> RetrievalResult:
        if profile_override:
            try:
                return self.retriever.retrieve(
                    query,
                    continuity_store=self.continuity_store,
                    profile_override=profile_override,
                )
            except TypeError as exc:
                if "profile_override" not in str(exc):
                    raise
        return self.retriever.retrieve(query, continuity_store=self.continuity_store)

    def _retrieve_ltm(
        self,
        retrieval_text: str,
        *,
        retrieval_override_active: bool,
        profile_override: str | None = None,
    ) -> RetrievalPassResult:
        if retrieval_override_active:
            retrieval = self._retriever_retrieve(str(retrieval_text or "").strip(), profile_override=profile_override)
            return RetrievalPassResult(retrieval=retrieval, passes_used=1, stop_reason="override_single_pass")
        return self._retrieve_ltm_multi_pass(retrieval_text, profile_override=profile_override)

    def _retrieve_ltm_multi_pass(self, retrieval_text: str, *, profile_override: str | None = None) -> RetrievalPassResult:
        base_query = str(retrieval_text or "").strip()
        if not base_query:
            retrieval = self._retriever_retrieve(retrieval_text, profile_override=profile_override)
            return RetrievalPassResult(retrieval=retrieval, passes_used=1, stop_reason="single_pass")
        if not self.ltm_multi_pass_enabled or self.ltm_max_passes <= 1:
            retrieval = self._retriever_retrieve(base_query, profile_override=profile_override)
            return RetrievalPassResult(retrieval=retrieval, passes_used=1, stop_reason="single_pass")

        best = None
        best_key = None
        passes_used = 0
        stop_reason = "max_passes_reached"
        started = time.perf_counter()
        seen_queries: set[str] = set()
        query = base_query
        for pass_idx in range(max(1, int(self.ltm_max_passes))):
            if passes_used > 0:
                if not self._needs_followup(best):
                    stop_reason = "confidence_sufficient"
                    break
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                if elapsed_ms >= self.ltm_followup_time_budget_ms:
                    stop_reason = "time_budget_exceeded"
                    break
                followup = self._build_followup_query(base_query, best)
                if not followup:
                    stop_reason = "no_followup_query"
                    break
                if followup in seen_queries:
                    stop_reason = "query_repeat"
                    break
                query = followup

            if _token_estimate(query) > self.ltm_followup_max_query_tokens:
                if pass_idx > 0:
                    stop_reason = "query_budget_exceeded"
                    break
            result = self._retriever_retrieve(query, profile_override=profile_override)
            passes_used += 1
            seen_queries.add(query)
            match_max, match_mean = self._query_match_stats(result)
            key = (match_max, match_mean, float(result.memory_pack.pack_confidence))
            if best is None or key > best_key:
                best = result
                best_key = key
        if best is None:
            retrieval = self._retriever_retrieve(retrieval_text, profile_override=profile_override)
            return RetrievalPassResult(retrieval=retrieval, passes_used=1, stop_reason="single_pass")
        if passes_used <= 1 and stop_reason == "max_passes_reached":
            stop_reason = "single_pass"
        return RetrievalPassResult(retrieval=best, passes_used=max(1, passes_used), stop_reason=stop_reason)

    def _build_followup_query(self, original_query: str, retrieval: Any) -> str:
        ordered = self._ordered_informative_tokens(original_query)
        if not ordered:
            return ""
        pack_tokens: set[str] = set()
        if retrieval is not None:
            pack = getattr(retrieval, "memory_pack", MemoryPack())
            items = list(pack.core) + list(pack.context) + list(pack.conflict) + list(pack.continuity)
            for item in items[:10]:
                pack_tokens.update(self._informative_tokens(item.canonical_text))

        unresolved = [tok for tok in ordered if tok not in pack_tokens]
        if not unresolved:
            unresolved = ordered
        high_signal = [tok for tok in unresolved if self._is_high_signal_token(tok)]
        remaining = [tok for tok in unresolved if tok not in high_signal]
        focus = high_signal + remaining
        query = " ".join(focus[:8]).strip()
        return query

    def trace_to_dict(self, trace: TurnTrace) -> dict[str, Any]:
        budget = self._budget_ledger_for_trace(trace)
        return {
            "turn_id": trace.turn_id,
            "session_id": trace.session_id,
            "timestamp": trace.timestamp.isoformat(),
            "user_text": trace.user_text,
            "response_text": trace.response_text,
            "decision": trace.decision,
            "citations": trace.citations,
            "pack_confidence": trace.pack_confidence,
            "retrieved_atom_ids": trace.retrieved_atom_ids,
            "memory_mode": trace.memory_mode,
            "memory_route": trace.memory_route,
            "route_reason": trace.route_reason,
            "route_reason_text": trace.route_reason_text,
            "retrieval_passes": trace.retrieval_passes,
            "retrieval_query_tokens": trace.retrieval_query_tokens,
            "retrieval_stop_reason": trace.retrieval_stop_reason,
            "retrieval_override": contract_to_dict(trace.retrieval_override),
            "retrieval_diagnostics": trace.retrieval_diagnostics,
            "memory_preference": trace.memory_preference,
            "short_term_hits": trace.short_term_hits,
            "memory_cards": trace.memory_cards,
            "claim_checks": trace.claim_checks,
            "writeback_event_id": trace.writeback_event_id,
            "budget": budget,
            "telemetry": {
                "retrieval_ms": trace.telemetry.retrieval_ms,
                "verifier_ms": trace.telemetry.verifier_ms,
                "total_ms": trace.telemetry.total_ms,
                "input_tokens": trace.telemetry.input_tokens,
                "output_tokens": trace.telemetry.output_tokens,
                "turn_cost_usd": trace.telemetry.turn_cost_usd,
                "cumulative_tokens": trace.telemetry.cumulative_tokens,
                "cumulative_cost_usd": trace.telemetry.cumulative_cost_usd,
            },
        }

    def _route_reason_text(self, code: str) -> str:
        return _ROUTE_REASON_TEXT.get(str(code or "").strip(), "Memory route selected by runtime policy.")

    def _budget_ledger_for_trace(self, trace: TurnTrace) -> dict[str, Any]:
        turn_tokens = int(trace.telemetry.input_tokens) + int(trace.telemetry.output_tokens)
        retrieval_pass_limit = max(1, int(self.ltm_max_passes))
        warnings: list[dict[str, str]] = []
        if trace.retrieval_stop_reason == "time_budget_exceeded":
            warnings.append(
                {
                    "code": "RETRIEVAL_TIME_BUDGET",
                    "severity": "warn",
                    "message": "Retrieval follow-up time budget was reached.",
                }
            )
        if trace.retrieval_stop_reason == "query_budget_exceeded":
            warnings.append(
                {
                    "code": "RETRIEVAL_QUERY_BUDGET",
                    "severity": "warn",
                    "message": "Retrieval query token budget was reached.",
                }
            )
        if trace.retrieval_stop_reason == "query_repeat":
            warnings.append(
                {
                    "code": "RETRIEVAL_QUERY_REPEAT",
                    "severity": "warn",
                    "message": "Retrieval follow-up query repeated and retrieval was stopped.",
                }
            )
        if trace.retrieval_stop_reason == "no_followup_query":
            warnings.append(
                {
                    "code": "RETRIEVAL_NO_FOLLOWUP",
                    "severity": "warn",
                    "message": "No informative follow-up query could be derived.",
                }
            )
        if trace.retrieval_passes >= retrieval_pass_limit and trace.retrieval_stop_reason in {"max_passes_reached", "single_pass"}:
            warnings.append(
                {
                    "code": "RETRIEVAL_PASS_CAP",
                    "severity": "warn",
                    "message": "Retrieval reached configured pass cap.",
                }
            )
        if float(trace.telemetry.total_ms) > self.turn_latency_warn_ms:
            warnings.append(
                {
                    "code": "TURN_LATENCY_HIGH",
                    "severity": "warn",
                    "message": "Turn latency exceeded warning threshold.",
                }
            )
        if turn_tokens > self.turn_token_warn_limit:
            warnings.append(
                {
                    "code": "TURN_TOKEN_HIGH",
                    "severity": "warn",
                    "message": "Turn token usage exceeded warning threshold.",
                }
            )
        if float(trace.telemetry.turn_cost_usd) > self.turn_cost_warn_limit_usd:
            warnings.append(
                {
                    "code": "TURN_COST_HIGH",
                    "severity": "warn",
                    "message": "Turn cost estimate exceeded warning threshold.",
                }
            )
        return {
            "warning_state": "warn" if warnings else "ok",
            "warnings": warnings,
            "limits": {
                "retrieval_passes": retrieval_pass_limit,
                "retrieval_query_tokens": int(self.ltm_followup_max_query_tokens),
                "retrieval_followup_time_ms": float(self.ltm_followup_time_budget_ms),
                "turn_latency_ms": float(self.turn_latency_warn_ms),
                "turn_tokens": int(self.turn_token_warn_limit),
                "turn_cost_usd": float(self.turn_cost_warn_limit_usd),
            },
            "usage": {
                "retrieval_passes": int(trace.retrieval_passes),
                "retrieval_query_tokens": int(trace.retrieval_query_tokens),
                "retrieval_followup_time_ms": float(trace.telemetry.retrieval_ms),
                "turn_latency_ms": float(trace.telemetry.total_ms),
                "turn_tokens": int(turn_tokens),
                "turn_cost_usd": float(trace.telemetry.turn_cost_usd),
            },
        }

    def _candidate_claims(self, pack: MemoryPack) -> list[str]:
        claims = [item.canonical_text for item in pack.core[:3]]
        if not claims and pack.conflict:
            claims = [item.canonical_text for item in pack.conflict[:2]]
        return claims

    def _query_match_stats(self, retrieval: Any) -> tuple[float, float]:
        scored = list(getattr(retrieval, "scored_atoms", []) or [])
        if not scored:
            return 0.0, 0.0
        top = scored[:5]
        scores = [max(float(item.lexical), float(item.semantic)) for item in top]
        if not scores:
            return 0.0, 0.0
        return max(scores), (sum(scores) / len(scores))

    def _pack_query_support_profile(self, query_text: str, pack: MemoryPack) -> tuple[float, float, int]:
        q_tokens = self._informative_tokens(query_text)
        if not q_tokens:
            return 0.0, 0.0, 0
        union_matches: set[str] = set()
        per_item_overlap: list[float] = []
        for item in (list(pack.core) + list(pack.context))[:6]:
            tokens = self._informative_tokens(item.canonical_text)
            if not tokens:
                continue
            matched = q_tokens.intersection(tokens)
            if not matched:
                continue
            union_matches.update(matched)
            per_item_overlap.append(len(matched) / max(1, len(q_tokens)))
        if not per_item_overlap:
            return 0.0, 0.0, 0
        return len(union_matches) / max(1, len(q_tokens)), max(per_item_overlap), len(per_item_overlap)

    def _core_distributed_query_support(self, query_text: str, pack: MemoryPack) -> tuple[float, int, float]:
        q_tokens = self._informative_tokens(query_text)
        if not q_tokens:
            return 0.0, 0, 0.0
        core_items = [item for item in list(pack.core)[:3] if self._informative_tokens(item.canonical_text)]
        if len(core_items) < 3:
            return 0.0, 0, 0.0
        union_tokens: set[str] = set()
        confidence_values: list[float] = []
        for item in core_items:
            union_tokens.update(self._informative_tokens(item.canonical_text))
            confidence_values.append(_clamp01(float(getattr(item, "confidence", 0.0) or 0.0)))
        if not union_tokens or not confidence_values:
            return 0.0, 0, 0.0
        matched = q_tokens.intersection(union_tokens)
        overlap = len(matched) / max(1, len(q_tokens))
        mean_confidence = sum(confidence_values) / len(confidence_values)
        return overlap, len(matched), mean_confidence

    def _has_coherent_distributed_core_support(
        self,
        query_text: str,
        pack: MemoryPack,
        *,
        informative_count: int,
        required_hits: int,
    ) -> bool:
        core_overlap, core_match_count, core_mean_confidence = self._core_distributed_query_support(query_text, pack)
        distributed_overlap_floor = max(
            self.min_query_informative_overlap,
            required_hits / max(1, informative_count),
        )
        distributed_confidence_floor = min(0.75, float(getattr(self.verifier, "support_threshold", 0.40)) + 0.10)
        return (
            core_match_count >= required_hits
            and core_overlap >= distributed_overlap_floor
            and core_mean_confidence >= distributed_confidence_floor
        )

    def _needs_followup(self, retrieval: Any) -> bool:
        if retrieval is None:
            return True
        pack = getattr(retrieval, "memory_pack", MemoryPack())
        has_evidence = bool(pack.core or pack.context or pack.conflict or pack.continuity)
        if not has_evidence:
            return True
        match_max, _match_mean = self._query_match_stats(retrieval)
        if match_max < self.ltm_followup_min_match_max:
            return True
        if float(pack.pack_confidence) < self.ltm_followup_min_pack_confidence:
            return True
        return False

    def _informative_tokens(self, text: str) -> set[str]:
        out: set[str] = set()
        for tok in _INFO_TOKEN_RE.findall(str(text or "").lower()):
            if tok in _INFO_STOPWORDS:
                continue
            out.add(tok)
        return out

    def _is_high_signal_token(self, token: str) -> bool:
        return "_" in token or any(ch.isdigit() for ch in token)

    def _query_informative_overlap(self, query_text: str, pack: MemoryPack) -> tuple[float, int, int, int, int]:
        q_tokens = self._informative_tokens(query_text)
        if not q_tokens:
            return 0.0, 0, 0, 0, 0
        signal_tokens = {token for token in q_tokens if self._is_high_signal_token(token)}
        pack_tokens: set[str] = set()
        items = list(pack.core) + list(pack.context) + list(pack.conflict) + list(pack.continuity)
        for item in items:
            pack_tokens.update(self._informative_tokens(item.canonical_text))
        if not pack_tokens:
            return 0.0, len(q_tokens), 0, len(signal_tokens), 0
        matched = q_tokens.intersection(pack_tokens)
        signal_matched = signal_tokens.intersection(pack_tokens)
        overlap = len(matched) / max(1, len(q_tokens))
        return overlap, len(q_tokens), len(matched), len(signal_tokens), len(signal_matched)

    def _apply_query_evidence_gate(
        self,
        verification: VerificationResult,
        retrieval: Any,
        retrieval_query: str,
        *,
        support_pack: MemoryPack | None = None,
    ) -> VerificationResult:
        if verification.decision is not VerificationDecision.PASS:
            return verification
        match_max, match_mean = self._query_match_stats(retrieval)
        gate_pack = support_pack or getattr(retrieval, "memory_pack", MemoryPack())
        informative_overlap, informative_count, informative_matches, signal_count, signal_matches = self._query_informative_overlap(
            retrieval_query,
            gate_pack,
        )
        required_hits = 1 if informative_count == 2 else min(self.min_query_token_hits, informative_count) if informative_count >= 2 else 1
        has_distributed_core_support = self._has_coherent_distributed_core_support(
            retrieval_query,
            gate_pack,
            informative_count=informative_count,
            required_hits=required_hits,
        )
        if signal_count > 0 and signal_matches == 0:
            if not has_distributed_core_support:
                return self._force_abstain(
                    verification,
                    reason="QUERY_SIGNAL_MISSING",
                    confidence=informative_overlap,
                )
        if informative_count >= 2:
            if informative_matches < required_hits:
                return self._force_abstain(
                    verification,
                    reason="QUERY_INFORMATIVE_MISMATCH",
                    confidence=informative_overlap,
                )
            if informative_overlap < self.min_query_informative_overlap:
                return self._force_abstain(
                    verification,
                    reason="QUERY_INFORMATIVE_MISMATCH",
                    confidence=informative_overlap,
                )
        if match_max >= self.min_query_match_max or match_mean >= self.min_query_match_mean:
            return verification
        pack_overlap, pack_item_max, pack_support_items = self._pack_query_support_profile(
            retrieval_query,
            gate_pack,
        )
        if pack_support_items >= 2 and (
            pack_overlap >= self.min_query_informative_overlap or pack_item_max >= self.min_query_match_max
        ):
            return verification
        if has_distributed_core_support:
            return verification
        return self._force_abstain(
            verification,
            reason="QUERY_EVIDENCE_WEAK",
            confidence=max(match_max, match_mean, pack_item_max, informative_overlap),
        )

    def _apply_pack_query_gate(
        self,
        verification: VerificationResult,
        pack: MemoryPack,
        retrieval_query: str,
        *,
        high_risk: bool,
    ) -> VerificationResult:
        if verification.decision is not VerificationDecision.PASS:
            return verification
        informative_overlap, informative_count, informative_matches, signal_count, signal_matches = self._query_informative_overlap(
            retrieval_query,
            pack,
        )
        if signal_count > 0 and signal_matches == 0:
            return self._force_abstain(
                verification,
                reason="QUERY_SIGNAL_MISSING",
                confidence=informative_overlap,
            )
        if high_risk and informative_count >= 2:
            required_hits = 1 if informative_count == 2 else min(self.min_query_token_hits, informative_count)
            if informative_matches < required_hits:
                return self._force_abstain(
                    verification,
                    reason="QUERY_INFORMATIVE_MISMATCH",
                    confidence=informative_overlap,
                )
            if informative_overlap < self.min_query_informative_overlap:
                return self._force_abstain(
                    verification,
                    reason="QUERY_INFORMATIVE_MISMATCH",
                    confidence=informative_overlap,
                )
        return verification

    def _force_abstain(
        self,
        verification: VerificationResult,
        *,
        reason: str,
        confidence: float,
    ) -> VerificationResult:
        gated_checks = list(verification.checks)
        gated_checks.append(
            ClaimCheck(
                claim="__query_evidence__",
                supported=False,
                confidence=max(0.0, float(confidence)),
                citations=[],
                reason=reason,
            )
        )
        unsupported = list(verification.unsupported_claims)
        unsupported.append(reason)
        return VerificationResult(
            decision=VerificationDecision.ABSTAIN,
            checks=gated_checks,
            unsupported_claims=unsupported,
            needs_uncertainty=verification.needs_uncertainty,
        )

    def _is_provisional_noise(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return True
        if normalized.endswith("?"):
            return True
        if any(phrase in normalized for phrase in _PROVISIONAL_NOISE_PHRASES):
            return True
        informative = self._ordered_informative_tokens(normalized)
        return len(informative) < 3

    def _provisional_kind_and_score(self, *, text: str, source_role: str) -> tuple[ProvisionalMemoryKind, float] | None:
        normalized = f" {re.sub(r'\\s+', ' ', str(text or '').strip().lower())} "
        if self._is_provisional_noise(normalized):
            return None
        informative_tokens = self._ordered_informative_tokens(normalized)
        info_score = min(0.30, 0.05 * float(len(informative_tokens)))
        if source_role == "assistant" and normalized.strip().startswith("i ") and any(
            hint in normalized for hint in _PROVISIONAL_SELF_CLAIM_HINTS
        ):
            return ProvisionalMemoryKind.SELF_CLAIM, min(1.0, 0.40 + info_score + 0.18)
        if any(hint in normalized for hint in _PROVISIONAL_CORRECTION_HINTS):
            return ProvisionalMemoryKind.CORRECTION, min(1.0, 0.38 + info_score + 0.16)
        if any(hint in normalized for hint in _PROVISIONAL_PREFERENCE_HINTS):
            return ProvisionalMemoryKind.PREFERENCE, min(1.0, 0.36 + info_score + 0.14)
        if any(hint in normalized for hint in _PROVISIONAL_PLAN_HINTS):
            return ProvisionalMemoryKind.PLAN, min(1.0, 0.34 + info_score + 0.14)
        if "remember this" in normalized or "important" in normalized:
            return ProvisionalMemoryKind.EVENT_NOTE, min(1.0, 0.34 + info_score + 0.12)
        if len(informative_tokens) >= 5:
            return ProvisionalMemoryKind.FACT, min(1.0, 0.32 + info_score + 0.10)
        return None

    def _proposal_kind_and_score(self, *, text: str, source_role: str) -> tuple[ProposalKind, str, float] | None:
        normalized = f" {re.sub(r'\\s+', ' ', str(text or '').strip().lower())} "
        if self._is_provisional_noise(normalized):
            return None
        info_score = min(0.24, 0.04 * float(len(self._ordered_informative_tokens(normalized))))
        if source_role == "assistant" and normalized.strip().startswith("i "):
            return None
        if any(hint in normalized for hint in _PROPOSAL_OTHER_PERSON_STATE_HINTS):
            return ProposalKind.OTHER_PERSON_INTERNAL_STATE, "other_person_internal_state", min(1.0, 0.48 + info_score)
        if any(hint in normalized for hint in _PROPOSAL_IDENTITY_HINTS):
            return ProposalKind.IDENTITY_SUMMARY, "identity_summary", min(1.0, 0.44 + info_score)
        if any(hint in normalized for hint in _PROPOSAL_RELATIONSHIP_HINTS):
            return ProposalKind.RELATIONSHIP_SUMMARY, "relationship_summary", min(1.0, 0.44 + info_score)
        if any(hint in normalized for hint in _PROPOSAL_MOTIVE_HINTS):
            return ProposalKind.INFERRED_MOTIVE, "inferred_motive", min(1.0, 0.42 + info_score)
        if any(hint in normalized for hint in _PROPOSAL_LIFE_STORY_HINTS):
            return ProposalKind.LIFE_STORY_CLAIM, "life_story_claim", min(1.0, 0.42 + info_score)
        return None

    def _proposal_candidate(
        self,
        *,
        text: str,
        source_role: str,
        source_id: str,
        message_id: str,
        timestamp: datetime,
        session_id: str,
    ) -> ProposalCandidate | None:
        candidate, _drop_reason = self._proposal_candidate_with_reason(
            text=text,
            source_role=source_role,
            source_id=source_id,
            message_id=message_id,
            timestamp=timestamp,
            session_id=session_id,
        )
        return candidate

    def _proposal_candidate_with_reason(
        self,
        *,
        text: str,
        source_role: str,
        source_id: str,
        message_id: str,
        timestamp: datetime,
        session_id: str,
    ) -> tuple[ProposalCandidate | None, str | None]:
        if self._proposal_store is None or not self._proposal_capture_enabled:
            return None, "proposal_capture_disabled"
        resolved = self._proposal_kind_and_score(text=text, source_role=source_role)
        if resolved is None:
            return None, "not_high_risk_class"
        kind, reason_code, score = resolved
        source_ref = SourceRef(
            source_id=source_id,
            message_id=message_id,
            timestamp=timestamp,
            span_start=0,
            span_end=max(1, len(str(text or ""))),
        )
        return (
            ProposalCandidate(
                kind=kind,
                canonical_text=self._compact_text(str(text or "").strip(), max_chars=280),
                source_refs=[source_ref],
                source_role=source_role,
                session_id=session_id,
                reason_code=reason_code,
                confidence=_clamp01(0.18 + score * 0.82),
                metadata={
                    "capture_reason": "turn_proposal_only",
                    "memory_layer": "proposal_only",
                    "trust_tier": "proposal_pending",
                },
            ),
            None,
        )

    def _provisional_candidate(
        self,
        *,
        text: str,
        source_role: str,
        source_id: str,
        message_id: str,
        timestamp: datetime,
        session_id: str,
    ) -> ProvisionalMemoryCandidate | None:
        candidate, _drop_reason = self._provisional_candidate_with_reason(
            text=text,
            source_role=source_role,
            source_id=source_id,
            message_id=message_id,
            timestamp=timestamp,
            session_id=session_id,
        )
        return candidate

    def _provisional_candidate_with_reason(
        self,
        *,
        text: str,
        source_role: str,
        source_id: str,
        message_id: str,
        timestamp: datetime,
        session_id: str,
    ) -> tuple[ProvisionalMemoryCandidate | None, str | None]:
        resolved = self._provisional_kind_and_score(text=text, source_role=source_role)
        if resolved is None:
            normalized = f" {re.sub(r'\\s+', ' ', str(text or '').strip().lower())} "
            if self._is_provisional_noise(normalized):
                return None, "noise_or_low_signal"
            return None, "no_supported_memory_class"
        kind, score = resolved
        profile = self._provisional_profile()
        threshold = profile.self_claim_threshold if kind is ProvisionalMemoryKind.SELF_CLAIM else profile.worthiness_threshold
        if source_role == "assistant" and kind is not ProvisionalMemoryKind.SELF_CLAIM:
            return None, "assistant_non_self_claim"
        if kind is ProvisionalMemoryKind.SELF_CLAIM and not self._provisional_policy.allow_self_claim_auto_write:
            return None, "self_claim_auto_write_disabled"
        if score < threshold:
            if kind is ProvisionalMemoryKind.SELF_CLAIM:
                return None, "self_claim_below_threshold"
            return None, "worthiness_below_threshold"
        source_ref = SourceRef(
            source_id=source_id,
            message_id=message_id,
            timestamp=timestamp,
            span_start=0,
            span_end=max(1, len(str(text or ""))),
        )
        stability = 0.12 if kind is ProvisionalMemoryKind.SELF_CLAIM else 0.24
        return (
            ProvisionalMemoryCandidate(
                kind=kind,
                canonical_text=self._compact_text(str(text or "").strip(), max_chars=280),
                source_refs=[source_ref],
                source_role=source_role,
                session_id=session_id,
                confidence=_clamp01(0.22 + score * 0.78),
                salience=_clamp01(0.18 + score * 0.82),
                stability=stability,
                metadata={"capture_reason": "turn_auto_write", "source_role": source_role},
            ),
            None,
        )

    def _capture_provisional_memory_from_text(
        self,
        *,
        text: str,
        source_role: str,
        session: SessionState,
        source_id: str,
        message_id: str,
        timestamp: datetime,
        reason: str,
    ) -> int:
        if self._provisional_store is None:
            return 0
        try:
            assert_safe_content(text)
        except SecretDetectedError:
            self._record_memory_capture_drop("secret_like_content_rejected")
            return 0
        profile = self._provisional_profile()
        with self._lock:
            if session.provisional_write_count >= profile.max_auto_writes_per_session:
                self._record_memory_capture_drop("session_cap_reached")
                return 0
        proposal_candidate, proposal_drop_reason = self._proposal_candidate_with_reason(
            text=text,
            source_role=source_role,
            source_id=source_id,
            message_id=message_id,
            timestamp=timestamp,
            session_id=session.session_id,
        )
        if proposal_candidate is not None:
            self._proposal_store.upsert_candidate(proposal_candidate, reason=reason)
            with self._lock:
                session.provisional_write_count += 1
                self._memory_capture_proposal_only_count += 1
            return 1
        candidate, drop_reason = self._provisional_candidate_with_reason(
            text=text,
            source_role=source_role,
            source_id=source_id,
            message_id=message_id,
            timestamp=timestamp,
            session_id=session.session_id,
        )
        if candidate is None:
            self._record_memory_capture_drop(drop_reason or proposal_drop_reason or "unclassified_drop")
            return 0
        if candidate.kind is ProvisionalMemoryKind.CORRECTION:
            record = self._apply_provisional_correction_candidate(candidate, reason=reason)
        else:
            record = self._provisional_store.upsert_candidate(candidate, reason=reason)
        if record is None:
            self._record_memory_capture_drop("correction_target_missing")
            return 0
        self._detect_and_log_near_duplicates(record)
        with self._lock:
            session.provisional_write_count += 1
            self._memory_capture_provisional_accepted_count += 1
            if reason == "soft_close_gap" or reason == "runtime_close" or reason == "session_boundary":
                self._memory_capture_sweep_promotion_count += 1
        return 1

    def _apply_provisional_correction_candidate(
        self,
        candidate: ProvisionalMemoryCandidate,
        *,
        reason: str,
    ) -> ProvisionalMemoryRecord | None:
        if self._provisional_store is None:
            return None
        hits = self._provisional_store.search(candidate.canonical_text, limit=4)
        previous = next(
            (
                hit.record
                for hit in hits
                if hit.record.status is ProvisionalMemoryStatus.ACTIVE
                and hit.record.record_id
                and hit.record.canonical_text.strip().lower() != candidate.canonical_text.strip().lower()
                and len(hit.matched_terms) >= 2
            ),
            None,
        )
        if previous is None:
            return self._provisional_store.upsert_candidate(candidate, reason=reason)
        replacement_kind = previous.kind if previous.kind is not ProvisionalMemoryKind.CORRECTION else ProvisionalMemoryKind.FACT
        replacement = ProvisionalMemoryCandidate(
            kind=replacement_kind,
            canonical_text=candidate.canonical_text,
            source_refs=list(candidate.source_refs),
            source_role=candidate.source_role,
            session_id=candidate.session_id,
            confidence=candidate.confidence,
            salience=candidate.salience,
            stability=max(candidate.stability, previous.stability),
            metadata=dict(candidate.metadata),
        )
        return self._provisional_store.supersede_record(previous.record_id, replacement, reason=reason)

    def _has_near_duplicate_event(self, *, record_id: str, other_record_id: str) -> bool:
        if self._provisional_store is None:
            return False
        for event in self._provisional_store.list_events(record_id=record_id, event_type=ProvisionalMemoryEventType.NEAR_DUPLICATE):
            if str((event.metadata or {}).get("other_record_id") or "").strip() == other_record_id:
                return True
        return False

    def _detect_and_log_near_duplicates(self, record: ProvisionalMemoryRecord) -> int:
        if self._provisional_store is None:
            return 0
        policy = self._provisional_policy.near_duplicate
        if not bool(policy.enabled):
            return 0
        hits = self._provisional_store.search(record.canonical_text, limit=8)
        logged = 0
        for hit in hits:
            other = hit.record
            if other.record_id == record.record_id:
                continue
            if _normalize_text(other.canonical_text) == _normalize_text(record.canonical_text):
                continue
            similarity = float(hit.score)
            if similarity < float(policy.similarity_threshold):
                continue
            if self._has_near_duplicate_event(record_id=record.record_id, other_record_id=other.record_id):
                continue
            created_at = getattr(record, "created_at", None)
            other_created_at = getattr(other, "created_at", None)
            ordering = "same_time"
            if created_at is not None and other_created_at is not None:
                if created_at < other_created_at:
                    ordering = "left_before_right"
                elif created_at > other_created_at:
                    ordering = "left_after_right"
            self._provisional_store.record_near_duplicate(
                record_id=record.record_id,
                other_record_id=other.record_id,
                similarity_score=similarity,
                metadata={
                    "left_record_id": record.record_id,
                    "right_record_id": other.record_id,
                    "same_session": "true" if record.session_id == other.session_id else "false",
                    "same_source_role": "true" if record.source_role == other.source_role else "false",
                    "same_kind": "true" if record.kind is other.kind else "false",
                    "same_conflict_state": "true" if record.status is other.status else "false",
                    "timestamp_order": ordering,
                },
            )
            logged += 1
            if logged >= int(policy.max_pairs_per_record):
                break
        if logged > 0:
            with self._lock:
                self._memory_capture_duplicate_suspected_count += logged
        return logged

    def _capture_provisional_turn(
        self,
        *,
        turn_id: str,
        session: SessionState,
        user_text: str,
        response_text: str,
        timestamp: datetime,
    ) -> int:
        if self._provisional_store is None:
            return 0
        profile = self._provisional_profile()
        created = 0
        entries = [
            ("user", user_text, f"turn:{turn_id}:user", f"{turn_id}:user"),
            ("assistant", response_text, f"turn:{turn_id}:assistant", f"{turn_id}:assistant"),
        ]
        for source_role, text, source_id, message_id in entries:
            if created >= profile.max_auto_writes_per_turn:
                break
            created += self._capture_provisional_memory_from_text(
                text=text,
                source_role=source_role,
                session=session,
                source_id=source_id,
                message_id=message_id,
                timestamp=timestamp,
                reason="turn_auto_write",
            )
        return created

    def _looks_like_soft_close_hint(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        return any(hint in normalized for hint in _SOFT_CLOSE_HINTS)

    def _handle_soft_close_state(self, *, session: SessionState, upcoming_text: str) -> int:
        if not self._provisional_stm_sweep_enabled:
            return 0
        now = _utc_now()
        with self._lock:
            hint_at = session.soft_close_hint_at
        if hint_at is None:
            return 0
        gap_seconds = max(1, int(self._provisional_policy.inactivity_gap_seconds))
        idle_seconds = max(0.0, (now - hint_at).total_seconds())
        if idle_seconds >= float(gap_seconds):
            return self.flush_session_to_provisional(session.session_id, reason="soft_close_gap")
        if str(upcoming_text or "").strip():
            with self._lock:
                session.soft_close_hint_at = None
                session.soft_close_hint_text = ""
        return 0

    def _retrieve_provisional_memory(self, query_text: str) -> tuple[MemoryPack, list[str], int, float]:
        if self._provisional_store is None or not self._provisional_retrieval_enabled:
            return MemoryPack(), [], 0, 0.0
        hits = self.search_provisional_memory(query_text, limit=4)
        if not hits:
            return MemoryPack(), [], 0, 0.0
        core_items: list[MemoryPackItem] = []
        context_items: list[MemoryPackItem] = []
        ranked_ids: list[str] = []
        atom_store = getattr(self.retriever, "store", None)
        for hit in hits:
            if isinstance(atom_store, SqliteAtomStore) and atom_store.is_provisional_bridge_suppressed(hit.record.record_id):
                continue
            confidence = min(0.78, 0.32 + float(hit.score) * 0.70)
            item = MemoryPackItem(
                atom_id=hit.record.record_id,
                canonical_text=hit.record.canonical_text,
                confidence=_clamp01(confidence),
                source_refs=list(hit.record.source_refs),
                record_updated_at=hit.record.updated_at,
                conflict_state=hit.record.status.value,
                conflict_with_ids=list(hit.record.conflict_with_record_ids),
                memory_layer="provisional",
                trust_tier="provisional",
                authority_tier=hit.record.authority_tier.value,
                maturity=hit.record.maturity.value,
                lifecycle=hit.record.lifecycle.value,
                human_reviewed=False,
                lineage_ids=list(hit.record.input_record_ids),
            )
            if not core_items:
                core_items.append(item)
            else:
                context_items.append(item)
            ranked_ids.append(item.atom_id)
        if not core_items and not context_items:
            return MemoryPack(), [], 0, 0.0
        pack_confidence = _clamp01(max(item.confidence for item in list(core_items) + list(context_items)))
        return (
            memory_pack_from_items(core_items, context=context_items, pack_confidence=pack_confidence),
            ranked_ids,
            len(ranked_ids),
            pack_confidence,
        )

    def _merge_long_term_with_provisional(self, long_term: MemoryPack, provisional: MemoryPack) -> MemoryPack:
        if not provisional.core and not provisional.context:
            return long_term
        if not long_term.core and not long_term.context and not long_term.continuity and not long_term.conflict:
            return provisional
        authority_resolver_enabled = bool(
            self.config.retrieval.derived_helpers.temporal_lift.enabled
            or self.config.retrieval.derived_helpers.update_family_resolver.enabled
        )

        def _unique(items: list[MemoryPackItem], limit: int) -> list[MemoryPackItem]:
            out: list[MemoryPackItem] = []
            seen: set[str] = set()
            for item in items:
                if item.atom_id in seen:
                    continue
                seen.add(item.atom_id)
                out.append(item)
                if len(out) >= limit:
                    break
            return out

        core_items = list(long_term.core) + list(provisional.core)
        context_items = list(long_term.context) + list(provisional.context)
        if authority_resolver_enabled:
            core_items = sorted(core_items, key=self._memory_item_precedence_key, reverse=True)
            context_items = sorted(context_items, key=self._memory_item_precedence_key, reverse=True)
        core = _unique(core_items, 6)
        context = _unique(context_items, 8)
        conflict = _unique(list(long_term.conflict), 6)
        continuity = _unique(list(long_term.continuity), 6)
        pack_confidence = _clamp01(long_term.pack_confidence * 0.75 + provisional.pack_confidence * 0.25)
        return memory_pack_from_items(
            core,
            context=context,
            conflict=conflict,
            continuity=continuity,
            pack_confidence=pack_confidence,
        )

    @staticmethod
    def _memory_item_precedence_key(item: MemoryPackItem) -> tuple[int, int, str, str, str]:
        trust_tier = str(getattr(item, "trust_tier", "") or "").strip().lower()
        explicit_authority = str(getattr(item, "authority_tier", "") or "").strip().lower()
        rank_tier = (
            explicit_authority
            if explicit_authority in {"provisional_consolidated", "provisional_observed"}
            else trust_tier
        )
        authority_rank = {
            "human_reviewed_canonical": 4,
            "published": 4,
            "evidence_atom": 3,
            "evidence": 3,
            "provisional_consolidated": 2,
            "provisional_observed": 1,
            "provisional": 1,
        }.get(rank_tier, 0)
        conflict_state = str(getattr(item, "conflict_state", "active") or "active").strip().lower()
        status_rank = {
            "active": 3,
            "conflicted": 2,
            "superseded": 1,
        }.get(conflict_state, 0)
        source_time = ""
        for ref in list(getattr(item, "source_refs", []) or []):
            timestamp = getattr(ref, "timestamp", None)
            if timestamp is None:
                continue
            normalized = timestamp.isoformat()
            if normalized > source_time:
                source_time = normalized
        updated_at = getattr(item, "record_updated_at", None)
        updated_key = updated_at.isoformat() if isinstance(updated_at, datetime) else ""
        return (authority_rank, status_rank, source_time, updated_key, str(item.atom_id or ""))

    def _session_working_set_tokens(self, session: SessionState) -> int:
        short_term_tokens = sum(_token_estimate(note.text) for note in session.short_term)
        return short_term_tokens + _token_estimate(session.rolling_summary)

    def _stm_similarity(
        self,
        *,
        query_tokens: set[str],
        query_ngrams: set[str],
        target_text: str,
    ) -> tuple[float, float, float]:
        target_tokens = set(_tokenize(target_text))
        target_ngrams = _char_ngrams(target_text)
        if not target_tokens and not target_ngrams:
            return 0.0, 0.0, 0.0
        token_overlap = (
            len(query_tokens.intersection(target_tokens)) / max(1, len(query_tokens))
            if query_tokens
            else 0.0
        )
        ngram_overlap = _jaccard(query_ngrams, target_ngrams)
        similarity = (
            token_overlap * self.short_term_token_weight
            + ngram_overlap * self.short_term_ngram_weight
        )
        return token_overlap, ngram_overlap, _clamp01(similarity)

    def _compact_session_summary(self, session: SessionState) -> None:
        if not self.short_term_summary_enabled:
            session.summary_segments.clear()
            session.rolling_summary = ""
            return
        joined = " | ".join(str(item or "").strip() for item in session.summary_segments if str(item or "").strip())
        session.rolling_summary = self._compact_text(joined, max_chars=self.short_term_summary_max_chars) if joined else ""

    def _append_summary_segment(self, session: SessionState, note: ShortTermNote) -> None:
        if not self.short_term_summary_enabled:
            return
        fragment = self._compact_text(note.text, max_chars=min(self.short_term_note_max_chars, 200))
        if not fragment:
            return
        session.summary_segments.append(f"{note.role}: {fragment}")
        self._compact_session_summary(session)

    def _evict_oldest_short_term_note(self, session: SessionState) -> bool:
        if not session.short_term:
            return False
        evicted = session.short_term.popleft()
        self._append_summary_segment(session, evicted)
        return True

    def _enforce_working_set_budget(self, session: SessionState) -> None:
        while len(session.short_term) > self.short_term_capacity:
            if not self._evict_oldest_short_term_note(session):
                break
        while self._session_working_set_tokens(session) > self.short_term_working_set_token_limit and session.short_term:
            if not self._evict_oldest_short_term_note(session):
                break
        while (
            self._session_working_set_tokens(session) > self.short_term_working_set_token_limit
            and session.summary_segments
        ):
            session.summary_segments.popleft()
            self._compact_session_summary(session)
        if session.rolling_summary and len(session.rolling_summary) > self.short_term_summary_max_chars:
            session.rolling_summary = self._compact_text(session.rolling_summary, max_chars=self.short_term_summary_max_chars)

    def _retrieve_short_term(
        self,
        query_text: str,
        *,
        session: SessionState | None = None,
    ) -> tuple[MemoryPack, list[str], int, float]:
        if not self.short_term_enabled:
            return MemoryPack(), [], 0, 0.0
        active = session or self._ensure_session("default")
        query_tokens = set(_tokenize(query_text))
        query_ngrams = _char_ngrams(query_text)
        if not query_tokens and not query_ngrams:
            return MemoryPack(), [], 0, 0.0

        with self._lock:
            notes = list(active.short_term)
            rolling_summary = active.rolling_summary

        scored: list[tuple[float, ShortTermNote]] = []
        total = len(notes)
        for idx, note in enumerate(reversed(notes)):
            token_overlap, ngram_overlap, similarity = self._stm_similarity(
                query_tokens=query_tokens,
                query_ngrams=query_ngrams,
                target_text=note.text,
            )
            if token_overlap < self.short_term_min_overlap and ngram_overlap < self.short_term_min_ngram:
                continue
            recency = 1.0 - (idx / max(total, 1)) * 0.35
            score = _clamp01(similarity * 0.75 + recency * 0.25)
            if score < self.short_term_min_score:
                continue
            scored.append((score, note))

        summary_score = 0.0
        if rolling_summary:
            summary_overlap, summary_ngram, summary_similarity = self._stm_similarity(
                query_tokens=query_tokens,
                query_ngrams=query_ngrams,
                target_text=rolling_summary,
            )
            if summary_overlap >= self.short_term_summary_match_floor or summary_ngram >= self.short_term_min_ngram:
                summary_score = _clamp01(summary_similarity * 0.85 + 0.15)

        if not scored and summary_score <= 0.0:
            return MemoryPack(), [], 0, 0.0

        top: list[tuple[float, ShortTermNote]] = []
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            top = scored[: self.short_term_top_k]

        core_items: list[MemoryPackItem] = []
        context_items: list[MemoryPackItem] = []
        ranked_ids: list[str] = []
        for score, note in top:
            source = SourceRef(
                source_id=f"stm:{note.turn_id}",
                message_id=note.note_id,
                timestamp=note.created_at,
                span_start=0,
                span_end=max(1, len(note.text)),
            )
            atom_id = f"stm_{note.note_id}"
            core_items.append(
                MemoryPackItem(
                    atom_id=atom_id,
                    canonical_text=note.text,
                    confidence=score,
                    source_refs=[source],
                    record_updated_at=note.created_at,
                    conflict_state="active",
                    memory_layer="short_term",
                    trust_tier="ephemeral",
                )
            )
            ranked_ids.append(atom_id)

        if summary_score > 0.0:
            summary_atom_id = f"stm_summary_{active.session_id}"
            summary_source = SourceRef(
                source_id=f"stm-summary:{active.session_id}",
                message_id="rolling",
                timestamp=active.updated_at,
                span_start=0,
                span_end=max(1, len(rolling_summary)),
            )
            summary_item = MemoryPackItem(
                atom_id=summary_atom_id,
                canonical_text=rolling_summary,
                confidence=summary_score,
                source_refs=[summary_source],
                record_updated_at=active.updated_at,
                conflict_state="active",
                memory_layer="short_term",
                trust_tier="ephemeral",
            )
            if core_items:
                context_items.append(summary_item)
            else:
                core_items.append(summary_item)
            ranked_ids.append(summary_atom_id)

        all_items = list(core_items) + list(context_items)
        confidence = _clamp01(sum(item.confidence for item in all_items) / max(1, len(all_items)))
        gate_candidates = [score for score, _ in top]
        if summary_score > 0.0:
            gate_candidates.append(summary_score)
        gate_score = _clamp01(max(gate_candidates) if gate_candidates else 0.0)
        pack = memory_pack_from_items(core_items, context=context_items, pack_confidence=confidence)
        return pack, ranked_ids, len(all_items), gate_score

    def _merge_packs(self, short_term: MemoryPack, long_term: MemoryPack) -> MemoryPack:
        def _unique(items: list[MemoryPackItem], limit: int) -> list[MemoryPackItem]:
            out: list[MemoryPackItem] = []
            seen: set[str] = set()
            for item in items:
                if item.atom_id in seen:
                    continue
                seen.add(item.atom_id)
                out.append(item)
                if len(out) >= limit:
                    break
            return out

        core = _unique(list(short_term.core) + list(long_term.core), 6)
        context = _unique(list(short_term.context) + list(long_term.context), 8)
        conflict = _unique(list(long_term.conflict), 6)
        continuity = _unique(list(long_term.continuity), 6)
        pack_confidence = _clamp01(short_term.pack_confidence * 0.6 + long_term.pack_confidence * 0.4)
        return memory_pack_from_items(
            core,
            context=context,
            conflict=conflict,
            continuity=continuity,
            pack_confidence=pack_confidence,
        )

    def _assemble_memory_cards(self, pack: MemoryPack) -> list[MemoryCard]:
        cards: list[MemoryCard] = []
        seen_ids: set[str] = set()
        next_rank = 0

        def add_items(items: list[MemoryPackItem], *, contradiction: bool, section: str) -> None:
            nonlocal next_rank
            for item in items:
                current_rank = next_rank
                next_rank += 1
                if item.atom_id in seen_ids:
                    continue
                card = self._item_to_card(
                    item,
                    contradiction=contradiction,
                    section=section,
                    pack_rank=current_rank,
                )
                if card is None:
                    continue
                cards.append(card)
                seen_ids.add(item.atom_id)

        add_items(list(pack.core)[:3], contradiction=False, section="core")
        add_items(list(pack.context)[:2], contradiction=False, section="context")
        add_items(list(pack.continuity)[:2], contradiction=False, section="continuity")
        add_items(list(pack.conflict)[:2], contradiction=True, section="conflict")
        return self._merge_related_cards(cards, max_cards=6)

    @staticmethod
    def _memory_card_section_priority(section: str) -> int:
        return {
            "core": 4,
            "context": 3,
            "continuity": 2,
            "conflict": 1,
        }.get(str(section or "").strip().lower(), 0)

    def _merge_related_cards(self, cards: list[MemoryCard], *, max_cards: int) -> list[MemoryCard]:
        if not cards:
            return []
        merged: list[MemoryCard] = []
        index_by_key: dict[tuple[str, str, bool], int] = {}

        for card in cards:
            primary_source = ""
            if card.citations:
                primary_source = str(card.citations[0]).split("#", 1)[0].strip()
            key = (card.kind, primary_source, bool(card.contradiction))
            existing_idx = index_by_key.get(key)
            if existing_idx is None:
                merged.append(
                    MemoryCard(
                        card_id=card.card_id,
                        kind=card.kind,
                        summary=card.summary,
                        confidence=card.confidence,
                        contradiction=card.contradiction,
                        citations=list(card.citations),
                        atom_ids=list(card.atom_ids),
                        cluster_size=max(1, int(card.cluster_size)),
                        summary_abstractive=str(card.summary_abstractive or ""),
                        raw_excerpt=str(card.raw_excerpt or ""),
                        section=str(card.section or "").strip().lower(),
                        pack_rank=max(0, int(card.pack_rank)),
                        memory_layer=str(card.memory_layer or "").strip().lower(),
                        trust_tier=str(card.trust_tier or "").strip().lower(),
                        conflict_state=str(card.conflict_state or "active").strip().lower(),
                        conflict_visible=bool(card.conflict_visible),
                        conflict_winner=bool(card.conflict_winner),
                        conflict_with=list(card.conflict_with),
                    )
                )
                index_by_key[key] = len(merged) - 1
                continue

            existing = merged[existing_idx]
            existing.summary = self._merge_card_summary(existing.summary, card.summary, max_chars=220)
            existing.summary_abstractive = self._merge_card_summary(
                existing.summary_abstractive or existing.summary,
                card.summary_abstractive or card.summary,
                max_chars=220,
            )
            existing.raw_excerpt = self._merge_card_summary(
                existing.raw_excerpt or existing.summary,
                card.raw_excerpt or card.summary,
                max_chars=320,
            )
            existing.confidence = max(float(existing.confidence), float(card.confidence))
            existing.contradiction = bool(existing.contradiction or card.contradiction)
            existing.cluster_size = int(existing.cluster_size) + max(1, int(card.cluster_size))
            existing.citations = self._merge_unique(existing.citations, card.citations)
            existing.atom_ids = self._merge_unique(existing.atom_ids, card.atom_ids)
            if self._memory_card_section_priority(card.section) > self._memory_card_section_priority(existing.section):
                existing.section = str(card.section or "").strip().lower()
            existing.pack_rank = min(int(existing.pack_rank), int(card.pack_rank))
            if str(card.trust_tier or "").strip().lower() == "published":
                existing.memory_layer = str(card.memory_layer or "").strip().lower()
                existing.trust_tier = str(card.trust_tier or "").strip().lower()
            if str(existing.conflict_state or "active").strip().lower() == "active":
                existing.conflict_state = str(card.conflict_state or existing.conflict_state or "active").strip().lower()
            existing.conflict_visible = bool(existing.conflict_visible or card.conflict_visible)
            existing.conflict_winner = bool(existing.conflict_winner or card.conflict_winner)
            existing.conflict_with = self._merge_unique(existing.conflict_with, card.conflict_with)

        limit = max(1, int(max_cards))
        if len(merged) <= limit:
            return merged

        contradictory_ids = [id(item) for item in merged if item.contradiction]
        if not contradictory_ids:
            return merged[:limit]
        if len(contradictory_ids) >= limit:
            keep_ids = set(contradictory_ids[:limit])
        else:
            keep_ids = set(contradictory_ids)
            remaining = limit - len(keep_ids)
            for item in merged:
                item_id = id(item)
                if item_id in keep_ids:
                    continue
                keep_ids.add(item_id)
                remaining -= 1
                if remaining <= 0:
                    break

        limited: list[MemoryCard] = []
        for item in merged:
            if id(item) not in keep_ids:
                continue
            limited.append(item)
            if len(limited) >= limit:
                break
        return limited

    def _merge_card_summary(self, left: str, right: str, *, max_chars: int) -> str:
        left_clean = self._compact_text(left, max_chars=max_chars)
        right_clean = self._compact_text(right, max_chars=max_chars)
        if not left_clean:
            return right_clean
        if not right_clean:
            return left_clean
        if right_clean.lower() in left_clean.lower():
            return left_clean
        if left_clean.lower() in right_clean.lower():
            return right_clean
        return self._compact_text(f"{left_clean} | {right_clean}", max_chars=max_chars)

    def _merge_unique(self, base: list[str], extra: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in list(base) + list(extra):
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    def _item_to_card(
        self,
        item: MemoryPackItem,
        *,
        contradiction: bool,
        section: str,
        pack_rank: int,
    ) -> MemoryCard | None:
        citations = self._citations_for_item(item)
        if not citations:
            return None
        summary = self._compact_text(item.canonical_text, max_chars=180)
        raw_source = str(getattr(item, "raw_context_text", "") or "")
        raw_excerpt = self._truncate_text_preserving_spacing(raw_source, max_chars=320) if raw_source else self._compact_text(item.canonical_text, max_chars=320)
        kind = self._card_kind(item.atom_id)
        summary_abstractive = self._abstractive_card_summary(item.canonical_text, kind=kind)
        contradiction_flag = bool(contradiction or str(item.conflict_state).lower() != "active")
        initial_conflict_with = [f"card_{item_id}" for item_id in list(getattr(item, "conflict_with_ids", []) or []) if str(item_id).strip()]
        return MemoryCard(
            card_id=f"card_{item.atom_id}",
            kind=kind,
            summary=summary,
            confidence=_clamp01(item.confidence),
            contradiction=contradiction_flag,
            citations=citations,
            atom_ids=[item.atom_id],
            cluster_size=1,
            summary_abstractive=summary_abstractive,
            raw_excerpt=raw_excerpt,
            section=str(section or "").strip().lower(),
            pack_rank=max(0, int(pack_rank)),
            memory_layer=str(getattr(item, "memory_layer", "") or "").strip().lower(),
            trust_tier=str(getattr(item, "trust_tier", "") or "").strip().lower(),
            conflict_state=str(getattr(item, "conflict_state", "active") or "active").strip().lower(),
            conflict_visible=bool(initial_conflict_with),
            conflict_winner=False,
            conflict_with=initial_conflict_with,
        )

    def _abstractive_card_summary(self, text: str, *, kind: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return "Memory summary: no content available."
        clause = self._evidence_best_clause(raw)
        normalized = self._normalize_summary_sentence(clause)
        if self._summary_sentence_is_fragmentary(normalized):
            return self._fallback_abstractive_card_summary(raw, kind=kind)
        prefix = self._card_summary_prefix(kind)
        return self._compact_text(f"{prefix} {normalized}", max_chars=180)

    @staticmethod
    def _card_summary_prefix(kind: str) -> str:
        prefix_map = {
            "event_card": "Event summary:",
            "relationship_card": "Relationship summary:",
            "fact_card": "Memory summary:",
        }
        return prefix_map.get(str(kind or "").strip().lower(), "Memory summary:")

    def _normalize_summary_sentence(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip("`\"'[]{}()|- ")
        if not cleaned:
            return ""
        cleaned = self._compact_text(cleaned, max_chars=150)
        if not cleaned:
            return ""
        if cleaned.isupper() and len(cleaned) <= 24:
            cleaned = cleaned.lower()
        cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else ""
        if cleaned and cleaned[-1] not in ".!?":
            cleaned = f"{cleaned}."
        return cleaned

    def _summary_sentence_is_fragmentary(self, text: str) -> bool:
        cleaned = str(text or "").strip()
        if not cleaned:
            return True
        tokens = _tokenize(cleaned)
        if len(tokens) < 4:
            return True
        informative = self._ordered_informative_tokens(cleaned)
        if len(informative) < 2:
            return True
        alpha_chars = sum(1 for ch in cleaned if ch.isalpha())
        if alpha_chars < max(8, len(cleaned) // 3):
            return True
        return False

    def _fallback_abstractive_card_summary(self, text: str, *, kind: str) -> str:
        prefix = self._card_summary_prefix(kind)
        if len(str(text or "").strip()) < 24:
            return f"{prefix} Limited source detail."
        informative = self._ordered_informative_tokens(text)
        if len(informative) >= 3:
            lead = ", ".join(informative[:3])
            return self._compact_text(f"{prefix} About {lead}.", max_chars=180)
        return f"{prefix} Limited source detail."

    def _card_kind(self, atom_id: str) -> str:
        if str(atom_id).startswith("episode_card:"):
            return "event_card"
        try:
            atom = self.retriever.store.get_atom(atom_id)
            atom_type = str(getattr(getattr(atom, "atom_type", None), "value", "")).strip().lower()
        except Exception:
            atom_type = ""
        if atom_type == "episode":
            return "event_card"
        if atom_type == "relational":
            return "relationship_card"
        return "fact_card"

    def _citations_for_item(self, item: MemoryPackItem) -> list[str]:
        out: list[str] = []
        for ref in list(item.source_refs):
            source_id = str(getattr(ref, "source_id", "")).strip()
            message_id = str(getattr(ref, "message_id", "")).strip()
            if not source_id:
                continue
            out.append(f"{source_id}#{message_id or 'unknown_message'}")
        # Preserve order while deduping.
        deduped: list[str] = []
        seen: set[str] = set()
        for item_id in out:
            if item_id in seen:
                continue
            seen.add(item_id)
            deduped.append(item_id)
        return deduped

    def _compact_text(self, text: str, *, max_chars: int) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return f"{cleaned[: max_chars - 3].rstrip()}..."

    def _truncate_text_preserving_spacing(self, text: str, *, max_chars: int) -> str:
        raw = str(text or "")
        if len(raw) <= max_chars:
            return raw
        return f"{raw[: max_chars - 3].rstrip()}..."

    def _card_to_dict(self, card: MemoryCard) -> dict[str, Any]:
        payload = {
            "card_id": card.card_id,
            "kind": card.kind,
            "summary": card.summary,
            "confidence": card.confidence,
            "contradiction": card.contradiction,
            "citations": list(card.citations),
            "atom_ids": list(card.atom_ids),
            "section": str(card.section or "").strip().lower(),
            "pack_rank": int(card.pack_rank),
        }
        memory_layer = str(card.memory_layer or "").strip().lower()
        trust_tier = str(card.trust_tier or "").strip().lower()
        conflict_state = str(card.conflict_state or "active").strip().lower()
        if memory_layer and memory_layer != "atom":
            payload["memory_layer"] = memory_layer
        if trust_tier and trust_tier != "evidence":
            payload["trust_tier"] = trust_tier
        if conflict_state and conflict_state != "active":
            payload["conflict_state"] = conflict_state
        if bool(card.conflict_visible):
            payload["conflict_visible"] = True
            payload["conflict_winner"] = bool(card.conflict_winner)
            payload["conflict_with"] = list(card.conflict_with)
        summary_abstractive = str(card.summary_abstractive or "").strip()
        if summary_abstractive and summary_abstractive != str(card.summary or "").strip():
            payload["summary_abstractive"] = summary_abstractive
        raw_excerpt = str(card.raw_excerpt or "").strip()
        if raw_excerpt and raw_excerpt != str(card.summary or "").strip():
            payload["raw_excerpt"] = raw_excerpt
        if int(card.cluster_size) > 1:
            payload["cluster_size"] = int(card.cluster_size)
        return payload

    def _compact_card_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        citations = [str(item).strip() for item in list(payload.get("citations") or []) if str(item).strip()]
        summary_text = str(payload.get("summary_abstractive") or payload.get("summary") or "")
        return {
            "card_id": payload.get("card_id"),
            "kind": payload.get("kind"),
            "summary": self._compact_text(summary_text, max_chars=180),
            "confidence": payload.get("confidence"),
            "citation_count": len(citations),
            "top_citation": citations[0] if citations else "",
            "memory_layer": str(payload.get("memory_layer") or "").strip().lower(),
            "trust_tier": str(payload.get("trust_tier") or "").strip().lower(),
            "conflict_state": str(payload.get("conflict_state") or "active").strip().lower(),
            "conflict_visible": bool(payload.get("conflict_visible")),
            "conflict_winner": bool(payload.get("conflict_winner")),
            "conflict_with_count": len(list(payload.get("conflict_with") or [])),
        }

    def _rank_memory_cards_for_response(
        self,
        *,
        user_text: str,
        memory_cards: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if len(memory_cards) <= 1:
            return list(memory_cards)
        normalized = str(user_text or "").strip().lower()
        query_tokens = set(self._ordered_informative_tokens(normalized))
        focus_tokens = set(self._query_focus_candidates(text=user_text, normalized=normalized))
        identity_query = self._is_identity_relationship_query(normalized)
        event_query = normalized.startswith("what happened") or normalized.startswith("tell me about")
        person_focus_query = bool(focus_tokens) and (
            identity_query
            or event_query
            or normalized.startswith("why does ")
            or normalized.startswith("why did ")
            or normalized.startswith("why is ")
        )

        def _score(card: dict[str, Any]) -> tuple[float, float, float, str]:
            summary = str(card.get("summary_abstractive") or card.get("summary") or "").strip()
            raw_excerpt = str(card.get("raw_excerpt") or card.get("summary") or "").strip()
            summary_tokens = set(self._ordered_informative_tokens(summary))
            raw_tokens = set(self._ordered_informative_tokens(raw_excerpt))
            overlap = len(query_tokens.intersection(summary_tokens)) / max(1, len(query_tokens)) if query_tokens else 0.0
            focus_overlap = len(focus_tokens.intersection(summary_tokens.union(raw_tokens)))
            lead_tokens = self._ordered_informative_tokens(raw_excerpt)[:8]
            lead_focus = len(focus_tokens.intersection(lead_tokens))
            confidence = float(card.get("confidence") or 0.0)
            kind = str(card.get("kind") or "").strip().lower()
            section = str(card.get("section") or "").strip().lower()
            pack_rank = max(0, int(card.get("pack_rank") or 0))
            kind_boost = 0.0
            if identity_query and kind == "relationship_card":
                kind_boost = 0.14
            elif event_query and kind == "event_card":
                kind_boost = 0.06
            section_boost = 0.0
            if identity_query:
                section_boost = {
                    "core": 0.16,
                    "context": 0.08,
                    "continuity": -0.06,
                    "conflict": -0.10,
                }.get(section, 0.0)
            elif event_query:
                section_boost = {
                    "core": 0.10,
                    "context": 0.04,
                    "continuity": -0.02,
                    "conflict": -0.08,
                }.get(section, 0.0)
            rank_boost = max(0.0, 0.10 - (0.015 * min(pack_rank, 6)))
            meta_penalty = 0.55 if self._looks_like_consumer_meta_instruction_text(summary) else 0.0
            meta_penalty += 0.45 if self._looks_like_consumer_meta_conversation_text(summary, user_text=user_text) else 0.0
            contradiction_penalty = 0.12 if bool(card.get("contradiction")) else 0.0
            authority_bonus = 0.0
            if bool(
                self.config.retrieval.derived_helpers.temporal_lift.enabled
                or self.config.retrieval.derived_helpers.update_family_resolver.enabled
            ):
                trust_tier = str(card.get("trust_tier") or "evidence").strip().lower()
                conflict_state = str(card.get("conflict_state") or "active").strip().lower()
                authority_bonus = {
                    "published": 0.08,
                    "evidence": 0.03,
                    "provisional": -0.03,
                    "proposal_pending": -0.08,
                }.get(trust_tier, 0.0)
                if bool(card.get("conflict_visible")) or bool(card.get("contradiction")):
                    authority_bonus *= 2.0
                authority_bonus -= {
                    "superseded": 0.10,
                    "conflicted": 0.04,
                }.get(conflict_state, 0.0)
            centrality_bonus = 0.0
            centrality_penalty = 0.0
            if person_focus_query and focus_tokens:
                focusable_tokens = summary_tokens.union(raw_tokens)
                focus_density = focus_overlap / max(1, len(focusable_tokens))
                centrality_bonus += min(0.24, 0.08 * focus_overlap + 0.10 * lead_focus + 0.70 * focus_density)
                non_focus_breadth = max(0, len(focusable_tokens.difference(focus_tokens)))
                if kind != "relationship_card" and lead_focus == 0 and focus_overlap <= 1:
                    centrality_penalty += min(0.22, 0.04 * max(0, non_focus_breadth - 4))
            score = overlap * 0.58 + min(0.26, 0.16 * focus_overlap) + confidence * 0.08 + kind_boost + section_boost + rank_boost
            score += centrality_bonus + authority_bonus
            score -= meta_penalty + contradiction_penalty + centrality_penalty
            return score, confidence, -float(pack_rank), summary.lower()

        ranked = list(memory_cards)
        ranked.sort(key=_score, reverse=True)
        return ranked

    def _annotate_memory_card_conflicts(
        self,
        *,
        user_text: str,
        memory_cards: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if len(memory_cards) <= 1:
            return list(memory_cards)
        normalized = str(user_text or "").strip().lower()
        query_tokens = set(self._ordered_informative_tokens(normalized))
        focus_tokens = set(self._query_focus_candidates(text=user_text, normalized=normalized))
        basis_tokens = focus_tokens or query_tokens
        if not basis_tokens:
            return list(memory_cards)

        def _card_tokens(card: dict[str, Any]) -> set[str]:
            summary = str(card.get("summary_abstractive") or card.get("summary") or "").strip()
            return set(self._ordered_informative_tokens(summary))

        annotated = [dict(card) for card in memory_cards]
        conflict_groups: list[list[int]] = []

        def _merge_into_groups(indices: list[int]) -> None:
            if len(indices) <= 1:
                return
            unique = sorted(set(indices))
            for group in conflict_groups:
                if any(index in group for index in unique):
                    for index in unique:
                        if index not in group:
                            group.append(index)
                    return
            conflict_groups.append(unique)

        card_index_by_id = {
            str(card.get("card_id") or ""): idx
            for idx, card in enumerate(annotated)
            if str(card.get("card_id") or "").strip()
        }
        for idx, card in enumerate(annotated):
            explicit_links = [
                card_index_by_id[item_id]
                for item_id in list(card.get("conflict_with") or [])
                if str(item_id or "").strip() in card_index_by_id
            ]
            if explicit_links:
                _merge_into_groups([idx] + explicit_links)

        for idx, card in enumerate(annotated):
            tier = str(card.get("trust_tier") or "").strip().lower()
            if tier not in {"published", "provisional"}:
                continue
            tokens = _card_tokens(card)
            basis_overlap = tokens.intersection(basis_tokens)
            if not basis_overlap:
                continue
            for jdx in range(idx + 1, len(annotated)):
                other = annotated[jdx]
                other_tier = str(other.get("trust_tier") or "").strip().lower()
                if other_tier not in {"published", "provisional"}:
                    continue
                other_tokens = _card_tokens(other)
                if not other_tokens.intersection(basis_tokens):
                    continue
                shared_basis = basis_overlap.intersection(other_tokens)
                if not shared_basis:
                    continue
                card_text = self._compact_text(str(card.get("summary") or ""), max_chars=220).lower()
                other_text = self._compact_text(str(other.get("summary") or ""), max_chars=220).lower()
                if card_text == other_text:
                    continue
                _merge_into_groups([idx, jdx])

        for group in conflict_groups:
            ordered = sorted(set(group))
            winner_idx = ordered[0]
            for idx in ordered:
                current = annotated[idx]
                others = [annotated[item]["card_id"] for item in ordered if item != idx]
                current["conflict_visible"] = True
                current["conflict_winner"] = idx == winner_idx
                current["conflict_with"] = others
        return annotated

    def _response_prefers_abstractive_summary(self, user_text: str) -> bool:
        normalized = str(user_text or "").strip().lower()
        if not normalized:
            return False
        identity_query = self._is_identity_relationship_query(normalized)
        named_person_event_query = normalized.startswith("what happened to ")
        if self._has_specific_recall_anchor(text=user_text, normalized=normalized) and not (
            identity_query or named_person_event_query
        ):
            return False
        if identity_query:
            return True
        if _NAMED_ENTITY_QUESTION_RE.search(str(user_text or "").strip()):
            return True
        return named_person_event_query

    def _response_card_text(self, card: dict[str, Any], *, user_text: str) -> str:
        normalized = str(user_text or "").strip().lower()
        if self._has_verbatim_session_recall_intent(text=user_text, normalized=normalized):
            raw_excerpt = str(card.get("raw_excerpt") or "")
            if raw_excerpt:
                return self._truncate_text_preserving_spacing(raw_excerpt, max_chars=320)
        if self._response_prefers_abstractive_summary(user_text):
            summary_abstractive = str(card.get("summary_abstractive") or "").strip()
            if summary_abstractive:
                return summary_abstractive
        return str(card.get("summary") or "").strip()

    def _remember_short_term(
        self,
        *,
        turn_id: str,
        user_text: str,
        response_text: str,
        session: SessionState | None = None,
    ) -> None:
        if not self.short_term_enabled:
            return
        active = session or self._ensure_session("default")
        created_at = _utc_now()
        entries = [("user", user_text), ("assistant", response_text)]
        with self._lock:
            for role, text in entries:
                cleaned = self._compact_text(str(text or "").strip(), max_chars=self.short_term_note_max_chars)
                if not cleaned:
                    continue
                self._note_seq += 1
                note = ShortTermNote(
                    note_id=f"stmn_{self._note_seq:07d}",
                    turn_id=turn_id,
                    role=role,
                    text=cleaned,
                    created_at=created_at,
                )
                if len(active.short_term) >= self.short_term_capacity:
                    self._evict_oldest_short_term_note(active)
                active.short_term.append(note)
            self._enforce_working_set_budget(active)
            active.updated_at = created_at

    def _compose_response(
        self,
        user_text: str,
        verification: VerificationResult,
        pack: MemoryPack,
        *,
        memory_cards: list[dict[str, Any]],
        memory_route: str,
    ) -> tuple[str, list[str]]:
        if verification.decision is VerificationDecision.NO_MEMORY or memory_route == "none":
            # Routine/non-memory turns should sound like normal chat and must not echo test-style prompts.
            return (self._routine_reply(user_text), [])
        citations = self._rank_citations(
            verification=verification,
            pack=pack,
        )

        if verification.decision is VerificationDecision.PASS:
            verbatim_intent = self._has_verbatim_session_recall_intent(text=user_text, normalized=str(user_text or "").strip().lower())
            lead = ""
            lead_sources: set[str] = set()
            support = ""
            support_sources: set[str] = set()
            if memory_cards:
                ranked_cards = self._rank_memory_cards_for_response(user_text=user_text, memory_cards=memory_cards)
                lead = self._response_card_text(ranked_cards[0], user_text=user_text)
                lead_sources = self._card_source_ids(ranked_cards[0])
                if len(ranked_cards) > 1:
                    support = self._response_card_text(ranked_cards[1], user_text=user_text)
                    support_sources = self._card_source_ids(ranked_cards[1])
            elif pack.core:
                lead = str(pack.core[0].canonical_text or "").strip()
                lead_sources = self._pack_item_source_ids(pack.core[0])
                if len(pack.core) > 1:
                    support = str(pack.core[1].canonical_text or "").strip()
                    support_sources = self._pack_item_source_ids(pack.core[1])

            mixing_options = _mixing_options_from_text(user_text)
            if mixing_options is not None:
                left_option, right_option = mixing_options
                evidence_segments: list[str] = []
                if lead:
                    evidence_segments.append(lead)
                if support:
                    evidence_segments.append(support)
                for item in list(pack.core or [])[:2]:
                    text = str(getattr(item, "canonical_text", "") or "").strip()
                    if text:
                        evidence_segments.append(text)
                evidence_text = " ".join(evidence_segments).strip()
                left_score = _option_support_score(left_option, evidence_text)
                right_score = _option_support_score(right_option, evidence_text)
                if (left_score > 0.0 or right_score > 0.0) and abs(left_score - right_score) >= 0.05:
                    chosen = left_option if left_score > right_score else right_option
                    rejected = right_option if chosen == left_option else left_option
                    chosen_compact = self._compact_text(chosen, max_chars=96)
                    rejected_compact = self._compact_text(rejected, max_chars=96)
                    parts = [f"I can support \"{chosen_compact}\", not \"{rejected_compact}\"."]
                    if lead:
                        lead_text = self._truncate_text_preserving_spacing(lead, max_chars=260) if verbatim_intent else self._compact_text(lead, max_chars=260)
                        parts.append(lead_text)
                    if support and self._allow_related_context(
                        user_text=user_text,
                        lead_text=lead,
                        support_text=support,
                        lead_sources=lead_sources,
                        support_sources=support_sources,
                        ranked_citations=citations,
                    ):
                        support_text = self._truncate_text_preserving_spacing(support, max_chars=220) if verbatim_intent else self._compact_text(support, max_chars=220)
                        parts.append(f"Related context: {support_text}")
                    return "\n".join(parts), citations

            if lead:
                lead_text = self._truncate_text_preserving_spacing(lead, max_chars=260) if verbatim_intent else self._compact_text(lead, max_chars=260)
                parts = [lead_text]
            else:
                parts = ["I can cite a related memory, but it is too sparse to restate cleanly."]
            if support and self._allow_related_context(
                user_text=user_text,
                lead_text=lead,
                support_text=support,
                lead_sources=lead_sources,
                support_sources=support_sources,
                ranked_citations=citations,
            ):
                support_text = self._truncate_text_preserving_spacing(support, max_chars=220) if verbatim_intent else self._compact_text(support, max_chars=220)
                parts.append(f"Related context: {support_text}")
            return "\n".join(parts), citations

        if verification.decision is VerificationDecision.CLARIFY:
            lines = [
                "I found conflicting supported memories, so I am not asserting one as final.",
                "Please clarify which timeline you want me to prioritize.",
            ]
            return "\n".join(lines), citations

        if memory_route == "stm_only":
            return (
                "I checked recent thread context but do not have enough supported detail yet. "
                "Share one more specific detail and I can continue safely.",
                citations,
            )

        return (
            "I cannot support a confident memory claim from the current evidence pack. "
            "Please provide another detail so I can retrieve stronger citations.",
            citations,
        )

    @staticmethod
    def _routine_reply(user_text: str) -> str:
        text = str(user_text or "").strip()
        lower = text.lower()
        if "how are you" in lower:
            return "I'm here and ready. How are you?"
        if "joke" in lower and "hear" in lower:
            return "Sure, go ahead."
        if lower.startswith(("hey", "hi", "hello")):
            return "Hey. What's up?"
        if "what's up" in lower or "whats up" in lower:
            return "Not much. What do you want to do next?"
        return "Okay."

    def _card_source_ids(self, payload: dict[str, Any]) -> set[str]:
        citations = [str(item).strip() for item in list(payload.get("citations") or []) if str(item).strip()]
        return {self._normalize_source_id(item) for item in citations if self._normalize_source_id(item)}

    @staticmethod
    def _pack_item_source_ids(item: MemoryPackItem) -> set[str]:
        out: set[str] = set()
        for ref in list(getattr(item, "source_refs", []) or []):
            source_id = str(getattr(ref, "source_id", "") or "").strip()
            if source_id:
                out.add(source_id)
        return out

    @staticmethod
    def _allow_related_context(
        *,
        user_text: str,
        lead_text: str,
        support_text: str,
        lead_sources: set[str],
        support_sources: set[str],
        ranked_citations: list[str],
    ) -> bool:
        # Hard block empty strings.
        if not str(lead_text or "").strip() or not str(support_text or "").strip():
            return False
        # Prefer provenance overlap: if the "support" comes from different sources than the lead,
        # it is likely to be unrelated context bleed.
        if lead_sources and support_sources and not lead_sources.intersection(support_sources):
            # Do not allow unrelated context solely because it appears in ranked citations.
            # If the sources are disjoint, require clear lexical overlap below.
            pass
        # If we cannot establish provenance overlap, fall back to a small overlap check over informative tokens
        # (exclude generic prompt words like "remember/about/when" so unrelated cards don't pass on boilerplate).
        user_tokens = {tok for tok in _tokenize(str(user_text or "")) if len(tok) >= 4 and tok not in _INFO_STOPWORDS}
        support_tokens = {tok for tok in _tokenize(str(support_text or "")) if len(tok) >= 4 and tok not in _INFO_STOPWORDS}
        if not user_tokens or not support_tokens:
            return False
        overlap = len(user_tokens.intersection(support_tokens))
        return overlap >= 2

    @staticmethod
    def _normalize_source_id(source_id: str) -> str:
        clean = str(source_id or "").strip()
        if not clean:
            return ""
        if "#" in clean:
            clean = clean.split("#", 1)[0].strip()
        if "?" in clean:
            clean = clean.split("?", 1)[0].strip()
        return clean

    def _rank_citations(
        self,
        *,
        verification: VerificationResult,
        pack: MemoryPack,
    ) -> list[str]:
        weight_by_citation: dict[str, float] = {}
        tokens_by_source: dict[str, set[str]] = {}

        def _add_citation(citation: str, weight: float) -> None:
            raw = str(citation or "").strip()
            if not raw:
                return
            source_id = self._normalize_source_id(raw)
            if not source_id:
                return
            if "#" in raw:
                message_id = str(raw.split("#", 1)[1] or "").strip() or "unknown_message"
            else:
                message_id = "unknown_message"
            token = f"{source_id}#{message_id}"
            weight_by_citation[token] = weight_by_citation.get(token, 0.0) + float(weight)
            tokens_by_source.setdefault(source_id, set()).add(token)

        for item in list(pack.core):
            for ref in list(item.source_refs):
                _add_citation(f"{str(getattr(ref, 'source_id', '')).strip()}#{str(getattr(ref, 'message_id', '')).strip()}", 3.0)
        for item in list(pack.context):
            for ref in list(item.source_refs):
                _add_citation(f"{str(getattr(ref, 'source_id', '')).strip()}#{str(getattr(ref, 'message_id', '')).strip()}", 2.0)
        for item in list(pack.continuity) + list(pack.conflict):
            for ref in list(item.source_refs):
                _add_citation(f"{str(getattr(ref, 'source_id', '')).strip()}#{str(getattr(ref, 'message_id', '')).strip()}", 1.0)

        for check in list(verification.checks):
            if not bool(getattr(check, "supported", False)):
                continue
            confidence = float(getattr(check, "confidence", 0.0) or 0.0)
            for citation in list(getattr(check, "citations", []) or []):
                raw = str(citation or "").strip()
                if not raw:
                    continue
                if "#" in raw:
                    _add_citation(raw, 4.0 + confidence)
                    continue
                source_id = self._normalize_source_id(raw)
                if not source_id:
                    continue
                mapped = sorted(tokens_by_source.get(source_id) or [])
                if mapped:
                    for token in mapped:
                        _add_citation(token, 4.0 + confidence)
                else:
                    _add_citation(f"{source_id}#unknown_message", 3.0 + confidence)

        ranked = sorted(weight_by_citation.items(), key=lambda item: (item[1], item[0]), reverse=True)
        return [token for token, _weight in ranked[:12]]

    def _enforce_direct_citation_gate(
        self,
        verification: VerificationResult,
        pack: MemoryPack,
        *,
        memory_route: str,
    ) -> VerificationResult:
        if verification.decision is not VerificationDecision.PASS:
            return verification
        if memory_route == "none":
            return verification
        supported_sources = {
            self._normalize_source_id(str(source))
            for check in verification.checks
            if bool(getattr(check, "supported", False))
            for source in list(getattr(check, "citations", []) or [])
            if self._normalize_source_id(str(source))
        }
        support_sources = {
            self._normalize_source_id(str(getattr(ref, "source_id", "")))
            for item in list(pack.core) + list(pack.context) + list(pack.conflict)
            for ref in list(item.source_refs)
            if self._normalize_source_id(str(getattr(ref, "source_id", "")))
        }
        if not support_sources:
            return self._force_abstain(
                verification,
                reason="DIRECT_CITATION_REQUIRED",
                confidence=0.0,
            )
        if supported_sources and support_sources.intersection(supported_sources):
            return verification
        if supported_sources:
            return self._force_abstain(
                verification,
                reason="DIRECT_CITATION_REQUIRED",
                confidence=0.0,
            )
        return self._force_abstain(
            verification,
            reason="DIRECT_CITATION_REQUIRED",
            confidence=0.0,
        )

    def _cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_cost_per_mtok + output_tokens * self.output_cost_per_mtok) / 1_000_000.0

    def _enqueue_writeback(
        self,
        trace: TurnTrace,
        verification: VerificationResult,
        pack: MemoryPack,
    ) -> WritebackEvent:
        if self._executor is None:
            raise RuntimeError("writeback executor is disabled")
        event = WritebackEvent(
            event_id=f"wb_{uuid4().hex}",
            turn_id=trace.turn_id,
            status="queued",
            created_at=_utc_now(),
        )
        with self._lock:
            self._writebacks[event.event_id] = event
        future = self._executor.submit(self._run_writeback, event.event_id, verification, pack)
        with self._lock:
            self._writeback_futures[event.event_id] = future
        future.add_done_callback(lambda fut, event_id=event.event_id: self._on_writeback_future_done(event_id, fut))
        return event

    def _on_writeback_future_done(self, event_id: str, future: Future[Any]) -> None:
        with self._lock:
            self._writeback_futures.pop(event_id, None)
            event = self._writebacks.get(event_id)
            if event is None:
                return
            if future.cancelled() and event.status in {"queued", "running"}:
                event.status = "failed"
                event.error = "writeback cancelled"
                event.processed_at = _utc_now()
                return
            if event.status in {"done", "failed"}:
                return

        exc = future.exception()
        if exc is None:
            return
        with self._lock:
            event = self._writebacks.get(event_id)
            if event is not None and event.status not in {"done", "failed"}:
                event.status = "failed"
                event.error = str(exc)
                event.processed_at = _utc_now()

    def _run_writeback(self, event_id: str, verification: VerificationResult, pack: MemoryPack) -> None:
        try:
            with self._lock:
                writeback_event = self._writebacks[event_id]
                writeback_event.status = "running"
            core = [
                item
                for item in pack.core
                if not item.atom_id.startswith(("stm_", "prov_", "episode_card:"))
            ][:2]
            recognized = verification.decision is VerificationDecision.PASS
            recorder = getattr(self.retriever.store, "record_recognition_event", None)
            for item in core:
                recognition_event = self.continuity_store.telemetry.record(
                    atom_id=item.atom_id,
                    recognized=recognized,
                    score=item.confidence,
                    query_text="runtime_writeback",
                )
                if callable(recorder):
                    recorder(
                        atom_id=item.atom_id,
                        recognized=recognized,
                        score=item.confidence,
                        query_text="runtime_writeback",
                        timestamp=recognition_event.timestamp,
                    )
            self._refresh_recognition_stats()
            with self._lock:
                writeback_event = self._writebacks[event_id]
                writeback_event.status = "done"
                writeback_event.processed_at = _utc_now()
        except Exception as exc:
            with self._lock:
                event = self._writebacks[event_id]
                event.status = "failed"
                event.error = str(exc)
                event.processed_at = _utc_now()

    def _hydrate_recognition_from_store(self) -> None:
        reader = getattr(self.retriever.store, "list_recognition_events", None)
        if not callable(reader):
            return
        try:
            events = list(reader(limit=5000))
        except Exception:
            return
        if not events:
            return
        loaded = []
        for event in events:
            loaded.append(
                self.continuity_store.telemetry.record(
                    atom_id=str(getattr(event, "atom_id", "")),
                    recognized=bool(getattr(event, "recognized", False)),
                    score=float(getattr(event, "score", 0.0)),
                    query_text=str(getattr(event, "query_text", "")),
                    timestamp=getattr(event, "timestamp", None),
                )
            )
        if loaded:
            self._refresh_recognition_stats()

    def _refresh_recognition_stats(self) -> None:
        reader = getattr(self.retriever.store, "recognition_stats", None)
        if callable(reader):
            try:
                stats = dict(reader())
            except Exception:
                stats = {}
        else:
            events = self.continuity_store.telemetry.events()
            total = len(events)
            recognized = sum(1 for event in events if event.recognized)
            stats = {
                "events": float(total),
                "recognized_rate": (recognized / total) if total else 0.0,
            }
        with self._lock:
            self._stats.recognition_events = int(float(stats.get("events", 0.0)))
            self._stats.recognition_rate = float(stats.get("recognized_rate", 0.0))

    def _check_to_dict(self, item: Any) -> dict[str, Any]:
        return {
            "claim": item.claim,
            "supported": item.supported,
            "confidence": item.confidence,
            "citations": list(item.citations),
            "reason": item.reason,
        }

    def _p95(self, values: list[float]) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = max(int(round(0.95 * (len(sorted_values) - 1))), 0)
        return sorted_values[index]
