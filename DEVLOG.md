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

## 2026-07-21 — E2/E3 closed: all four routes real, judge independent

- **E2** — the Research agent now makes its own `model_hint="research"` call
  (the Groq cheap tier): a one-line factual screening brief over the
  collected evidence, stored on `ResearchFindings.screening_summary`. It is
  NOT a rating — the tool findings still drive the decision, and a
  summary-call failure degrades to a deterministic brief rather than
  aborting the application. `demo.py f5` now prints
  `routes actually used this run: ['intake', 'research', 'analyst', 'judge']`
  — all four, not three plus a degrade target.
- **E3** — judge split onto a distinct model: analyst `claude-sonnet-4-6`,
  judge `claude-opus-4-8`. A rationale's own author is the worst-placed
  reviewer of its soundness, so "judge/actor separation" needed to be a
  config fact, not a slogan. The framework gained
  `runtime.judging.judge_independence_warning`; the tenant judge calls it
  once against the merged registry and logs if the two ever collapse to one
  id. A tenant test forces that misconfiguration and asserts the warning
  fires (proving the wiring, not just the helper).
- Suite: 36 → **39 passing**; all eight F-scenarios still fire; strict
  security harness still exits 0.

**KYC Sentinel is now feature-complete against its spec** (all 5 agents /
4 routes / F1–F8 real). Remaining work is deployment only — the sections
below.

---

## 2026-07-22 — pushed to GitHub, CI green

- Repo pushed to `github.com/bobbyaqlaar/KycSentinel` (was local-only).
  First CI run failed: `ci.yml` checks out `bobbyaqlaar/AgentSmith` and
  `pip install -e`s it, but the framework's own `main` (which has the G6
  packaging commit adding `pyproject.toml`) had never been pushed to
  GitHub — 8 local commits sat unpushed on the framework side. Pushed
  `AgentSmith` main, reran: **CI green**
  ([run](https://github.com/bobbyaqlaar/KycSentinel/actions/runs/29955428301)).
- Eval-scorecard/fairness/hallucination gates are not yet wired as
  separate CI jobs for this tenant — `ci.yml` today runs unit tests +
  F-scenario drivers + the strict security harness only. Adding the
  reusable `eval-*.yml` callers is follow-up work, not blocking.

## 2026-07-22 — GCP staging smoke deploy (Cloud Run Job)

**Scope decision:** `worker.py` is a Temporal poller with no HTTP listener
and no standalone-run mode — it connects to Temporal at startup. Standing
up the full "Running live" stack (Temporal, Postgres, Ollama for the
sovereign `intake` route, Phoenix, real Anthropic/Groq keys) in the new
`kycsentinel` GCP project is a separate, bigger decision, deferred. This
pass proves the **deploy pipeline** end-to-end instead: WIF auth, this
repo's own Dockerfile building on Cloud Build, and the actual pipeline
(`demo.py`'s F1–F8 drivers, `KYC_FAKE_LLM=1` — same fake gateway CI uses)
executing as a **Cloud Run Job** in `kycsentinel`.

- **GCP project:** `kycsentinel` (number `857211089844`), region
  `us-central1`. APIs enabled: Cloud Run, Cloud Build, Artifact Registry,
  IAM, IAM Credentials, STS, Cloud Resource Manager.
- **WIF:** `github-actions-pool` / `github-provider`, attribute-condition
  scoped to `assertion.repository=='bobbyaqlaar/KycSentinel'`. SA
  `github-deployer@kycsentinel.iam.gserviceaccount.com` holds
  `roles/run.admin`, `roles/artifactregistry.writer`,
  `roles/iam.serviceAccountUser`, `roles/cloudbuild.builds.editor`,
  `roles/storage.admin`.
- **Two real gaps found and fixed along the way** (both are permanent
  fixes, not deploy-only workarounds):
  1. `requirements.txt` had the `agentsmith-runtime` git dependency
     **commented out** (no `v1.0.0` tag exists yet to pin to), so a
     standalone `docker build` — exactly what Cloud Run `--source` deploy
     does — installed no framework at all. Repointed to `@main`.
  2. The `python:3.11-slim` base image has no `git`, which pip needs to
     clone that dependency. Added `apt-get install git` as a Dockerfile
     layer. Verified locally (`docker build` + `docker run ... demo.py
     all`) before pushing to CI, both green.
  3. **GCP-side, discovered live:** new projects no longer auto-grant the
     default compute service account (`857211089844-compute@developer...`)
     any project roles. Cloud Run's `--source` deploy uses that SA under
     the hood via Cloud Build; it had zero permissions and failed reading
     its own source-upload bucket (`storage.objects.get` denied). Granted
     it `roles/storage.objectViewer`, `roles/artifactregistry.writer`,
     `roles/logging.logWriter`. Also had to pre-create the
     `cloud-run-source-deploy` Artifact Registry repo by hand — the
     `github-deployer` SA has `artifactregistry.writer`, not `.admin`, so
     it can't auto-create repos (deliberate least-privilege choice over
     widening the role).
- **`.github/workflows/cd-staging.yml`** (new) + **`.github/actions/gcp-auth`**
  (vendored from the framework, unmodified) — `staging` GitHub Environment
  created with `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`,
  `GCP_PROJECT_ID` secrets.
- **Result:** Cloud Run Job `kyc-sentinel-smoke` deployed and executed —
  `EXECUTION_SUCCEEDED`, all eight F-scenarios fired, `Container called
  exit(0)`
  ([run](https://github.com/bobbyaqlaar/KycSentinel/actions/runs/29956358039)).
  Verified via `gcloud logging read` against the job's own Cloud Logging
  output, not just the GitHub Actions log.

**Still open — the actual "Running live" milestone:** Cloud SQL
(`BUDGET_BACKEND=postgres`), a Temporal server, Ollama for the sovereign
`intake` route, Phoenix, and real Anthropic/Groq API keys (user declined
to wire these in this pass — deferred). Once those exist, swap
`cd-staging.yml`'s Cloud Run Job for a `gcloud run deploy` of `worker.py`
as a long-running service (`--no-cpu-throttling --min-instances=1`,
OPERATIONS.md §4), point it at the real `TEMPORAL_ADDRESS`, and pick up
from there: Phoenix/Ops Portal wiring, widget embed, first HITL
round-trip, shadow-eval sampling turn-on, first production golden case.

## 2026-07-28 — review fixes: HITL bypass, vacuous demo guards, PII symmetry

Cross-repo docs+code review (framework + this tenant). Five tenant-side
correctness fixes; the framework changes they depend on are in AgentSmith's
CHANGELOG under [Unreleased] "Review findings (2026-07-28)".

- **HITL bypass on the decision gate (the serious one).** The workflow ran
  `run_with_hitl_gate(gate_activity_name="analyst_activity", ...)` *after* it
  had already run the Analyst via `run_with_self_correction`. The framework
  gate executes the named activity and reads `needs_hitl` off **that** run, so
  every HIGH application re-ran a temperature=0.1 frontier call plus the
  judge — both discarded — and if the re-run came back MEDIUM/unflagged the
  gate approved on the spot, no `hitl_approved` signal, while `approve_input`
  still carried the original HIGH assessment. policy-006's "mandatory HITL"
  was skippable by a coin flip. The gate now takes `gate_result=analysis` (new
  framework parameter) — the decision already made — and runs no second
  Analyst call.
- **HITL timeout lost the application.** The same call passed the framework's
  generic `dlq_enqueue_activity`, which reads `payload`/`error`/`tenant_id`
  off its input, while the gate built the flattened
  `{**gate_input, "error": ...}` shape carrying none of them → `KeyError`, so
  a 24h timeout failed the workflow instead of parking it. Now passes
  `tenant_id=` / `gate_id=`, which selects the generic DLQ envelope.
- **F1/F2 drivers were vacuous.** Both raised their guard `AssertionError`
  *inside* a `try` guarded by `except Exception`, which caught it — so with
  the control fully broken, `make demo-all`, `demo.py all` in CI and the Cloud
  Run smoke job all printed "the control fired" and returned success.
  Extracted `_expect_rejection()`, which asserts outside the except and pins
  the expected exception type (F4 now uses it too). New test stubs intake to
  always succeed and asserts both drivers fail.
- **Moderation hook disagreed with the input guardrail.** `agents/moderation.py`
  hand-rolled `(?:\d[ -]?){13,19}` with no Luhn check, so an 18-digit registry
  filing reference in a rationale was blocked as a leaked card while the
  pre-call scrub left the identical digits alone — the exact pre/post-call
  divergence `runtime/luhn.py` was extracted to make impossible. Now calls the
  framework's new `input_guardrail.detect_pii()`, so the two sides cannot
  disagree by construction.
- **PROMPT_GUARD mode was ignored at the front door.** `pipeline.py` called
  `scan_prompt`, which reports `blocked=True` on any hit regardless of mode,
  so `PROMPT_GUARD=off` still blocked and `warn` — the observe-first tier
  added as framework G9 — was unusable in this tenant. Now
  `apply_prompt_guard` + `is_enforcing`, with `PromptGuardBlockedError` caught
  so `strict` yields the same human-review outcome rather than a crash
  (found by the new mode tests, not assumed). Guard reasons ride along on the
  `Decision` in warn mode.
- **Tool spans carried no tenant.** `ToolRegistry(tenant_id="kyc-sentinel")` —
  the `agent.tool.*` spans were the only ones without `tenant.id`, so a
  per-tenant Phoenix filter hid every tool call.

**Verification:** tenant suite 39 → 49 passing; `demo.py all` fires all eight
controls; `run-security-checks.py --mode ci --strict` with
`MODERATION_HOOK=required` exits 0. Framework suite 289 → 302 passing
(`pytest runtime/test scripts/test`).

**Not done in this pass** (rest of the review's plan): remove the dead
`NotImplementedError` streaming shim in `agents/analyst.py`, cache the corpus
in `agents/tools.py`, add `.dockerignore`, wire the eval gates into `ci.yml`.

## 2026-07-29 — review phase 2: cleanup, plus a harness that graded the wrong repo

Framework-side changes are in AgentSmith's CHANGELOG under [Unreleased]
"Review findings, phase 2". Tenant-side:

- **The security harness was never grading THIS repo.** ci.yml's step is
  labelled "Security harness (strict) against this tenant", but
  `run-security-checks.py` resolved the `.agent-rfc/security/` pack from its
  own install location, so every run graded the framework's pack. The risk
  register, agency manifest and tool allowlist authored here on 2026-07-21 had
  never been read by anything. Fixed upstream (`_tenant_root()` resolves from
  cwd); re-verified locally — strict + `MODERATION_HOOK=required` still exits 0,
  now against this repo's own pack.
- **`.dockerignore` added.** `COPY . .` was baking `.env` and the full `.git`
  into the worker image on the documented local `docker build`.
- **Corpus cached.** `agents/tools.py:_load` re-read and re-parsed
  sanctions.json / adverse_media.json on every tool call — 4 per application,
  120 for F5's 30-application batch. Same module-level cache
  `agents/research.py` already used for the policy corpus.
- **Dead streaming shim removed.** `_complete_maybe_stream`'s
  `except NotImplementedError` branch was unreachable in both real and fake
  mode since framework G1, and its comment claimed the opposite of the shipped
  behaviour. `test_analyst_survives_provider_without_streaming` was rewritten
  to assert the framework's guarantee against a genuinely non-streaming
  provider (bedrock) instead of monkeypatching a raise the gateway no longer
  performs — a test that simulates deleted behaviour proves nothing.
- **Vendored-action drift check** in ci.yml: `.github/actions/gcp-auth` is a
  verbatim copy of the framework's, and nothing kept them in step. CI now diffs
  it against the framework checkout it already clones.

**Verification:** tenant suite 49 → 50 passing; `demo.py all` fires all eight
controls; strict harness exits 0. Framework suite 310 → 322. Phase 1 fixes
re-proved end to end: no analyst re-run in the HITL gate, F1/F2 fail loudly
when their control is stubbed out, moderation and the pre-call guard agree on
a non-Luhn 18-digit run, all five PROMPT_GUARD modes behave per contract,
tool registry carries tenant.id.

## 2026-07-29 — phase 3: pinned to a real release, eval gates wired

- **Pinned to `agentsmith-runtime@v1.1.0`.** The framework cut its first
  actual release today (1.0.0 was documented but never tagged), so
  `requirements.txt` no longer tracks a moving `main`. Every `docker build` /
  Cloud Run `--source` deploy of this repo now resolves the same framework
  commit — verified with a `pip install --dry-run`, which resolved
  `agentsmith-runtime-1.1.0` at 5897e8a. `framework.version` moved to `1.1.x`.
  Adopting a new framework version is now a deliberate edit to that line.
- **Eval gates wired into ci.yml**, closing the gap between
  testbed-tenant-spec.md §3's claim and what CI actually ran (nothing).
  - **adversarial** runs unconditionally on every PR — it is deterministic
    pattern matching with no judge model, so it needs no secrets. Verified
    locally: 7/7 cases, 0.00 miss rate.
  - **scorecard / fairness / hallucination** run when `ANTHROPIC_API_KEY` is
    present, since the judge resolves to this repo's declared
    `claude-opus-4-8`. Without the secret they are skipped, not failed — the
    same "optional infra never fails CI" posture as the `gcp-auth` action. Add
    the secret and they become real gates with no workflow change.
  - Deliberately NOT the framework's reusable `eval-*.yml` workflows: those
    run `python3 scripts/run-evals.py` against the calling repo, and this
    tenant has no `scripts/` of its own. It uses the framework checkout ci.yml
    already clones, exactly like the security-harness step.
- **Framework bug this surfaced:** `run-evals.py` returned exit 2 for "too few
  cases to gate", which failed the CI step — so a fresh `ai-tenant-init` repo
  went red on its first push for not yet having a golden dataset, and
  eval-scorecard.yml's own comment ("exit 2 = skip gracefully (not a
  failure)") described behaviour the code never had. Fixed upstream; the CLI
  boundary now maps skip to 0.

**Verification:** tenant suite 50 passing; `demo.py all` fires all eight
controls; strict security harness exits 0 against this repo's own pack;
adversarial eval gate passes offline.

## 2026-07-29 — eval fixtures pinned; the gates now judge THIS app

Checking the three dormant gates (rather than only proving they skip) found
they would have graded the wrong system entirely.

- **The gates judged the framework's code-generation pipeline.** None of the 12
  golden or 4 fairness cases carried an `actual_output`, so `run-evals.py` fell
  through to `local_agent_stack.run_pipeline` — the generic
  Architect→Developer→Validator *code* pipeline — and judged its output against
  KYC onboarding references. Confirmed by running it: all four fairness cases
  scored 0.00, with `architect_plan_generated` / `developer_code_generated` in
  the log and judge notes about generated code. `--fail-below 0.80` would have
  blocked merges on a number measuring nothing.
- **Fixed by pinning.** `scripts/pin_eval_outputs.py` (`make pin-evals`) runs
  each case's applicant through the real `process_application` in fake mode —
  deterministic, so a re-run on unchanged code is a no-op diff — and records
  what the app produces. The suites are now regression tests: a behaviour
  change shows up as a score drop instead of silently passing.
  Result: **507s → 18s** for the fairness suite (no pipeline generation), and
  it passes **1.000 with pair parity 1.000** on a capable judge.
- **Two real defects the pinning surfaced**, both fixed: `kyc_012` is a *pair*
  case whose reference asks for identical ratings, so pinning one side scored
  0.20 — it now pins both; and the rendered output dropped the company registry
  status that several references ask for.
- **The gender fairness pair had no applicant behind it** — it existed only as
  prompt text, so it could never run through the pipeline. Added `fair-013a/b`
  (identical but for the name's gender marker) plus a corpus adverse-media
  entry, so the pair shares a non-trivial MEDIUM rather than a trivial LOW.
- **Guard:** `test/test_eval_fixtures_pinned.py` fails if a case is unpinned,
  unmapped, or has drifted from what the pipeline produces — verified by
  planting stale text and watching it fail.

**Not resolved: the golden threshold is uncalibrated.** 0.80 is the framework
default and has only ever been scored by local Ollama judges, which proved
unreliable here — qwen2.5 marked `kyc_012` down for producing "identical
outputs despite the differing nationalities", i.e. penalising the exact
behaviour policy-007 requires, and made factually false claims about missing
citations that were present. Calibrate against the real judge before trusting
this as a merge gate; noted in ci.yml at the step.
