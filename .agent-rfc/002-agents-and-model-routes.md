# RFC 002 — Agents and Model Routes

## Decision

Four model routes, chosen so multi-LLM is structural, not cosmetic:

| Agent | Route | Why |
|---|---|---|
| Intake | `falcon3:3b` @ Ollama | Sovereign/in-border: raw PII text is parsed locally; the scrub runs before ANY cloud call. `degrade_to: null` — a PII route must never fail over to a cloud model. |
| Research | Groq Llama | High-volume retrieval + tool loops on the cheap tier. |
| Analyst | Claude Sonnet (frontier) | The one expensive judgment call; streamed (`complete_stream`, TTFT budget); degrade ladder → research → intake (F5). |
| Judge | `AGENT_JUDGE_MODEL` (Claude) | Judge/actor separation: the model grading rationale quality is routed independently of the model that wrote it. `degrade_to: null` — a silently downgraded judge is worse than a failed one. |

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
