"""test/test_intake.py — Intake agent: PII scrub order, structured parse,
malformed-input propagation (F1/F2/F8)."""

from __future__ import annotations

import pytest
from conftest import submission

from agents.intake import run_intake


@pytest.mark.asyncio
async def test_clean_submission_parses_to_profile(gateway):
    result = await run_intake(gateway, submission("clean-001"))
    p = result.profile
    assert p.applicant_id == "clean-001"
    assert p.full_name == "Amina Hassan"
    assert p.nationality == "EG"
    assert p.dob == "1988-03-14"


@pytest.mark.asyncio
async def test_pii_scrubbed_before_model_call(gateway):
    """F8: the Emirates ID / card / email must be gone from the prompt the
    model receives — not just from the output."""
    result = await run_intake(gateway, submission("pii-004"))
    assert result.scrub_counts.get("emirates_id", 0) >= 1
    assert result.scrub_counts.get("card", 0) >= 1
    assert result.scrub_counts.get("email", 0) >= 1
    prompt_seen_by_model = gateway.calls[0]["prompt"]
    assert "784-1985-1234567-1" not in prompt_seen_by_model
    assert "4111 1111 1111 1111" not in prompt_seen_by_model
    assert "omar@rashidventures.example" not in prompt_seen_by_model


@pytest.mark.asyncio
async def test_malformed_dob_raises_for_recoverable_step(gateway):
    """F1: a bad date is a validation error the workflow parks on — the
    agent must not guess."""
    with pytest.raises(Exception) as exc:
        await run_intake(gateway, submission("malf-009"))
    assert "dob" in str(exc.value) or "date" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_broken_model_json_raises_for_self_correction(gateway):
    """F2: unparseable model output raises StructuredOutputError."""
    from agents.intake import StructuredOutputError

    with pytest.raises(StructuredOutputError):
        await run_intake(gateway, submission("malf-010"))
