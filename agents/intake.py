"""
agents/intake.py — Intake Agent: PII scrub FIRST, then structured parse.

Order is the whole point (PDPL decision-path story, F8): the framework
input_guardrail scrubs Emirates IDs / emails / phones / Luhn cards from the
raw submission BEFORE the text reaches any model — and the intake model
route is local anyway (falcon3 @ Ollama, RFC-002). Returns the scrub counts
so the workflow can attach them as span attributes.

A malformed submission surfaces as StructuredOutputError / pydantic
ValidationError from parse_llm_json — consumed upstream by F1 (recoverable
step) and F2 (self-correction). This agent does not catch it.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import _framework  # noqa: F401
from .models import ApplicantProfile

from runtime.input_guardrail import scrub_text
from runtime.structured_output import parse_llm_json, StructuredOutputError  # noqa: F401

INTAKE_PROMPT = """You are the KYC intake parser. Extract the applicant fields
from the submission below and reply with ONLY a JSON object with keys:
applicant_id, full_name, dob (ISO YYYY-MM-DD), nationality, company_name,
role, source_of_funds (or null), notes.

Submission:
{submission}
"""


@dataclass
class IntakeResult:
    profile: ApplicantProfile
    scrub_counts: dict
    scrubbed_submission: str


async def run_intake(gateway, submission: str) -> IntakeResult:
    scrubbed, counts = scrub_text(submission, mode="default")
    result = await gateway.complete(
        INTAKE_PROMPT.format(submission=scrubbed),
        model_hint="intake",
        max_tokens=512,
        temperature=0.0,
    )
    profile = parse_llm_json(result.text, ApplicantProfile)
    return IntakeResult(profile=profile, scrub_counts=counts, scrubbed_submission=scrubbed)
