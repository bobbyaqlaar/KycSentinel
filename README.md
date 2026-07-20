# KYC Sentinel

AgentSmith **E2E testbed tenant**: a corporate-onboarding (KYC) copilot with
5 agents across 4 model routes, built so that every framework layer is
exercised by an observable scenario. Canonical spec:
`AgenticFramework/docs/testbed-tenant-spec.md`. Build history: `DEVLOG.md`.

> Synthetic data only. Not a real KYC/AML product, not legal advice.

## Agents & routes (RFC-002)

Intake (Falcon 3 @ Ollama, sovereign — PII scrubbed *before* parse) →
Research (Groq, RAG + strict-allowlisted tools) → Analyst (Claude frontier,
streamed, degrade ladder → Groq → local) → Judge (independent judge route:
citation grounding + pair parity) → auto-approve (LOW) or HITL (HIGH/flag).

## Quick start (offline — zero keys, zero infra)

```bash
export AGENTSMITH_DIR=/path/to/AgenticFramework   # or keep it as a sibling dir
make test        # 24 tests, fake gateway
make demo-all    # F1–F8 scenario drivers
make demo-f4     # a single scenario
```

## The F-scenarios

| # | Demo | Framework control proven |
|---|---|---|
| F1 | malformed dob | recoverable step → DLQ → portal edit-and-resume |
| F2 | broken model JSON | structured-output gate → opt-in self-correction |
| F3 | embedded injection | prompt_guard flags before any model call |
| F4 | `wire_transfer` | tool allowlist deny-by-default (SEC-TOOL-001) |
| F5 | $5 monthly cap | gateway degrade ladder analyst→research→intake |
| F6 | nationality swap | fairness pair parity (policy-007) |
| F7 | ghost citation | hallucination flag blocks auto-approval |
| F8 | Emirates ID + card | pre-call PII scrub, counts recorded |

## Running live

1. `cp .env.example .env`, unset `KYC_FAKE_LLM`, fill provider keys.
2. Backends: Postgres (`BUDGET_BACKEND=postgres`), Temporal, Phoenix — see
   `OPERATIONS.md` §0 in the framework repo.
3. `make worker` then `python3 trigger_workflow.py sanc-005` → workflow
   pauses at the HITL gate; approve via the Ops Portal (or send the
   `hitl_approved` signal). `malf-009` parks in the DLQ for edit-and-resume.

## Layout

`agents/` one module per agent + `tools.py` + `gateway.py` (fake/real) ·
`pipeline.py` engine-agnostic pipeline · `workflows/` Temporal workflow on
`BaseAgentWorkflow` · `corpus/` synthetic policies/sanctions/media ·
`fixtures/applicants.json` 12 profiles · `.agent-rfc/` RFCs, golden +
fairness seeds, tool allowlist · `demo.py` F-drivers · `DEVLOG.md` log.
