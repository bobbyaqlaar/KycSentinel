# RFC 001 — KYC Sentinel Architecture

## Objective

Corporate-onboarding (KYC) copilot that doubles as the AgentSmith E2E
testbed: every framework layer must be exercised by at least one observable
scenario (F1–F8). Canonical spec: `AgenticFramework/docs/testbed-tenant-spec.md`.

## Pipeline

submit → Intake (PII scrub → structured parse) → Research (RAG + allowlisted
tools) → Analyst (streamed risk rating + cited rationale) → Judge (citation +
parity check) → auto-approve (LOW) or HITL gate (HIGH / judge flag).

## Files

- `agents/` — intake, research, analyst, judge, tools (one module each)
- `workflows/` — Temporal workflow (BaseAgentWorkflow subclass) + activities
- `corpus/` — synthetic policy + sanctions documents (RAG + tool fixtures)
- `fixtures/applicants.json` — 12 synthetic profiles incl. F-scenario cases
- `demo.py` — in-process F1–F8 drivers (fake mode; CI-runnable)

## Acceptance Criteria

- All F1–F8 drivers pass offline (`KYC_FAKE_LLM=1 make demo-all`)
- `pytest test/` green with zero external infra
- Golden dataset ≥ 12 cases; fairness pairs present
- Strict security harness passes against this repo's `.agent-rfc/security/`

## Non-goals (spec §7)

Real KYC/AML compliance, real sanctions data, gateway function-calling,
multi-turn planner correction.
