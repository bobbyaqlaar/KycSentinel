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

from . import _framework  # noqa: F401
from .models import ApplicantProfile, ResearchFindings, RiskAssessment

from runtime.structured_output import parse_llm_json

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
    # complete_stream handles the non-streaming providers itself now: it falls
    # back to complete() internally with ttft_ms=None rather than raising
    # (framework G1, CHANGELOG [Unreleased]). A local `except
    # NotImplementedError` shim used to sit here for that; it became
    # unreachable in both real and fake mode — runtime.testing.FakeGateway
    # defaults stream_fallback=True — while its comment still asserted the
    # gateway "raises NotImplementedError for 'anthropic'", which is now the
    # opposite of the truth. Dead code with a confidently wrong comment is
    # worse than no comment.
    result = await gateway.complete_stream(
        prompt, model_hint="analyst", max_tokens=1024, temperature=0.1
    )
    return parse_llm_json(result.text, RiskAssessment)
