# RFC 002 — Agents and Model Routes

## Decision

Four model routes, chosen so multi-LLM is structural, not cosmetic:

| Agent | Route | Why |
|---|---|---|
| Intake | `falcon3:3b` @ Ollama | Sovereign/in-border: raw PII text is parsed locally; the scrub runs before ANY cloud call. `degrade_to: null` — a PII route must never fail over to a cloud model. |
| Research | `llama-3.3-70b` @ Groq | High-volume retrieval + tool loops on the cheap tier, **plus its own one-line screening-summary LLM call** so the route is genuinely exercised, not only a degrade target (E2). |
| Analyst | `claude-sonnet-4-6` (frontier) | The one expensive judgment call; streamed (`complete_stream`, TTFT budget); degrade ladder → research → intake (F5). |
| Judge | `claude-opus-4-8` (frontier, **distinct from Analyst**) | Judge/actor separation: the model grading a rationale must not be the one that wrote it, or the separation is nominal (E3). The framework logs a warning (`runtime.judging.judge_independence_warning`) if the two ever resolve to the same id. `degrade_to: research` (→ `intake`) — availability wins over strict separation: a hard-failed judge blocks every application behind it, so it degrades through the same chain the Analyst uses rather than taking down the pipeline. Every degrade is logged (`Degraded from %r to %r due to provider error`), never silent, and `judge_independence_warning` still runs against the merged registry either way, so a degrade that collapses judge and analyst onto the same model is caught and logged, just not blocked. |

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
