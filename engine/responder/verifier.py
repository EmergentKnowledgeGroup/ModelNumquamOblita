from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping


_CITATION_TOKEN_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}#[0-9A-Za-z_-]+",
    re.IGNORECASE,
)

CANONICAL_ABSTAIN_PHRASE = "I don't have that memory."

_ABSTAIN_MARKERS = (
    "i don't remember",
    "i do not remember",
    "i can't remember",
    "i cannot remember",
    "i don't have that memory",
    "i do not have that memory",
    "i can't find",
    "i cannot find",
    "i don't have enough",
    "i do not have enough",
    "not enough detail",
    "not enough evidence",
)

_ABSTAIN_REGEXES = (
    re.compile(r"\b(?:i|we)\s+(?:do not|don't|cannot|can't)\s+(?:remember|recall)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:i|we)\s+(?:do not|don't|cannot|can't)\s+(?:have|find|access)\b[^.?!\n]{0,96}\b"
        r"(?:memory|memories|evidence|detail|details|record|records|context|information)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnot enough (?:detail|details|evidence|context|information)\b", re.IGNORECASE),
)

_SOURCE_LINE_RE = re.compile(r"^\s*\[\d+\]\s*source\s*:\s*.+$", re.IGNORECASE)
_SOURCE_PAREN_RE = re.compile(
    r"\(\s*\*?\s*source\s*:\s*[^)]+\)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class VerifiedReply:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    found_citations: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    inferred_decision: str = ""


def _evidence_citations(package: Mapping[str, Any]) -> set[str]:
    citations: set[str] = set()
    evidence = package.get("ltm_evidence")
    if not isinstance(evidence, list):
        return citations
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        for raw in list(item.get("citations") or []):
            token = str(raw or "").strip()
            if token:
                citations.add(token)
    return citations


def _service_decision(package: Mapping[str, Any]) -> str:
    verdict = package.get("service_verdict")
    if isinstance(verdict, Mapping):
        value = str(verdict.get("decision") or "").strip().upper()
        if value:
            return value
    return ""


def _service_citations(package: Mapping[str, Any]) -> set[str]:
    verdict = package.get("service_verdict")
    if not isinstance(verdict, Mapping):
        return set()
    citations = verdict.get("citations")
    if not isinstance(citations, list):
        return set()
    return {str(item).strip() for item in citations if str(item).strip()}


def _citations_visible(package: Mapping[str, Any]) -> bool:
    guidance = package.get("responder_guidance")
    if isinstance(guidance, Mapping):
        value = guidance.get("render_citations")
        if isinstance(value, bool):
            return bool(value)
    # Backward compatible strict default for packages without explicit guidance.
    return True


def _normalize_text(text: str) -> str:
    lowered = str(text or "").lower()
    lowered = lowered.replace("’", "'").replace("‘", "'").replace("`", "'")
    lowered = lowered.replace("“", '"').replace("”", '"')
    return " ".join(lowered.split()).strip()


def _contains_abstain(text: str) -> bool:
    normalized = _normalize_text(text)
    if any(marker in normalized for marker in _ABSTAIN_MARKERS):
        return True
    return any(pattern.search(normalized) for pattern in _ABSTAIN_REGEXES)


def _strip_hidden_citation_artifacts(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return ""
    cleaned = _CITATION_TOKEN_RE.sub("", cleaned)
    cleaned = _SOURCE_PAREN_RE.sub("", cleaned)
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = str(raw or "")
        if _SOURCE_LINE_RE.match(line):
            continue
        line = re.sub(r"\[\d+\]", "", line)
        lines.append(line.rstrip())
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def enforce_reply_contract(package: Mapping[str, Any], reply_text: str) -> str:
    text = str(reply_text or "").strip()
    if not _citations_visible(package):
        text = _strip_hidden_citation_artifacts(text)
    if _service_decision(package) != "ABSTAIN":
        return text
    return CANONICAL_ABSTAIN_PHRASE


def verify_reply_against_package(package: Mapping[str, Any], reply_text: str) -> VerifiedReply:
    text = str(reply_text or "").strip()
    if not text:
        return VerifiedReply(ok=False, reasons=["empty_reply"])

    allowed = _evidence_citations(package)
    service_citations = _service_citations(package)
    citations_visible = _citations_visible(package)
    found = sorted([token for token in allowed if token in text])
    all_tokens = set(_CITATION_TOKEN_RE.findall(text))
    unknown = sorted([token for token in all_tokens if token not in allowed])

    decision = _service_decision(package)
    inferred = ""
    reasons: list[str] = []
    ok = True

    # Inference is decision-aware: question marks can appear in routine chat and should not
    # automatically imply CLARIFY unless the service verdict is CLARIFY.
    if found:
        inferred = "PASS"
    elif decision == "PASS" and not citations_visible:
        inferred = "ABSTAIN" if _contains_abstain(text) else "PASS"
    elif decision == "CLARIFY":
        inferred = "CLARIFY" if "?" in text else "NO_MEMORY"
    elif decision == "ABSTAIN":
        inferred = "ABSTAIN" if _contains_abstain(text) else "NO_MEMORY"
    elif decision == "NO_MEMORY":
        inferred = "NO_MEMORY"
    elif _contains_abstain(text):
        inferred = "ABSTAIN"
    elif "?" in text:
        inferred = "CLARIFY"
    else:
        inferred = "NO_MEMORY"

    if unknown:
        ok = False
        reasons.append("unknown_citations_present")

    if decision in {"PASS"}:
        if _contains_abstain(text):
            ok = False
            reasons.append("pass_response_abstained")
        if citations_visible:
            if not found:
                ok = False
                reasons.append("missing_citations_for_pass")
        else:
            if not service_citations and not allowed:
                ok = False
                reasons.append("missing_internal_citations_for_pass")
    elif decision in {"ABSTAIN", "NO_MEMORY"}:
        if found:
            ok = False
            reasons.append("citations_present_on_abstain")
        if decision == "ABSTAIN" and not _contains_abstain(text):
            ok = False
            reasons.append("abstain_marker_missing")
    elif decision == "CLARIFY":
        if "?" not in text:
            ok = False
            reasons.append("clarify_question_missing")

    lowered = text.lower()
    if (
        "evidence pack" in lowered
        or "retrieve stronger citations" in lowered
        or "available memory evidence" in lowered
    ):
        ok = False
        reasons.append("internal_jargon_leak")

    return VerifiedReply(
        ok=ok,
        reasons=reasons,
        found_citations=found,
        unknown_citations=unknown,
        inferred_decision=inferred,
    )
