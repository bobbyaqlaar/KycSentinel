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
actor routes and `GEMINI_API_KEY` for the judge — separate accounts on purpose,
so exhausting an actor's quota cannot also take out its reviewer.

## Quick start (offline — zero keys, zero infra)

```bash
export AGENTSMITH_DIR=/path/to/AgenticFramework   # or keep it as a sibling dir
make test        # fake gateway, no network
make demo-all    # F1–F8 scenario drivers
make demo-f4     # a single scenario
```

The framework is a real dependency, pinned in `requirements.txt` — read the pin
there rather than here, because it moves and this line has already been left
behind once (it said `v1.1.0` through the v1.2.0 and v1.3.0 bumps).
`AGENTSMITH_DIR` is only for developing against
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
   pauses at the HITL gate. Record the decision with
   `python3 resolve_hitl.py <workflow-id>` (add `--reject` to refuse); the id
   is printed by `trigger_workflow.py`. `malf-009` parks in the DLQ for
   edit-and-resume, which IS an Ops Portal action ("Replay with edits").

   The Ops Portal does not approve HITL gates — it does DLQ replay and
   discard. This line used to say it did, and no sender shipped here either,
   so policy-006's "recorded human decision" had no reachable path and a HIGH
   application could only time out.

## Layout

`agents/` one module per agent + `tools.py` + `gateway.py` (fake/real) ·
`pipeline.py` engine-agnostic pipeline · `workflows/` Temporal workflow on
`BaseAgentWorkflow` · `corpus/` synthetic policies/sanctions/media ·
`fixtures/applicants.json` 15 profiles · `.agent-rfc/` RFCs, golden +
fairness seeds, security pack · `demo.py` F-drivers · `DEVLOG.md` log.

## CI gates

`.github/workflows/ci.yml` runs offline on every PR: unit tests, the F-scenario
drivers, the framework security harness `--strict` (with
`MODERATION_HOOK=required`), and the **adversarial** eval suite — all without
credentials.

The **golden / fairness / hallucination** gates need a judge model. The variable
comes from the `judge` role in `models.yaml` — currently `GEMINI_API_KEY`
(`gemini-3-flash-preview`, a different vendor from the Claude analyst whose
rationale it grades, so judge/actor separation is real rather than nominal). Without it each gate skips with a
message naming the variable it wants rather than failing, so a fork with no
secrets stays green.

The judge moved here on 2026-08-19, after Groq decommissioned the entire Llama
family and `llama-3.3-70b-versatile` began returning HTTP 404 on every call.
Worth knowing how that presented, because it is the failure mode this repo's
own gates are designed around: **nothing went red.** Each suite reported
`NO VERDICT (judge unreachable)` and exited 0 — correct, since a judge that
cannot be reached is an infrastructure failure rather than a quality result —
so CI stayed green while grading nothing for several days. If you take one
operational habit from this repo, take this one: on a judged gate, read the
run's output rather than trusting the tick.

With the secret set, **only golden runs on every push.** Fairness and
hallucination run on alternating crons, because this judge's free tier allows
20 requests a day and the three suites need 22 — a full cycle goes red on quota
rather than on quality:

| Trigger | Suites | Judge calls |
|---|---|---|
| push / PR touching any non-`.md` file | golden | 12 |
| push / PR touching **only** `.md` files | none | 0 |
| cron Mon/Wed/Fri 09:00 UTC | fairness | 4 |
| cron Tue/Thu/Sat 09:00 UTC | hallucination | 6 |
| `workflow_dispatch` (`judged_suites` input) | `all` by default, or one suite | 4–22 |

The documentation-only skip exists because a README commit on 2026-09-01 spent
the day's judge budget — golden graded 6 of 12, took 429 on the rest, and the
local run queued to grade golden properly lost its window. Prose cannot change
what the judge says about the agents' output. Everything else still runs on a
docs change: unit tests, the F-scenario drivers and the security harness, since
a README edit can contradict the F-table it documents. The skip is announced in
the run rather than passing quietly, and it fails **open** — any push where the
changed-file list cannot be determined runs the gate.

This paragraph used to claim all three ran on every push, on the strength of one
22-call cycle completing on 2026-08-19 at `EVAL_RPM=12`. Re-measured 2026-08-23,
the limit is hard and it is daily:

    429 RESOURCE_EXHAUSTED
    quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
    quotaValue: 20   model: gemini-3-flash

so the split stands, and `ci.yml` has enforced it throughout — the README was
the only place that said otherwise. Worth stating plainly, because a doc that
overstates which gates run is the same failure this file spends a page warning
about: something that reads as guarded and is not. Two suites out of three were
never covering a push, and nothing about a green tick said so.

The daily budget resets at midnight America/Los_Angeles, and that is the only
thing that clears it. Probing tells you the per-minute window is open; it says
nothing about how much of the day's 20 remain. Run two suites at once, or grade
locally at the same time, and they starve each other. A gate that reports two
days late is a weaker gate, but a gate that silently grades nothing is no gate
at all — so read the run.

`judged_suites` is how you re-run one suite against a fixture change without
paying for the other two.

Thresholds are **not** passed on the command line. They live on the `judge` role
and were measured against the grader that produced them, so repointing the judge
cannot leave a stale number behind.

## Licence

GNU Affero General Public License v3.0 — see [LICENSE](./LICENSE).

The same licence as [AgentSmith](https://github.com/bobbyaqlaar/AgentSmith), the
framework this tenant exercises. Deliberately matched: a permissive reference
implementation wrapped around a copyleft framework sends a confusing signal
about what you may actually do with the pair.

This repository is a **testbed tenant**, not a KYC product. It exists to prove
the framework's controls against a realistic domain — sovereign PII routing,
judge/actor separation, fairness pair parity, citation grounding, HITL gates.
Do not deploy it as a compliance system.
