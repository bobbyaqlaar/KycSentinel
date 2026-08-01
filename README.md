# KYC Sentinel

AgentSmith **E2E testbed tenant**: a corporate-onboarding (KYC) copilot with
5 agents across 4 model routes, built so that every framework layer is
exercised by an observable scenario. Canonical spec:
`AgenticFramework/docs/testbed-tenant-spec.md`. Build history: `DEVLOG.md`.

> Synthetic data only. Not a real KYC/AML product, not legal advice.

## Agents & routes (RFC-002)

Intake (Falcon 3 @ Ollama, sovereign — PII scrubbed *before* parse) →
Research (Llama 3.3 70B @ OpenRouter, RAG + strict-allowlisted tools) →
Analyst (Claude Sonnet 4.5 @ OpenRouter, streamed, degrade ladder → research →
intake) → Judge (Gemini @ Google AI Studio — cross-vendor: citation grounding,
evidence-mandated rating floor, pair parity) → auto-approve (LOW) or HITL
(HIGH / flagged).

Routes are declared per profile in `models.yaml`; `hybrid` is the default and
`local` runs every role on Ollama. Two credentials: `OPENROUTER_API_KEY` and
`GEMINI_API_KEY`.

## Quick start (offline — zero keys, zero infra)

```bash
export AGENTSMITH_DIR=/path/to/AgenticFramework   # or keep it as a sibling dir
make test        # fake gateway, no network
make demo-all    # F1–F8 scenario drivers
make demo-f4     # a single scenario
```

The framework is a real dependency, pinned in `requirements.txt` to
`agentsmith-runtime @ v1.1.0`. `AGENTSMITH_DIR` is only for developing against
a live framework checkout — it takes precedence over the installed package so
your edits there take effect without reinstalling.

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
fairness seeds, security pack · `demo.py` F-drivers · `DEVLOG.md` log.

## CI gates

`.github/workflows/ci.yml` runs offline on every PR: unit tests, the F-scenario
drivers, the framework security harness `--strict` (with
`MODERATION_HOOK=required`), and the **adversarial** eval suite — all without
credentials.

The **scorecard / fairness / hallucination** gates need a judge model. They
skip with a message naming the variable they want rather than failing, so CI
stays green until you opt in. The variable comes from the `judge` role in
`models.yaml` (currently `ANTHROPIC_API_KEY_JUDGE`, its own account for
judge/actor separation) — set that secret and the three gates turn on with no
workflow change.
