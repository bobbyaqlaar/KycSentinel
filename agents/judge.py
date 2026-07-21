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

# Framework judge primitives (G7): the same citation-grounding and
# pair-parity logic the CI eval suites use, so this per-request enforcement
# and the eval gate cannot drift.
from runtime.judging import citations_grounded, parity_violation


def check_citations(assessment: RiskAssessment, findings: ResearchFindings) -> JudgeVerdict:
    """F7 / policy-008: every citation must resolve to a retrieved doc."""
    check = citations_grounded(assessment.citations, findings.retrieved_doc_ids)
    return JudgeVerdict(
        citation_ok=check.grounded,
        unresolved_citations=list(check.unresolved),
        flagged=not check.grounded,
        reason=check.reason,
    )


def check_parity(a: RiskAssessment, b: RiskAssessment, attribute: str = "nationality") -> JudgeVerdict:
    """F6 / policy-007: same profile, protected attribute swapped → same rating."""
    reason = parity_violation(a.rating, b.rating, attribute=attribute)
    if reason is None:
        return JudgeVerdict(citation_ok=True, flagged=False)
    return JudgeVerdict(citation_ok=True, flagged=True, reason=f"{reason} (policy-007)")


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
