"""
agents/analyst.py — Risk Analyst: the one frontier call (model_hint=
"analyst"), STREAMED in real mode so the TTFT budget applies, degrading
Claude → Groq → local under the $5 tenant cap (F5 — the ladder lives in
the gateway, not here).

The evidence summary embedded in the prompt is deterministic (hit counts,
retrieved doc ids); the model produces the rating + rationale + citations
as JSON, validated by parse_llm_json — a malformed response is exactly the
F2 self-correction trigger, so it propagates.
"""

from __future__ import annotations

import logging

from . import _framework  # noqa: F401
from .models import ApplicantProfile, ResearchFindings, RiskAssessment

try:
    from runtime.structured_output import parse_llm_json
except ImportError:
    from structured_output import parse_llm_json  # type: ignore

logger = logging.getLogger(__name__)

ANALYST_PROMPT = """You are the KYC risk analyst. Apply the retrieved policies to
the evidence and reply with ONLY JSON: {{"rating": "LOW|MEDIUM|HIGH",
"rationale": "...", "citations": ["policy-id", ...]}}.
Every claim must cite a retrieved policy id in [brackets]. Never cite a
document that is not listed under retrieved_docs.

applicant: {applicant_id} ({nationality})
sanctions_hit_count: {hits}
adverse_media_count: {media}
source_of_funds: {sof}
retrieved_docs: {docs}
{extra}
"""


async def run_analyst(
    gateway,
    profile: ApplicantProfile,
    findings: ResearchFindings,
    extra_context: str = "",
) -> RiskAssessment:
    prompt = ANALYST_PROMPT.format(
        applicant_id=profile.applicant_id,
        nationality=profile.nationality,
        hits=len(findings.sanctions_hits),
        media=len(findings.adverse_media),
        sof=profile.source_of_funds or "missing",
        docs=" ".join(f"[{d}]" for d in findings.retrieved_doc_ids),
        extra=extra_context,
    )
    result = await _complete_maybe_stream(gateway, prompt)
    return parse_llm_json(result.text, RiskAssessment)


async def _complete_maybe_stream(gateway, prompt: str):
    """Stream when the analyst's provider supports it, else fall back.

    TestbedFeedback-2026-07-21 G1/E1: the framework's complete_stream()
    raises NotImplementedError for 'anthropic' and every cloud-native
    provider — i.e. for exactly the frontier model this route uses. Fake
    mode masked it, so the crash would only have appeared in production.
    Streaming is a latency optimisation, never a correctness requirement:
    losing ttft_ms must not lose the assessment. Remove this shim once the
    gateway streams Anthropic (or falls back internally)."""
    try:
        return await gateway.complete_stream(
            prompt, model_hint="analyst", max_tokens=1024, temperature=0.1
        )
    except NotImplementedError as exc:
        logger.info("analyst provider does not support streaming (%s); TTFT unavailable", exc)
        return await gateway.complete(
            prompt, model_hint="analyst", max_tokens=1024, temperature=0.1
        )
