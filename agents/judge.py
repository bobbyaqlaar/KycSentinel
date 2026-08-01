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

import logging

from . import _framework  # noqa: F401
from .models import JudgeVerdict, ResearchFindings, RiskAssessment

# Framework judge primitives (G7): the same citation-grounding and
# pair-parity logic the CI eval suites use, so this per-request enforcement
# and the eval gate cannot drift.
from runtime.judging import (
    citations_grounded,
    parity_violation,
    warn_if_judge_not_independent,
)

logger = logging.getLogger(__name__)

_independence_checked = False


def _check_independence() -> None:
    """Warn once if the judge and analyst resolve to the same model (E3).
    Reads the merged registry (framework defaults ← models.yaml ←
    tenant.yaml overrides), so it reflects what the gateway will actually
    route, not just what this file assumes."""
    global _independence_checked
    if _independence_checked:
        return
    _independence_checked = True
    try:
        from runtime.llm_gateway import load_model_registry

        reg = load_model_registry()
        warn_if_judge_not_independent(
            (reg.get("analyst") or {}).get("id"),
            (reg.get("judge") or {}).get("id"),
        )
    except Exception:  # fail-open: an advisory check must never break judging
        pass


def check_citations(assessment: RiskAssessment, findings: ResearchFindings) -> JudgeVerdict:
    """F7 / policy-008: every citation must resolve to a retrieved doc."""
    check = citations_grounded(assessment.citations, findings.retrieved_doc_ids)
    return JudgeVerdict(
        citation_ok=check.grounded,
        unresolved_citations=list(check.unresolved),
        flagged=not check.grounded,
        reason=check.reason,
    )


def check_rating_floor(assessment: RiskAssessment, findings: ResearchFindings) -> JudgeVerdict:
    """policy-003 / policy-004: evidence that MANDATES a rating floor.

    The rating is the model's judgement, but some inputs remove that discretion:
    policy-003 says "Any hit mandates a HIGH rating and human review before
    onboarding". A sanctions hit is a FACT returned by the screening tool, not
    an opinion, so whether it forces human review must not depend on the model
    agreeing.

    Found live, not by any test. Against real models the Analyst rated an
    applicant with one confirmed sanctions hit as MEDIUM, cited five policies —
    all of them genuinely retrieved, so citation grounding passed — and
    `needs_hitl = assessment.rating == "HIGH" or judge.flagged` therefore
    evaluated to FALSE. A sanctions-matched applicant was one step from
    auto-approval with no human ever seeing it.

    Nothing in the offline suite could catch this: the fake gateway derives the
    rating deterministically from the hit count, so it always says HIGH and the
    control looks sound. It only fails when a real model is asked to agree with
    a rule it was never obliged to follow.
    """
    hits = len(findings.sanctions_hits or [])
    media = len(findings.adverse_media or [])
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    actual = order.get((assessment.rating or "").upper(), 0)

    if hits and actual < order["HIGH"]:
        return JudgeVerdict(
            citation_ok=True,
            flagged=True,
            reason=(
                f"policy-003: {hits} sanctions hit(s) mandate a HIGH rating and "
                f"human review; the Analyst returned {assessment.rating!r}. "
                f"Routing to human review on the evidence, not the rating."
            ),
        )
    if media >= 2 and actual < order["MEDIUM"]:
        return JudgeVerdict(
            citation_ok=True,
            flagged=True,
            reason=(
                f"policy-004: {media} adverse media items warrant at least "
                f"MEDIUM; the Analyst returned {assessment.rating!r}."
            ),
        )
    return JudgeVerdict(citation_ok=True, flagged=False)


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
    _check_independence()
    verdict = check_citations(assessment, findings)
    if verdict.flagged:
        return verdict
    # Evidence-mandated floor, checked AFTER grounding and independently of it.
    # A well-cited rationale can still under-rate a sanctions hit — observed
    # live — and citation grounding says nothing about that: it verifies the
    # rationale points at real documents, not that the rating obeys them.
    floor = check_rating_floor(assessment, findings)
    if floor.flagged:
        return floor
    # LLM critique is advisory on top of the hard checks — routed to the
    # independent judge model, never the analyst's. Its result is deliberately
    # not consumed: the verdict above comes from deterministic checks
    # (citation grounding, pair parity), and the call exists so the judge route
    # is genuinely exercised end-to-end (RFC-002 E3) rather than only declared.
    #
    # fail-open: advisory in output, so it must be advisory in failure too.
    # Until now an exception here propagated and failed the whole application —
    # a call whose ANSWER nobody reads could still block onboarding. The judge
    # role's degrade_to was masking that: an outage degraded to a weaker model
    # which wrote a critique nobody reads, and the fragility stayed hidden. The
    # degrade is gone (a substituted grader is not a grader — models.yaml), so
    # the real fix is that the hard checks, which are what actually gate, keep
    # working when the judge provider is down.
    try:
        await gateway.complete(
            f"Critique this KYC rationale for grounding and clarity:\n{assessment.rationale}",
            model_hint="judge",
            max_tokens=256,
        )
    except Exception as exc:
        logger.warning(
            "Advisory judge critique unavailable (%s) — citation and parity "
            "checks still applied; verdict unaffected.", exc,
        )
    return verdict
