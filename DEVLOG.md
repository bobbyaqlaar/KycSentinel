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
