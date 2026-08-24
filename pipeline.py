"""
pipeline.py — the KYC decision pipeline, engine-agnostic.

One async function = one application. The Temporal workflow's activities
call these same steps (workflows/activities.py); demo.py and the tests
call it in-process. Keeping the pipeline out of the workflow file keeps
Temporal's determinism sandbox away from file I/O and lets every
F-scenario run without an orchestrator.

Order of controls (each one is a framework claim under test):
  1. prompt_guard.scan_prompt on the RAW submission (F3)
  2. Intake: input_guardrail scrub → local parse → Pydantic (F1/F2/F8)
  3. Research: strict-allowlisted tools + RAG retrieve (F4)
  4. Analyst: streamed frontier call w/ degrade ladder (F5)
  5. Judge: citation grounding (F7); parity checked batch-wise (F6)
  6. Decision: LOW → auto-approve; HIGH or judge flag → HITL (policy-006)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agents import _framework  # noqa: F401
from agents.analyst import run_analyst
from agents.intake import IntakeResult, run_intake
from agents.judge import run_judge
from agents.models import JudgeVerdict, ResearchFindings, RiskAssessment
from agents.research import run_research

from runtime.prompt_guard import (
    PromptGuardBlockedError,
    PromptGuardResult,
    apply_prompt_guard,
    is_enforcing,
)
from runtime.tenancy import agent_context, resolve_tenant_id
from runtime.tracing import agent_span


@dataclass
class Decision:
    applicant_id: str
    outcome: str  # "approved" | "hitl" | "blocked_injection"
    rating: Optional[str] = None
    rationale: str = ""
    scrub_counts: dict = field(default_factory=dict)
    guard_reasons: list = field(default_factory=list)
    verdict: Optional[JudgeVerdict] = None
    assessment: Optional[RiskAssessment] = None
    findings: Optional[ResearchFindings] = None


async def process_application(gateway, submission: str, analyst_extra: str = "") -> Decision:
    # apply_prompt_guard, not scan_prompt: scan_prompt always reports
    # blocked=True on a hit regardless of PROMPT_GUARD, so calling it directly
    # made this front door ignore the mode contract entirely — PROMPT_GUARD=off
    # still blocked, and `warn` (the observe-first tier the framework added in
    # G9 precisely so a guard can be rolled out against real traffic before it
    # enforces) was unusable here. is_enforcing() is the framework's single
    # definition of "blocking", shared with the gateway and the SEC-PROMPT-001
    # harness, so this check and the gateway's cannot disagree about whether
    # the guard is on.
    # PROMPT_GUARD=strict raises from inside apply_prompt_guard rather than
    # returning a blocked result (that is the difference between strict and
    # default). Catching it here keeps the outcome identical to default mode —
    # a flagged submission is a human-review case, not a crashed application.
    try:
        guard = apply_prompt_guard([{"role": "user", "content": submission}])
    except PromptGuardBlockedError as exc:
        guard = PromptGuardResult(blocked=True, reasons=list(exc.reasons))

    if guard.blocked and is_enforcing():
        # F3: injection attempts route straight to human review, flagged —
        # the pipeline never lets the embedded instruction reach the analyst.
        return Decision(
            applicant_id="(unparsed)",
            outcome="hitl",
            rationale="prompt-injection heuristics fired; manual review required",
            guard_reasons=list(guard.reasons),
        )

    # Identity is BOUND, not threaded. This line was
    # `getattr(gateway, "tenant_id", "kyc-sentinel")` — a third copy of a value
    # declared once in .agenticframework/tenant.yaml, and the fallback silently
    # relabelled every span whenever the gateway was a test double. Bound once
    # here, each step names only its role, and every span beneath — including
    # the gateway's LLM spans and ToolRegistry's tool spans — inherits both.
    tenant = resolve_tenant_id(getattr(gateway, "tenant_id", None))
    # In warn mode the call proceeds, but the findings still ride along on the
    # Decision — observe-first is only useful if you can actually see what
    # would have been blocked.
    guard_reasons = list(guard.reasons)

    # Each step gets its own span (framework G8) so the non-LLM work — scrub
    # counts, tool calls (auto-annotated by ToolRegistry.invoke), the judge
    # verdict — is visible in Phoenix alongside the gateway's LLM spans, not
    # just the model calls. No-ops cleanly when tracing is off.
    with agent_context(tenant_id=tenant):
        with agent_context(role="intake"), agent_span("intake") as span:
            intake: IntakeResult = await run_intake(gateway, submission)
            span.set_attribute("agent.pii_redactions", sum(intake.scrub_counts.values()))

        with agent_context(role="research"), agent_span("research") as span:
            findings = await run_research(gateway, intake.profile)
            span.set_attribute("agent.sanctions_hits", len(findings.sanctions_hits))

        with agent_context(role="analyst"), agent_span("analyst"):
            assessment = await run_analyst(gateway, intake.profile, findings, analyst_extra)

        with agent_context(role="judge"), agent_span("judge") as span:
            verdict = await run_judge(gateway, assessment, findings)
            span.set_attribute("agent.judge_flagged", verdict.flagged)

    if assessment.rating == "HIGH" or verdict.flagged:
        outcome = "hitl"  # policy-006: high-impact → human decision
    else:
        outcome = "approved"

    return Decision(
        applicant_id=intake.profile.applicant_id,
        outcome=outcome,
        rating=assessment.rating,
        rationale=assessment.rationale,
        scrub_counts=intake.scrub_counts,
        guard_reasons=guard_reasons,
        verdict=verdict,
        assessment=assessment,
        findings=findings,
    )
