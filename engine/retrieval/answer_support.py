"""Conservative source-text checks, without inferring natural-language meaning."""

from typing import Any

from ..contracts import MemoryPack


def normalize_answer_claims(claims: list[str] | None) -> list[str] | None:
    if claims is None:
        return None
    if not isinstance(claims, list) or not claims or any(
        not isinstance(value, str) or not value.strip() for value in claims
    ):
        raise ValueError("answer_claims must be a non-empty array of non-empty strings")
    return list(dict.fromkeys(value.strip() for value in claims))


def _text_key(text: str) -> str:
    # Preserve case, word order, negation and quotation/clause boundaries.
    return " ".join(text.split()).removesuffix(".")


def check_answer_claims(
    claims: list[str] | None, pack: MemoryPack, *, evidence_eligible: bool = True,
) -> dict[str, Any]:
    claims = normalize_answer_claims(claims)
    if claims is None:
        return {"status": "NOT_CHECKED", "checks": []}
    checks: list[dict[str, Any]] = []
    for claim in claims:
        claim_key = _text_key(claim)
        matching = None
        if evidence_eligible:
            matching = next((
                item for item in pack.core + pack.context
                if item.conflict_state == "active"
                and item.memory_layer != "short_term" and item.trust_tier != "ephemeral"
                and _text_key(item.canonical_text) == claim_key
                and any(ref.source_id and ref.message_id for ref in item.source_refs)
            ), None)
        checks.append({
            "claim": claim,
            "supported": matching is not None,
            "reason": "SOURCE_TEXT_MATCH" if matching else "ANSWER_NOT_VERIFIED",
            "evidence_id": matching.atom_id if matching else "",
            "citations": sorted({f"{ref.source_id}#{ref.message_id}" for ref in matching.source_refs
                                 if ref.source_id and ref.message_id}) if matching else [],
        })
    return {"status": "SUPPORTED" if all(row["supported"] for row in checks) else "UNVERIFIED", "checks": checks}
