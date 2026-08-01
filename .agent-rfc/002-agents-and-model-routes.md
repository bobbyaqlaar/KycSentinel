# RFC 002 — Agents and Model Routes

## Decision

Four model routes, chosen so multi-LLM is structural, not cosmetic:

| Agent | Route | Why |
|---|---|---|
| Intake | `falcon3:3b` @ Ollama | Sovereign/in-border: raw PII text is parsed locally; the scrub runs before ANY cloud call. `degrade_to: null` — a PII route must never fail over to a cloud model. |
| Research | `meta-llama/llama-3.3-70b-instruct` @ OpenRouter | High-volume retrieval + tool loops on the cheap tier, **plus its own one-line screening-summary LLM call** so the route is genuinely exercised, not only a degrade target (E2). |
| Analyst | `anthropic/claude-sonnet-4.5` @ OpenRouter (frontier) | The one expensive judgment call; streamed (`complete_stream`, TTFT budget); degrade ladder → research → intake (F5). |
| Judge | `gemini-3-flash-preview` @ Google AI Studio (**cross-vendor**, distinct from Analyst) | Judge/actor separation: the model grading a rationale must not be the one that wrote it, or the separation is nominal (E3). **No `degrade_to` — the only role without one.** See "Why the judge does not degrade" below. |

## The rating floor is enforced on evidence, not on the rating

`check_rating_floor` in `agents/judge.py` is deterministic and runs after
citation grounding, independently of it.

The Analyst decides the rating, but some inputs remove that discretion.
policy-003: *"Any hit mandates a HIGH rating and human review before
onboarding."* A sanctions hit is a **fact returned by the screening tool**, not
an opinion, so whether it forces human review must not depend on the model
agreeing.

It previously did. HITL was gated on
`needs_hitl = assessment.rating == "HIGH" or judge.flagged`, and against live
models the Analyst rated an applicant with one confirmed sanctions hit as
MEDIUM, citing five policies — all genuinely retrieved, so grounding passed and
`judge.flagged` was False. Both clauses evaluated False: a sanctions-matched
applicant one step from auto-approval with no human review.

Nothing offline could catch it. The fake gateway derives the rating from the
hit count, so it always returns HIGH and the control looks sound; it fails only
when a real model is asked to agree with a rule it was never obliged to follow.
Grounding does not help either — it proves the citations point at real
documents, not that the rating obeys them.

Floors enforced: any sanctions hit → HIGH (policy-003); two or more adverse
media items → at least MEDIUM (policy-004).

## Why the judge does not degrade

Every other role falls back down the ladder on a provider failure. The judge
does not, and that asymmetry is the decision.

A degraded **actor** produces worse output that a good judge still catches. A
degraded **judge** produces confident verdicts into the same `score` field,
compared against the same threshold, gating the same merges — and nothing
downstream can distinguish them from real ones. Scores are only comparable
against the grader they were calibrated for. We have direct evidence of the
failure mode: local judges marked `kyc_012` down for producing identical
ratings across nationalities, which is precisely what policy-007 requires.

This role previously declared `degrade_to: research`, which was wrong three
ways.

**On the path that gates merges it could not fire.** CI evals call
`scripts/eval_judge.py` → `scripts/cost_router.py`, which does not walk
`degrade_to`; only `runtime/llm_gateway.py` does. When the judge account ran
out of credit the gates went dark while this file promised a reroute.

**Where it could fire, it masked a bug.** `agents/judge.py`'s advisory critique
does go through the gateway — but its result is discarded (the verdict comes
from the deterministic citation and parity checks), while an exception from it
failed the entire application. A call whose *answer* nobody reads could block
onboarding. The degrade hid this by substituting a weaker model to write a
critique nobody reads. That call is now fail-open, which is the real fix.

**It named an actor route.** `research` is the retrieval model the pipeline itself
uses, so the declared fallback pointed the grader at the side of the separation
it exists to be independent of.

The independence check does not cover this either. `agents/judge.py` passes the
ids **declared** in the merged registry to `warn_if_judge_not_independent`, so
it validates configuration and is structurally blind to a runtime substitution.
It is a check on this file, not on what ran.

So an unreachable judge now skips the gate with the provider's message
(framework `run-evals.py`), and the framework records per-case `judged_by`
provenance with a hard failure if one scorecard mixes graders. No verdict is a
better outcome than a verdict you cannot trust.

## Offline mode

`KYC_FAKE_LLM=1` swaps the framework `LLMGateway` for `agents/gateway.py`'s
deterministic `FakeGateway` (same `complete()` shape). Rationale: the
testbed's F-scenarios and CI must run with zero keys/infra, matching the
framework's own unit-test philosophy. Every agent takes `gateway` as an
argument — no module-level singletons — so tests can inject either.

## Acceptance Criteria

- No agent imports a provider SDK or `cost_router` directly; all LLM calls
  go through the gateway object it is handed (SEC-GW-001).
- Intake output validates against `ApplicantProfile` via `parse_llm_json`.
