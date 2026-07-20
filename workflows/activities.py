"""
workflows/activities.py — Temporal activities wrapping the pipeline steps.

Activities are thin: all logic lives in pipeline.py / agents/* so the
same code runs in-process (demo, tests) and under Temporal. Payloads are
plain dicts (Temporal-serializable); Pydantic models are rebuilt inside.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from temporalio import activity  # noqa: E402

from agents import _framework  # noqa: E402,F401
from agents.analyst import run_analyst  # noqa: E402
from agents.gateway import get_gateway  # noqa: E402
from agents.intake import run_intake  # noqa: E402
from agents.judge import run_judge  # noqa: E402
from agents.models import ApplicantProfile, ResearchFindings, RiskAssessment  # noqa: E402
from agents.research import run_research  # noqa: E402


@activity.defn
async def intake_activity(input: dict) -> dict:
    gw = get_gateway()
    result = await run_intake(gw, input["submission"])
    return {
        "profile": result.profile.model_dump(),
        "scrub_counts": result.scrub_counts,
    }


@activity.defn
async def research_activity(input: dict) -> dict:
    gw = get_gateway()
    findings = await run_research(gw, ApplicantProfile(**input["profile"]))
    return {"findings": findings.model_dump()}


@activity.defn
async def analyst_activity(input: dict) -> dict:
    gw = get_gateway()
    assessment = await run_analyst(
        gw,
        ApplicantProfile(**input["profile"]),
        ResearchFindings(**input["findings"]),
        input.get("extra", ""),
    )
    judge = await run_judge(gw, assessment, ResearchFindings(**input["findings"]))
    needs_hitl = assessment.rating == "HIGH" or judge.flagged
    return {
        "assessment": assessment.model_dump(),
        "verdict": judge.model_dump(),
        "needs_hitl": needs_hitl,
    }


@activity.defn
async def approve_activity(input: dict) -> dict:
    """Terminal step after auto-approval or explicit human approval —
    the high-impact action itself (policy-006). Audit-logged upstream."""
    assessment = RiskAssessment(**input["assessment"])
    return {
        "status": "completed",
        "decision": "approved",
        "rating": assessment.rating,
        "applicant_id": input.get("applicant_id", ""),
    }
