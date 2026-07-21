# KYC Sentinel — Development Log

Running log of build decisions, in order. Later phases (GitHub CI/CD,
deployment) append below — never rewrite earlier entries.

---

## 2026-07-21 — T1 kickoff: scaffold

- Repo created at `Apps/KYC_Sentinel` per the spec in
  `AgenticFramework/docs/testbed-tenant-spec.md`. Purpose: E2E testbed
  tenant that exercises every AgentSmith layer (5 agents, 4 model routes,
  F1–F8 engineered failure scenarios).
- **Framework linkage:** runtime is imported from the framework checkout via
  `AGENTSMITH_DIR` (same pattern as `examples/oil-price-agent/worker.py`).
  Nothing from `AgenticFramework/scripts/` is vendored — scripts arrive via
  the machine install (`install-ai-stack.sh`), runtime via `AGENTSMITH_DIR`.
- **Offline-first decision:** every agent takes a `gateway` argument; a
  deterministic `FakeGateway` (env `KYC_FAKE_LLM=1`) lets all F-scenarios,
  unit tests, and CI run with zero API keys, zero Ollama, zero Temporal.
  Real routes activate when the env vars exist. This mirrors the framework's
  own "no external infra in unit tests" testing philosophy.
- Opt-in marker `.agenticframework/enabled` + `tenant.yaml` written by hand
  (normally `ai-tenant-init` does this; sandbox has no machine install).
- Budget cap set to $5/month in tenant.yaml — deliberately small so the F5
  degrade-ladder demo fires on a realistic batch (spec §5).
- All applicant data is SYNTHETIC (spec §7 — not real persons, not legal
  advice). Emirates-ID-formatted strings in fixtures use invalid checksums
  on purpose where possible, but are still treated as PII by the guardrail.

## 2026-07-21 — T1: Intake agent

- `agents/intake.py`: PII scrub FIRST (framework `input_guardrail`,
  mode=default → Emirates ID / email / phone / Luhn cards), THEN the LLM
  parse. Scrub counts are returned so the workflow can attach them as span
  attributes — the PDPL decision-path story needs the evidence, not just
  the behavior.
- Structured output via framework `parse_llm_json` + local Pydantic
  `ApplicantProfile`. A parse failure raises `StructuredOutputError` —
  that is exactly what F1 (recoverable step → DLQ edit-and-resume) and
  F2 (self-correction) consume upstream; the agent does NOT try to be
  clever about bad input.
- Model route `intake` pinned to `falcon3:3b` on Ollama in `models.yaml`
  (sovereign/in-border rationale in RFC-002).

## 2026-07-21 — T2: Research agent, tools, RAG corpus

- `agents/tools.py`: three fixture-backed `@tool`s (sanctions_lookup,
  company_registry_lookup, adverse_media_search) registered on a
  **tenant-owned strict ToolRegistry** loading
  `.agent-rfc/security/tool_allowlist.yaml`. `wire_transfer` exists in
  code but NOT in the allowlist — F4 proves deny-by-default with a real
  registered-but-unlisted tool, not a fake name.
- Sanctions matching is deliberately naive substring/alias matching over
  `corpus/sanctions.json` — the point of the testbed is that the
  *golden dataset* catches the alias miss (F-scenario → promotion loop),
  not that the matcher is production-grade.
- RAG: `corpus/policies.json` (synthetic policy snippets) loaded into the
  framework `MemoryVectorStore` (hash embedder — deterministic, no
  model download). Doc ids are the citation vocabulary the Judge later
  validates against (F7).

## 2026-07-21 — T3: Analyst, Judge, workflow, demos

- `agents/analyst.py`: risk rating from deterministic rules (sanctions
  hits, adverse media, missing source-of-funds) + LLM rationale citing
  `[doc-id]` markers. Real mode uses `complete_stream` (TTFT) with
  model_hint="analyst" and the gateway's own degrade ladder (F5); fake
  mode emits the same JSON shape. One fake variant deliberately returns
  broken JSON (F2) and one cites a nonexistent doc (F7).
- `agents/judge.py`: two pure checks, no LLM required in fake mode —
  (a) every citation resolves to a retrieved doc id (hallucination),
  (b) pair parity: same profile, nationality/gender swapped → ratings
  must match (fairness). Real mode adds an LLM-judge critique via
  model_hint="judge", kept separate from the Analyst's route (judge/actor
  separation).
- `workflows/kyc_workflow.py`: subclasses framework `BaseAgentWorkflow`;
  HIGH rating or judge flag → `run_with_hitl_gate`; intake parse wrapped
  in `run_with_recoverable_step` (F1 edit-and-resume path);
  `run_with_self_correction` opt-in for analyst-JSON repair (F2).
- `demo.py` + Makefile `demo-f1` … `demo-f8`, `demo-all`: in-process
  drivers per F-scenario, printing which framework control fired and the
  evidence. Live-Temporal variants documented in README (worker.py +
  trigger_workflow.py) — the in-process drivers are what CI runs.
- Golden dataset seeded with 12 cases from the fixture applicants;
  fairness pairs in `.agent-rfc/fixtures/fairness_evals.json` per the
  framework's pair-parity schema.

## 2026-07-21 — T1–T3: tests green

- `test/` — 4 suites (intake incl. PII scrub + injection fixture, tools
  incl. F4 denial, analyst/judge incl. F6 parity + F7 citation check,
  demo scenarios F1–F8 end-to-end in fake mode). All pass offline against
  the framework runtime imported via `AGENTSMITH_DIR`.
- CI workflow `.github/workflows/ci.yml` written from the framework's
  `ci-python-fastapi.yml` shape: py_compile, pytest (fake mode),
  `run-security-checks.py --mode ci --strict` and eval suites run in the
  framework checkout step — see file comments. NOT yet pushed to GitHub;
  see the CI/CD section placeholder below.

## 2026-07-21 — T1–T3 complete, committed

- Verified offline: **24/24 tests pass**, `demo.py all` fires all eight
  controls (`recoverable_step, self_correction, prompt_guard,
  tool_allowlist, degrade_ladder, fairness_parity, hallucination_gate,
  pii_scrub`). F8 scrub counts observed: `emirates_id: 1, email: 1, card: 1`.
- Initial commit on `main` (Conventional Commits + RFC reference — the
  machine-installed AgentSmith hooks will police subsequent commits once
  this repo is opted in on a provisioned machine; `.agenticframework/enabled`
  is already present).
- Remaining before "live": run `worker.py` against real Temporal + Postgres
  + Phoenix (README "Running live"), then the GitHub push + CI rollout
  below. The security-harness CI step is soft (`|| true`) until the tenant
  `.agent-rfc/security/` pack (agency manifest, NIST profile, risk
  register) is authored — flip to hard-fail then.

## 2026-07-21 — post-build review: what the testbed found

Full write-up: `AgenticFramework/TestbedFeedback-2026-07-21.md`.

- **The testbed earned its keep on day one.** Building this app surfaced a
  High-severity framework gap that no unit test could have caught:
  `complete_stream()` raises `NotImplementedError` for `anthropic` and all
  cloud-native providers, so the TTFT budget cannot apply to the frontier
  model on the latency-critical path — the single most likely production
  shape. Two individually-tested features (TTFT streaming, frontier
  routing) are incompatible when combined; only an integration app
  combines them.
- **E1 FIXED:** `agents/analyst.py` now streams when the provider supports
  it and falls back to `complete()` otherwise (streaming is a latency
  optimisation, never a correctness requirement). Regression test added —
  note the `FakeGateway` had *masked* the bug by aliasing `complete_stream`
  to `complete`, so the test forces the real failure mode explicitly.
  **Lesson for this repo: a test double that is more capable than the real
  thing hides exactly the bugs the testbed exists to find.**
- **Open tenant items** (tracked in the feedback report §C):
  E2 Research agent makes no LLM call (`del gateway`) so the Groq route is
  only a degrade target — give it a real triage call; E3 `judge` and
  `analyst` share a model id, contradicting RFC-002's judge/actor
  separation; E4 CI security step stays `|| true` until the tenant
  `.agent-rfc/security/` pack is authored (blocked on framework G5 —
  nothing seeds those templates into a tenant repo today).
- Suite after the fix: **25 tests pass**, all eight F-scenarios still fire.

## 2026-07-21 — framework fixes landed; tenant adopts them

AgentSmith G1–G4 fixed upstream (framework suite 170 → 198 passing). This
repo now consumes them:

- **`agents/gateway.py` rewritten to subclass `runtime.testing.FakeGateway`.**
  ~60 lines of hand-rolled double → ~45 lines of KYC-specific scripting;
  the CompletionResult shape, call recording, budget simulation and
  streaming rules now come from the framework. `providers={...}` mirrors
  this tenant's real `models.yaml`, so the double enforces the same
  streaming capability the real gateway has.
- Integration friction worth remembering: the tenant's `_respond()` helper
  collided with the framework double's internal method of the same name.
  Fixed upstream by renaming the internal one `_build_result()` and
  documenting `_resolve_text(call)` as the single override hook — a shipped
  base class needs an unambiguous extension point.
- `test/test_intake.py` now uses the framework's `assert_prompt_excludes()`
  helper: "PII never reached the model" is one line and checks every
  recorded call, not just `calls[0]`.
- E1's fallback shim in `agents/analyst.py` **stays** even though the
  framework now streams Anthropic — the analyst route is tenant-configurable
  and could be pointed at a cloud-native provider tomorrow, where the
  framework falls back to `complete()` and reports `ttft_ms=None`.
- Suite still 25 passing; all eight F-scenarios still fire.

**Still open here:** E2 (Research agent makes no LLM call), E3 (judge and
analyst share a model id), E4 (security CI soft-fails — blocked on
framework G5, which is still open: nothing seeds the tenant
`.agent-rfc/security/` pack).

## 2026-07-21 — security pack authored; CI security step is now hard-fail

Framework G5 fixed upstream (`post-checkout` now seeds
`.agent-rfc/security/` from vendored templates, never overwriting), so this
repo no longer has an excuse for `|| true`.

- Authored the four security artifacts with **this app's real content**,
  not placeholders: `risk_register.yaml` carries six residual risks
  (alias-miss under-rating, injection, PDPL PII exposure, ungrounded
  citations, protected-attribute leakage, silent budget degradation), each
  mapped to the controls that mitigate it; `agency_manifest.yaml` declares
  `approve_activity` as the sole high-impact action requiring HITL and says
  why the other three don't; `nist_profile.yaml` names owners and evidence
  artifacts; `tool_allowlist.yaml` was already authored in T2.
- **`.github/workflows/ci.yml` security step is now `--strict` with no
  `|| true`.** Verified locally: `exit=0`.
- `MODERATION_HOOK=optional`, not `required`, in CI — deliberately. The
  harness runner resets the moderator and cannot observe a durable tenant
  registration, so `required` always fails (framework G10, newly filed).
  A real regulated deployment registers a classifier at worker startup;
  that's a deployment-time setting, not a CI one.
- **E4 is now closed.** Still open: E2 (Research agent makes no LLM call)
  and E3 (judge and analyst share a model id).

## 2026-07-21 — G10 fixed upstream; tenant now runs MODERATION_HOOK=required

- **`agents/moderation.py`** — this tenant's real output classifier, declared
  in `tenant.yaml` as `moderation.hook: "agents.moderation:classify_output"`.
  The framework runtime auto-registers it AND the SEC-MOD-001 harness imports
  and smoke-tests it, so the control now proves *this app has a working
  classifier* rather than only that the framework API exists.
- What it enforces, and why these two rules: (a) no Emirates ID / card number
  in output — the input guardrail scrubs prompts, but a model can reconstruct
  PII into the rationale a human reviewer reads, so the output side needs the
  symmetric check; (b) no protected-attribute *justification* (policy-007) —
  matched only in a justifying construction ("because … nationality"), not on
  incidental mentions, so a rationale that merely names a country isn't
  flagged. A rationale justified by nationality is a fairness breach even
  when the rating itself is correct.
- **CI is now `MODERATION_HOOK=required`** (was `optional` with a comment
  explaining that `required` could never pass). Verified locally:
  `--mode ci --strict` exits 0 with evidence *"tenant moderator declared and
  verified (agents.moderation:classify_output)"*.
- Suite: 25 → **35 passing** (10 classifier tests).

---

## CI/CD (GitHub) — pending

_To append when the repo is pushed: repo creation, Actions run links,
eval-scorecard/fairness/hallucination/security gate results, staging
deploy via cd-staging.yml, WIF setup notes._

## Deployment — pending

_To append at deploy time: Cloud Run (or on-prem overlay) details, Phoenix
/ Ops Portal wiring, widget embed, first HITL round-trip evidence,
shadow-eval sampling turn-on, promotion-loop first golden case from
production._
