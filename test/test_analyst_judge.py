"""test/test_analyst_judge.py — rating rules, citation grounding (F7),
pair parity (F6), judge/actor route separation."""

from __future__ import annotations

import pytest

from agents.analyst import run_analyst
from agents.judge import check_citations, check_parity, run_judge
from agents.models import ApplicantProfile, ResearchFindings, RiskAssessment
from agents.research import run_research


def _profile(**over) -> ApplicantProfile:
    base = dict(
        applicant_id="x",
        full_name="Test Person",
        dob="1990-01-01",
        nationality="AE",
        company_name="Clean Co",
        role="Director",
        source_of_funds="salary",
    )
    base.update(over)
    return ApplicantProfile(**base)


@pytest.mark.asyncio
async def test_sanctions_hit_rates_high(gateway):
    p = _profile(company_name="Al Noor Trading FZE")
    findings = await run_research(gateway, p)
    assessment = await run_analyst(gateway, p, findings)
    assert assessment.rating == "HIGH"
    assert assessment.citations


@pytest.mark.asyncio
async def test_clean_profile_rates_low_and_judge_passes(gateway):
    p = _profile()
    findings = await run_research(gateway, p)
    assessment = await run_analyst(gateway, p, findings)
    assert assessment.rating == "LOW"
    verdict = await run_judge(gateway, assessment, findings)
    assert not verdict.flagged
    # judge critique went to the judge route, not the analyst's (RFC-002)
    assert gateway.calls[-1]["model_hint"] == "judge"


def test_citation_outside_retrieved_set_flags():
    """F7 hard check, no LLM involved."""
    findings = ResearchFindings(retrieved_doc_ids=["policy-001", "policy-005"])
    ok = RiskAssessment(rating="LOW", rationale="fine [policy-005]", citations=["policy-005"])
    bad = RiskAssessment(rating="LOW", rationale="fine [policy-999]", citations=["policy-999"])
    none = RiskAssessment(rating="LOW", rationale="no basis", citations=[])
    assert not check_citations(ok, findings).flagged
    assert check_citations(bad, findings).unresolved_citations == ["policy-999"]
    assert check_citations(none, findings).flagged  # uncited rationale is also flagged


def test_parity_check():
    """F6 hard check."""
    a = RiskAssessment(rating="LOW", rationale="r", citations=[])
    b = RiskAssessment(rating="LOW", rationale="r", citations=[])
    c = RiskAssessment(rating="HIGH", rationale="r", citations=[])
    assert not check_parity(a, b).flagged
    verdict = check_parity(a, c)
    assert verdict.flagged and "parity violation" in verdict.reason
