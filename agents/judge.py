"""
agents/judge.py — Compliance Judge: two deterministic checks (no LLM
needed to enforce them) + an optional LLM critique on the independent
judge route (judge/actor separation, RFC-002).

  (a) Citation grounding (F7): every citation must be in the retrieved set
      — policy-008 calls an unresolved citation a hallucination and it
      blocks auto-approval.
  (b) Pair parity (F6): same profile with a protected attribute swapped
      must produce the same rating (policy-007).
"""

from __future__ import annotations

from . import _framework  # noqa: F401
from .models import JudgeVerdict, ResearchFindings, RiskAssessment


def check_citations(assessment: RiskAssessment, findings: ResearchFindings) -> JudgeVerdict:
    retrieved = set(findings.retrieved_doc_ids)
    unresolved = [c for c in assessment.citations if c not in retrieved]
    missing_any = not assessment.citations
    flagged = bool(unresolved) or missing_any
    reason = (
        f"citations not in retrieved set: {unresolved}" if unresolved
        else ("rationale has no citations" if missing_any else "")
    )
    return JudgeVerdict(
        citation_ok=not flagged,
        unresolved_citations=unresolved,
        flagged=flagged,
        reason=reason,
    )


def check_parity(a: RiskAssessment, b: RiskAssessment, attribute: str = "nationality") -> JudgeVerdict:
    if a.rating == b.rating:
        return JudgeVerdict(citation_ok=True, flagged=False)
    return JudgeVerdict(
        citation_ok=True,
        flagged=True,
        reason=(
            f"parity violation: identical profiles with {attribute} swapped "
            f"rated {a.rating} vs {b.rating} (policy-007)"
        ),
    )


async def run_judge(
    gateway,
    assessment: RiskAssessment,
    findings: ResearchFindings,
) -> JudgeVerdict:
    verdict = check_citations(assessment, findings)
    if verdict.flagged:
        return verdict
    # LLM critique is advisory on top of the hard checks — routed to the
    # independent judge model, never the analyst's.
    await gateway.complete(
        f"Critique this KYC rationale for grounding and clarity:\n{assessment.rationale}",
        model_hint="judge",
        max_tokens=256,
    )
    return verdict
