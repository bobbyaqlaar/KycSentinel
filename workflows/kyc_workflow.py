"""
workflows/kyc_workflow.py — durable KYC pipeline on the framework's
BaseAgentWorkflow (SPECS.md §25).

Framework patterns used (testbed-tenant-spec.md §2):
  - run_with_recoverable_step around INTAKE — a malformed submission parks
    in the DLQ; portal "Replay with edits" → replay webhook →
    temporal_replay signals the fix back in (F1).
  - run_with_self_correction around ANALYST — broken model JSON gets one
    corrected retry, then the human DLQ (F2). Opt-in per tenant.yaml.
  - run_with_hitl_gate on the DECISION — HIGH rating or judge flag pauses
    for the hitl_approved signal; approve_activity only runs after a
    recorded human decision (policy-006).

sys.path bootstrap lives in worker.py, NOT here — Temporal's determinism
sandbox re-imports this module and rejects Path.resolve() at module level
(same lesson recorded in examples/oil-price-agent/worker.py). Since the
runtime became an installable package (framework G6) the base-workflow
import is a plain `runtime.workflows.base_workflow` rather than a flat
`base_workflow` that depended on worker.py having inserted
`runtime/workflows/` onto sys.path first — one less ordering constraint
between two files the sandbox re-imports independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from runtime.workflows.base_workflow import (  # noqa: F401
        AgentWorkflowResult,
        BaseAgentWorkflow,
    )


@dataclass
class KycWorkflowInput:
    tenant_id: str
    submission: str
    self_correct: bool = True


@workflow.defn
class KycApplicationWorkflow(BaseAgentWorkflow):
    @workflow.run
    async def run(self, input: KycWorkflowInput) -> dict:
        # F1: intake failures park for a human-edited payload.
        intake = await self.run_with_recoverable_step(
            "intake_activity",
            {"submission": input.submission},
            tenant_id=input.tenant_id,
            gate_id="intake-parse",
            reason="intake_validation_error",
        )
        if isinstance(intake, AgentWorkflowResult):  # dead-lettered terminally
            return {"status": intake.status, "stage": "intake"}

        research = await workflow.execute_activity(
            "research_activity",
            {"profile": intake["profile"]},
            start_to_close_timeout=timedelta(minutes=5),
        )

        analyst_input = {
            "profile": intake["profile"],
            "findings": research["findings"],
        }
        # F2: one corrected retry for broken analyst JSON, then human DLQ.
        if input.self_correct:
            analysis = await self.run_with_self_correction(
                "analyst_activity",
                analyst_input,
                tenant_id=input.tenant_id,
                gate_id="analyst-json",
                reason="analyst_validation_error",
                # Retry on the Analyst's OWN model tier, not the framework's
                # generic "developer" default (gpt-4o/OpenAI) — this tenant
                # never configures OPENAI_API_KEY, and correcting the
                # Analyst's broken JSON with a different, unrelated model
                # than the one that wrote it defeats the point of a
                # same-model retry.
                model_hint="analyst",
            )
        else:
            analysis = await workflow.execute_activity(
                "analyst_activity",
                analyst_input,
                start_to_close_timeout=timedelta(minutes=5),
            )
        if isinstance(analysis, AgentWorkflowResult):
            return {"status": analysis.status, "stage": "analyst"}

        # policy-006: HIGH / judge-flag pauses for a recorded human decision.
        #
        # The gate is handed the assessment the Analyst ALREADY produced
        # (gate_result=analysis) rather than an activity name to run. Passing
        # "analyst_activity" here re-ran the Analyst — a second frontier call
        # plus a second judge call, both discarded — and, worse, the gate then
        # read needs_hitl off that SECOND run. The Analyst runs at
        # temperature=0.1, so a re-run could come back MEDIUM/unflagged and the
        # gate would approve on the spot, with no hitl_approved signal, while
        # approve_input still carried the original HIGH assessment. A
        # mandatory-HITL control that a coin flip can skip is not a control.
        approve_input = {
            "assessment": analysis["assessment"],
            "applicant_id": intake["profile"]["applicant_id"],
        }
        result = await self.run_with_hitl_gate(
            None,
            analyst_input,
            resume_activity_name="approve_activity",
            resume_input=approve_input,
            dead_letter_activity_name="dlq_enqueue_activity",
            gate_result=analysis,
            # dlq_enqueue_activity is the framework's GENERIC dead-letter
            # activity: it reads payload/error/tenant_id off its input. Passing
            # tenant_id switches the gate to that envelope — without it a HITL
            # timeout raised KeyError inside the activity and the application
            # was lost rather than parked for a human.
            tenant_id=input.tenant_id,
            gate_id="kyc-decision",
        )
        if isinstance(result, AgentWorkflowResult):
            return {"status": result.status, "stage": "hitl"}
        return result
