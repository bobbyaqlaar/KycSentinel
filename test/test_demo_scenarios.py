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
async def test_injection_never_reaches_analyst(gateway):
    """F3 depth: the embedded instruction must not lower the rating —
    the pipeline stops before any model call."""
    decision = await process_application(gateway, submission("inj-012"))
    assert decision.outcome == "hitl"
    assert decision.rating is None  # no analyst call happened at all
    assert gateway.calls == []
