"""test/test_demo_scenarios.py — every F-scenario driver must fire its
control (these are the same functions `make demo-f*` runs)."""

from __future__ import annotations

import pytest

import demo
from conftest import submission
from pipeline import process_application


@pytest.mark.asyncio
@pytest.mark.parametrize("fid", list(demo.SCENARIOS))
async def test_scenario_fires_its_control(fid):
    expected = {
        "f1": "recoverable_step",
        "f2": "self_correction",
        "f3": "prompt_guard",
        "f4": "tool_allowlist",
        "f5": "degrade_ladder",
        "f6": "fairness_parity",
        "f7": "hallucination_gate",
        "f8": "pii_scrub",
    }
    assert await demo.SCENARIOS[fid]() == expected[fid]


@pytest.mark.asyncio
@pytest.mark.parametrize("fid", ["f1", "f2"])
async def test_scenario_fails_loudly_when_its_control_stops_firing(fid, monkeypatch):
    """Regression: F1 and F2 raised their own guard AssertionError INSIDE a
    `try` guarded by `except Exception`, so both caught it and returned their
    control name anyway. `make demo-all`, `demo.py all` in CI, and the Cloud
    Run smoke job all reported the control proven while it was doing nothing.
    With intake stubbed to always succeed, the drivers must now fail."""
    from agents.intake import IntakeResult
    from agents.models import ApplicantProfile

    async def never_rejects(_gateway, submission):
        return IntakeResult(
            profile=ApplicantProfile(
                applicant_id="stub",
                full_name="Stub",
                dob="1990-01-01",
                nationality="AE",
                company_name="Stub LLC",
                role="director",
            ),
            scrub_counts={},
            scrubbed_submission=submission,
        )

    monkeypatch.setattr(demo, "run_intake", never_rejects)

    with pytest.raises(AssertionError, match="control did NOT fire"):
        await demo.SCENARIOS[fid]()


@pytest.mark.asyncio
async def test_pipeline_outcomes_match_fixture_expectations(gateway, applicants):
    """End-to-end: every non-malformed fixture routes to the documented
    outcome — sanctions/injection → hitl, clean → approved."""
    for a in applicants.values():
        if "malformed" in a["tags"]:
            continue
        decision = await process_application(gateway, a["submission"])
        if a["expected_rating"] == "HIGH" or "injection" in a["tags"]:
            assert decision.outcome == "hitl", a["id"]
        elif a["expected_rating"] == "LOW":
            assert decision.outcome == "approved", a["id"]
        else:  # MEDIUM: approved unless judge flagged
            assert decision.outcome in ("approved", "hitl"), a["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["default", "block", "strict", ""])
async def test_enforcing_modes_block_the_injection(gateway, monkeypatch, mode):
    monkeypatch.setenv("PROMPT_GUARD", mode)
    decision = await process_application(gateway, submission("inj-012"))
    assert decision.outcome == "hitl"
    assert decision.rating is None
    assert decision.guard_reasons


@pytest.mark.asyncio
async def test_warn_mode_reports_without_blocking(gateway, monkeypatch):
    """Regression: the pipeline called scan_prompt directly, which reports
    blocked=True on any hit regardless of PROMPT_GUARD — so this tenant's front
    door ignored the mode contract and `warn`, the observe-first tier the
    framework added in G9, could not be used at all. The findings must still
    ride along on the Decision, or observing is pointless."""
    monkeypatch.setenv("PROMPT_GUARD", "warn")
    decision = await process_application(gateway, submission("inj-012"))
    assert decision.rating is not None, "warn must not stop the pipeline"
    assert "instruction_override" in decision.guard_reasons


@pytest.mark.asyncio
async def test_off_mode_does_not_scan(gateway, monkeypatch):
    monkeypatch.setenv("PROMPT_GUARD", "off")
    decision = await process_application(gateway, submission("inj-012"))
    assert decision.rating is not None
    assert decision.guard_reasons == []


@pytest.mark.asyncio
async def test_injection_never_reaches_analyst(gateway):
    """F3 depth: the embedded instruction must not lower the rating —
    the pipeline stops before any model call."""
    decision = await process_application(gateway, submission("inj-012"))
    assert decision.outcome == "hitl"
    assert decision.rating is None  # no analyst call happened at all
    assert gateway.calls == []
