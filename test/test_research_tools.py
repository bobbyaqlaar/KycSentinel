"""test/test_research_tools.py — tools (F4 denial), sanctions alias
matching, RAG retrieval."""

from __future__ import annotations

import pytest

from agents.models import ApplicantProfile
from agents.research import policy_store, run_research
from agents.tools import ToolNotAllowedError, registry


def _profile(**over) -> ApplicantProfile:
    base = dict(
        applicant_id="x",
        full_name="Test Person",
        dob="1990-01-01",
        nationality="AE",
        company_name="Test LLC",
        role="Director",
        source_of_funds="salary",
    )
    base.update(over)
    return ApplicantProfile(**base)


def test_wire_transfer_denied_by_allowlist():
    """F4: registered but not allowlisted → deny-by-default."""
    with pytest.raises(ToolNotAllowedError):
        registry.invoke("wire_transfer", {"to_account": "IBAN", "amount_usd": 1.0})


def test_allowlisted_tools_invoke():
    assert registry.invoke("company_registry_lookup", {"company": "Acme"})["registered"]
    assert registry.invoke("sanctions_lookup", {"name": "Nobody Special"}) == []


def test_sanctions_alias_matching():
    hits = registry.invoke("sanctions_lookup", {"name": "Al Noor Trading FZE"})
    assert hits and hits[0]["entity"] == "Al-Noor Trading Company"
    hits = registry.invoke("sanctions_lookup", {"name": "Viktor Marchenco"})
    assert hits and hits[0]["entity"] == "Viktor Marchenko"


def test_policy_store_retrieves_relevant_docs():
    hits = policy_store().query("sanctions screening alias", k=3)
    assert len(hits) == 3
    assert all(h.id.startswith("policy-") for h in hits)


@pytest.mark.asyncio
async def test_research_findings_shape(gateway):
    findings = await run_research(gateway, _profile(company_name="CSL Shipping"))
    assert findings.sanctions_hits, "alias hit expected for CSL Shipping"
    # rubric + sanctions SOP always pinned into the citation vocabulary
    assert {"policy-005", "policy-003"} <= set(findings.retrieved_doc_ids)


@pytest.mark.asyncio
async def test_adverse_media_lookup(gateway):
    findings = await run_research(gateway, _profile(full_name="Karim Haddad"))
    assert len(findings.adverse_media) >= 2


@pytest.mark.asyncio
async def test_research_makes_a_real_cheap_tier_call(gateway):
    """E2: the Research agent uses its own model_hint='research' route
    (Groq cheap tier), not just tools + RAG — so all four model routes are
    genuinely exercised, not three plus a degrade target."""
    findings = await run_research(gateway, _profile(company_name="Al Noor Trading FZE"))
    assert "research" in gateway.routes_used()
    assert findings.screening_summary  # the LLM brief, not empty
    assert gateway.calls_for("research")[0].model_hint == "research"


@pytest.mark.asyncio
async def test_research_summary_degrades_without_failing(gateway):
    """A screening-summary failure is informational — it must not abort the
    application; the tool findings still drive the decision."""

    async def boom(*a, **k):
        raise RuntimeError("provider down")

    gateway.complete = boom
    findings = await run_research(gateway, _profile())
    assert findings.screening_summary  # deterministic fallback brief
    assert "source of funds" in findings.screening_summary
