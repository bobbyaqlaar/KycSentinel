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
`local` runs every role on Ollama. Two credentials: `OPENROUTER_API_KEY` for the
actor routes and `GROQ_API_KEY` for the judge — separate accounts on purpose, so
exhausting an actor's quota cannot also take out its reviewer.

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

The **golden / fairness / hallucination** gates need a judge model. The variable
comes from the `judge` role in `models.yaml` — currently `GROQ_API_KEY`
(`llama-3.3-70b-versatile`, a different vendor from the Claude analyst whose
rationale it grades, so judge/actor separation is real rather than nominal). Without it each gate skips with a
message naming the variable it wants rather than failing, so a fork with no
secrets stays green.

With the secret set, the three gates run on **different triggers**, because they
do not all fit in one day's judge quota — 22 calls against a free tier that
allows 20 a day:

| Trigger | Suite | Judge calls |
|---|---|---|
| push / PR | golden | 12 |
| cron Mon/Wed/Fri 08:30 UTC | fairness | 4 |
| cron Tue/Thu 08:30 UTC | hallucination | 6 |
| `workflow_dispatch` (`judged_suites` input) | one chosen suite | 4–12 |

No gate is removed or loosened — each runs less often. Fairness and
hallucination alternate days so the heaviest day (a push plus the hallucination
cron) is 18, inside the cap. **The free tier affords one graded push per day**;
a second errors on quota. A paid tier removes that with no other change, since
the route and its calibrated threshold travel with the `judge` role in
`models.yaml`.

Thresholds are **not** passed on the command line. They live on the `judge` role
and were measured against the grader that produced them, so repointing the judge
cannot leave a stale number behind.
