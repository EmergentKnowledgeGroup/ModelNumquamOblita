from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from ..contracts import MemoryPack, MemoryPackItem

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_DERIVED_TERMS = ("constellation", "narrative arc", "dynamic pattern", "shared language")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / max(1, len(left))


class VerificationDecision(str, Enum):
    PASS = "PASS"
    CLARIFY = "CLARIFY"
    ABSTAIN = "ABSTAIN"
    NO_MEMORY = "NO_MEMORY"


@dataclass(slots=True)
class ClaimCheck:
    claim: str
    supported: bool
    confidence: float
    citations: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass(slots=True)
class VerificationResult:
    decision: VerificationDecision
    checks: list[ClaimCheck]
    unsupported_claims: list[str]
    needs_uncertainty: bool


class ClaimVerifier:
    """Claim-level verifier that fails closed on unsupported memory claims."""

    def __init__(self, *, support_threshold: float = 0.40, conflict_threshold: float = 0.33) -> None:
        self.support_threshold = support_threshold
        self.conflict_threshold = conflict_threshold

    def verify(
        self,
        claims: list[str],
        memory_pack: MemoryPack,
        *,
        high_risk: bool = False,
    ) -> VerificationResult:
        checks: list[ClaimCheck] = []
        unsupported: list[str] = []
        needs_uncertainty = False
        threshold = self.support_threshold + (0.08 if high_risk else 0.0)

        for claim in claims:
            text = str(claim or "").strip()
            if not text:
                continue
            check = self._verify_one(text, memory_pack, threshold=threshold)
            checks.append(check)
            if not check.supported:
                unsupported.append(text)
            if check.reason == "UNRESOLVED_CONFLICT":
                needs_uncertainty = True

        if unsupported:
            decision = VerificationDecision.ABSTAIN
        elif needs_uncertainty:
            decision = VerificationDecision.CLARIFY
        else:
            decision = VerificationDecision.PASS
        return VerificationResult(
            decision=decision,
            checks=checks,
            unsupported_claims=unsupported,
            needs_uncertainty=needs_uncertainty,
        )

    def _verify_one(self, claim: str, pack: MemoryPack, *, threshold: float) -> ClaimCheck:
        claim_tokens = _tokenize(claim)
        if not claim_tokens:
            return ClaimCheck(claim=claim, supported=False, confidence=0.0, reason="EMPTY_CLAIM")

        core_context = pack.core + pack.context
        conflict = pack.conflict
        continuity = pack.continuity

        core_best = self._best_match(claim_tokens, core_context)
        conflict_best = self._best_match(claim_tokens, conflict)
        continuity_best = self._best_match(claim_tokens, continuity)
        contains_derived_term = any(term in claim.lower() for term in _DERIVED_TERMS)

        if contains_derived_term and core_best[1] < threshold and conflict_best[1] < threshold:
            derived_support_threshold = max(0.25, threshold * 0.70)
            if continuity_best[1] >= derived_support_threshold:
                return ClaimCheck(
                    claim=claim,
                    supported=False,
                    confidence=continuity_best[1],
                    citations=self._citations(continuity_best[0]),
                    reason="DERIVED_ONLY_EVIDENCE",
                )

        if conflict_best[1] >= self.conflict_threshold:
            competing = self._count_matches_over_threshold(claim_tokens, conflict, self.conflict_threshold)
            if competing >= 2:
                return ClaimCheck(
                    claim=claim,
                    supported=True,
                    confidence=conflict_best[1],
                    citations=self._citations(conflict_best[0]),
                    reason="UNRESOLVED_CONFLICT",
                )

        if core_best[1] >= threshold:
            return ClaimCheck(
                claim=claim,
                supported=True,
                confidence=core_best[1],
                citations=self._citations(core_best[0]),
                reason="SUPPORTED",
            )
        if conflict_best[1] >= threshold:
            competing = self._count_matches_over_threshold(claim_tokens, conflict, threshold)
            if competing >= 2:
                return ClaimCheck(
                    claim=claim,
                    supported=True,
                    confidence=conflict_best[1],
                    citations=self._citations(conflict_best[0]),
                    reason="UNRESOLVED_CONFLICT",
                )
            return ClaimCheck(
                claim=claim,
                supported=False,
                confidence=conflict_best[1],
                citations=self._citations(conflict_best[0]),
                reason="INCOMPLETE_CONFLICT_COVERAGE",
            )
        return ClaimCheck(claim=claim, supported=False, confidence=max(core_best[1], conflict_best[1]), reason="UNSUPPORTED")

    def _best_match(self, claim_tokens: set[str], items: list[MemoryPackItem]) -> tuple[MemoryPackItem | None, float]:
        best_item: MemoryPackItem | None = None
        best_score = 0.0
        for item in items:
            score = _overlap_score(claim_tokens, _tokenize(item.canonical_text))
            if score > best_score:
                best_score = score
                best_item = item
        return best_item, best_score

    def _count_matches_over_threshold(self, claim_tokens: set[str], items: list[MemoryPackItem], threshold: float) -> int:
        return sum(1 for item in items if _overlap_score(claim_tokens, _tokenize(item.canonical_text)) >= threshold)

    def _citations(self, item: MemoryPackItem | None) -> list[str]:
        if item is None:
            return []
        return sorted({ref.source_id for ref in item.source_refs if ref.source_id})
