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
    assert gateway.calls[-1].model_hint == "judge"


def test_citation_outside_retrieved_set_flags():
    """F7 hard check, no LLM involved."""
    findings = ResearchFindings(retrieved_doc_ids=["policy-001", "policy-005"])
    ok = RiskAssessment(rating="LOW", rationale="fine [policy-005]", citations=["policy-005"])
    bad = RiskAssessment(rating="LOW", rationale="fine [policy-999]", citations=["policy-999"])
    none = RiskAssessment(rating="LOW", rationale="no basis", citations=[])
    assert not check_citations(ok, findings).flagged
    assert check_citations(bad, findings).unresolved_citations == ["policy-999"]
    assert check_citations(none, findings).flagged  # uncited rationale is also flagged


@pytest.mark.asyncio
async def test_analyst_streams_on_a_streaming_provider(gateway):
    """The analyst route is Anthropic, which the framework streams (G1), so the
    TTFT budget applies to the one latency-critical call in this pipeline."""
    p = _profile()
    findings = await run_research(gateway, p)
    await run_analyst(gateway, p, findings)

    analyst_call = next(c for c in reversed(gateway.calls) if c.model_hint == "analyst")
    assert analyst_call.streamed is True


@pytest.mark.asyncio
async def test_analyst_survives_provider_without_streaming(gateway):
    """G1 regression: a route pointed at a provider with no SSE surface must
    still produce an assessment — losing ttft_ms must never lose the decision.

    This used to be the tenant's problem: complete_stream raised
    NotImplementedError and agents/analyst.py carried its own
    `except NotImplementedError` shim. The gateway now falls back to complete()
    inside complete_stream itself, so the shim was removed and this asserts the
    FRAMEWORK's guarantee instead. It exercises a provider the gateway
    genuinely cannot stream (bedrock — a cloud-native adapter with its own
    envelope), rather than monkeypatching a raise that the real gateway no
    longer performs; a test that simulates deleted behaviour proves nothing
    about today's code."""
    gateway.providers = {**gateway.providers, "analyst": "bedrock"}

    p = _profile()
    findings = await run_research(gateway, p)
    assessment = await run_analyst(gateway, p, findings)

    assert assessment.rating == "LOW"
    analyst_call = next(c for c in reversed(gateway.calls) if c.model_hint == "analyst")
    assert analyst_call.streamed is False  # fell back, same route


def test_parity_check():
    """F6 hard check."""
    a = RiskAssessment(rating="LOW", rationale="r", citations=[])
    b = RiskAssessment(rating="LOW", rationale="r", citations=[])
    c = RiskAssessment(rating="HIGH", rationale="r", citations=[])
    assert not check_parity(a, b).flagged
    verdict = check_parity(a, c)
    assert verdict.flagged and "parity violation" in verdict.reason


@pytest.mark.asyncio
async def test_judge_warns_when_configured_same_as_analyst(gateway, monkeypatch, caplog):
    """E3 wiring: if a misconfiguration points judge and analyst at the same
    model, run_judge must actually emit the framework warning — not just
    import the helper."""
    import logging

    import agents.judge as judge_mod
    from runtime import llm_gateway

    monkeypatch.setattr(judge_mod, "_independence_checked", False)
    monkeypatch.setattr(
        llm_gateway,
        "load_model_registry",
        lambda: {"analyst": {"id": "same-model"}, "judge": {"id": "same-model"}},
    )

    a = RiskAssessment(rating="LOW", rationale="ok [policy-005]", citations=["policy-005"])
    f = ResearchFindings(retrieved_doc_ids=["policy-005"])
    with caplog.at_level(logging.WARNING):
        await run_judge(gateway, a, f)
    assert any("not independent" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_judge_provider_outage_does_not_fail_the_application(gateway, caplog):
    """The advisory critique is advisory in failure too.

    Its result is discarded — the verdict comes from the deterministic citation
    and parity checks — yet an exception from it used to propagate and fail the
    whole application. A call whose answer nobody reads could block onboarding.

    This was invisible while the judge role declared `degrade_to: research`: an
    outage quietly substituted a weaker model to write a critique nobody reads.
    That degrade is gone (a substituted grader is not a grader), so this is what
    keeps applications flowing when the judge provider is down.
    """
    p = _profile()
    findings = await run_research(gateway, p)
    assessment = await run_analyst(gateway, p, findings)

    async def _exhausted(*a, **k):
        raise RuntimeError(
            "HTTP 400: Your credit balance is too low to access the Anthropic API."
        )

    gateway.complete = _exhausted

    with caplog.at_level("WARNING"):
        verdict = await run_judge(gateway, assessment, findings)

    # The hard checks still ran and still decided.
    assert not verdict.flagged
    assert "Advisory judge critique unavailable" in caplog.text
    assert "credit balance is too low" in caplog.text


@pytest.mark.asyncio
async def test_a_flagged_citation_still_blocks_when_the_judge_is_down(gateway):
    """Fail-open must not become fail-blind: the deterministic checks are the
    gate, so they must still flag with the LLM unavailable."""
    p = _profile()
    findings = await run_research(gateway, p)
    assessment = await run_analyst(gateway, p, findings)
    assessment.citations = ["doc-that-was-never-retrieved"]

    async def _exhausted(*a, **k):
        raise RuntimeError("provider down")

    gateway.complete = _exhausted

    verdict = await run_judge(gateway, assessment, findings)
    assert verdict.flagged


# ── Evidence-mandated rating floor (policy-003 / policy-004) ─────────────────


def test_sanctions_hit_forces_review_even_when_the_model_under_rates():
    """The control that failed live.

    Against real models the Analyst rated an applicant with one confirmed
    sanctions hit as MEDIUM, citing five genuinely-retrieved policies — so
    citation grounding passed, `judge.flagged` was False, and
    `needs_hitl = rating == "HIGH" or judge.flagged` came out FALSE. A
    sanctions-matched applicant was one step from auto-approval.

    policy-003 makes this non-discretionary: "Any hit mandates a HIGH rating
    and human review". A sanctions hit is a fact from the screening tool, so
    the gate must key off the evidence rather than the model's agreement.
    """
    from agents.judge import check_rating_floor

    findings = ResearchFindings(
        sanctions_hits=[{"entity": "Viktor Marchenko"}],
        retrieved_doc_ids=["policy-003", "policy-005"],
    )
    under_rated = RiskAssessment(
        rating="MEDIUM", rationale="Some risk.", citations=["policy-003", "policy-005"]
    )
    v = check_rating_floor(under_rated, findings)
    assert v.flagged
    assert "policy-003" in v.reason
    # The whole point: HITL fires on the evidence, not on the rating.
    assert (under_rated.rating == "HIGH" or v.flagged) is True


def test_a_correctly_rated_sanctions_hit_is_not_double_flagged():
    from agents.judge import check_rating_floor

    findings = ResearchFindings(
        sanctions_hits=[{"entity": "x"}], retrieved_doc_ids=["policy-003"]
    )
    ok = RiskAssessment(rating="HIGH", rationale="Sanctions hit.", citations=["policy-003"])
    assert not check_rating_floor(ok, findings).flagged


def test_adverse_media_floor():
    """policy-004: two or more items warrant at least MEDIUM."""
    from agents.judge import check_rating_floor

    findings = ResearchFindings(
        adverse_media=["a", "b"], retrieved_doc_ids=["policy-004"]
    )
    assert check_rating_floor(
        RiskAssessment(rating="LOW", rationale="", citations=[]), findings
    ).flagged
    assert not check_rating_floor(
        RiskAssessment(rating="MEDIUM", rationale="", citations=[]), findings
    ).flagged


def test_clean_applicant_is_not_flagged():
    """No evidence, no floor — a genuine LOW must stay LOW and auto-approvable."""
    from agents.judge import check_rating_floor

    assert not check_rating_floor(
        RiskAssessment(rating="LOW", rationale="Clean.", citations=["policy-005"]),
        ResearchFindings(retrieved_doc_ids=["policy-005"]),
    ).flagged
