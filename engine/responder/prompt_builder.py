from __future__ import annotations

from typing import Any, Mapping

from .verifier import CANONICAL_ABSTAIN_PHRASE


def build_responder_messages(package: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build external-model messages from a context package.

    This intentionally produces a provider-agnostic messages array (system/user roles).
    """

    message = str(package.get("message") or "").strip()
    guidance = package.get("responder_guidance") if isinstance(package.get("responder_guidance"), Mapping) else {}
    decision = ""
    verdict = package.get("service_verdict") if isinstance(package.get("service_verdict"), Mapping) else {}
    if isinstance(verdict, Mapping):
        decision = str(verdict.get("decision") or "").strip().upper()
    render_citations = bool(guidance.get("render_citations", True))

    rule_lines = [
        "You are the assistant. You have access to memory evidence from a memory service.",
        "",
        "Rules:",
        "- Do not invent memories. If evidence is insufficient, abstain or ask one follow-up question.",
        "- Do not quote evidence verbatim unless the user asks for a quote.",
        "- Do not mention internal tools, 'evidence packs', or evaluation jargon.",
        "- Keep the reply natural.",
    ]
    if render_citations:
        rule_lines.append(
            "- When you use memory evidence, include at least one citation token exactly as provided (format: source_id#message_id)."
        )
    else:
        rule_lines.append("- Use memory evidence internally, but do not output citation tokens or source-id strings.")
        rule_lines.append("- Do not output footnotes/references like [1], 'Source:', or a references section.")
    if decision == "ABSTAIN":
        rule_lines.append(f"- If service verdict is ABSTAIN, reply exactly: {CANONICAL_ABSTAIN_PHRASE}")
    rule_lines.extend(
        [
            "",
            f"Service verdict (follow this): {decision or 'UNKNOWN'}",
            f"Citations visible to user: {'ON' if render_citations else 'OFF'}",
        ]
    )
    rules = "\n".join(rule_lines).strip()

    evidence_lines: list[str] = []
    evidence = package.get("ltm_evidence")
    if isinstance(evidence, list) and evidence:
        evidence_lines.append("Memory evidence (cite with the Sources tokens):")
        for idx, item in enumerate(evidence[:8], start=1):
            if not isinstance(item, Mapping):
                continue
            summary = str(item.get("summary") or "").strip()
            citations = item.get("citations")
            citations_list = [str(c).strip() for c in list(citations or []) if str(c).strip()]
            sources = ", ".join(citations_list[:4])
            if summary:
                evidence_lines.append(f"{idx}. {summary}")
                if sources:
                    evidence_lines.append(f"   Sources: {sources}")
    else:
        evidence_lines.append("Memory evidence: (none)")

    evidence_block = "\n".join(evidence_lines).strip()

    return [
        {"role": "system", "content": rules},
        {"role": "system", "content": evidence_block},
        {"role": "user", "content": message},
    ]
