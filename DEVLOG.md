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

## 2026-07-29 — the gates run; the judge has no credits

The pinned fixtures went in green locally and the gate still failed 12/12 at
`score=0.00` with empty notes. The fixtures were never the problem.

**What the failure actually was.** Every judge call returned HTTP 400, and
`raise_for_status()` reports only the status line — so a malformed request, a
dead model id and an unpayable account are indistinguishable. Two hypotheses
were chased and both were wrong (a runtime/scripts version skew; an invalid
model id — `claude-opus-4-8` is valid and the request body was correct). The
fix was to stop guessing and print the response body, at which point CI said it
outright:

> `Your credit balance is too low to access the Anthropic API. Please go to
> Plans & Billing to upgrade or purchase credits.`

Valid key, well-formed request, valid model, unfunded account. The 400-not-401
was itself the tell: a bad key returns 401, so authentication had succeeded.

**Consequence for CI.** `main` was red because of an account billing state, not
a regression. Framework `run-evals.py` now exits 0 when *every* case errors,
printing the provider's message — no verdicts means no quality signal to gate
on. Partial errors still fail. The output stays honest rather than quietly
passing:

```
⏭️  Skipping golden gate: no case received a verdict — the judge was unreachable.
    LLM call failed [forced / claude-opus-4-8]: HTTP 400 ... credit balance is too low
```

Adversarial is unaffected and remains a real gate on every PR — it is
pattern-matched, with no judge model and no credential.

**Open, and not a code task:** fund the account behind
`ANTHROPIC_API_KEY_JUDGE` (or repoint the `judge` role at a funded route).
Until then the three judge-backed gates skip, and the golden threshold
(`--fail-below 0.80`) stays uncalibrated — it has never been scored by the
configured judge. Calibrate on a green `main` before trusting it as a merge
gate.

## 2026-07-29 — the judge does not degrade, and an advisory call stops being fatal

Framework review Phase 2. The `judge` role declared `degrade_to: research`,
justified in a six-line comment as "availability wins over strict separation".
Removing it turned out to expose a real bug.

**The declared fallback was wrong three ways.** On the path that gates merges
it could not fire — CI evals go through `scripts/cost_router.py`, which does
not walk `degrade_to`; only `runtime/llm_gateway.py` does. So when the account
hit "credit balance is too low", the gates went dark while `models.yaml` said
they would reroute. It named an **actor** route (`research` is the Groq model
the pipeline itself uses), pointing the grader at the side of the separation it
exists to be independent of. And both `models.yaml` and RFC-002 claimed
`warn_if_judge_not_independent` would catch such a collapse — it cannot.
`agents/judge.py` passes the ids **declared** in the merged registry, so it
validates this file, not what ran.

**Where the degrade could fire, it was masking a defect.** `run_judge` makes an
advisory critique call whose result is discarded — the verdict comes from the
deterministic citation and parity checks — but an exception from it propagated
and failed the whole application. A call whose *answer* nobody reads could
block onboarding. The degrade hid it by substituting a weaker model to write a
critique nobody reads. That call is now fail-open; the degrade is gone.

Two tests pin it: a credit-exhausted judge does not block an application, and a
citation outside the retrieved set still flags with the judge unavailable — so
fail-open does not become fail-blind.

**Why not just keep the degrade.** A degraded actor produces worse output that
a good judge still catches. A degraded judge writes confident verdicts into the
same `score` field, against the same threshold, gating the same merges. Local
judges were measurably unreliable on these very cases — qwen2.5 marked
`kyc_012` down for producing identical ratings across nationalities, which is
exactly what policy-007 requires. The framework now records per-case
`judged_by` and fails a scorecard that mixes graders.

Still open: the golden threshold remains uncalibrated, and the judge account
still needs credit before the three gates produce real verdicts.

## 2026-07-29 — the judge config was not what models.yaml appeared to say

Framework Phase 4 found that `load_model_registry` shallow-merged this repo's
`judge` role over the framework's, so the role this file declares was not the
role the code used. Merged, it carried:

- `endpoint: ${OLLAMA_BASE_URL}/v1` inherited from the framework's local judge —
  so the **runtime** judge posted `claude-opus-4-8` requests at the Ollama host.
  The eval path escaped only because `cost_router` used to ignore `endpoint`.
- `degrade_to: fast` — the previous entry's removal of `degrade_to: research`
  did **not** take effect, because the framework's value showed through. The
  judge documented here as having no fallback still degraded, to `smollm2`.

A tenant entry declaring a different `id` is now taken wholesale rather than
merged, so this file's judge role means what it reads as. Verified: the merged
config is exactly the keys declared here, and `_degrade_chain("judge")` is
`["judge"]`. No change was needed in this repo.

The judge can now also be pointed at xAI or Google from `models.yaml` — see the
worked options in the framework's `runtime/models.yaml`. Cross-vendor is the
stronger choice for independence: `judge_independence_warning` only catches
identical ids, so `claude-opus-4-8` grading `claude-sonnet-4-6` passes the check
while both share a lineage. The threshold must be recalibrated per judge
(`fail_below` on the role), and `scripts/verify_judge_route.py` proves a route
reaches its declared provider before it gates merges.

## 2026-07-30 — calibrating the golden threshold found the gate was measuring a stub

Goal was to set `--fail-below` from real judge behaviour. The first real
scorecard (0.842) held up, but four cases scored 0.40–0.60 and the reasons were
not application defects.

**Three of four were the same complaint: wrong policy cited.** `kyc_006` is a
sanctions alias hit; the reference expects `policy-003` (Sanctions screening
SOP, "including known aliases") and is correct. The cause was
`agents/gateway.py`'s FakeGateway picking citations positionally —
`re.findall(...)[:2]`, the first two policy ids appearing in the prompt. Across
the suite 8 of 12 cases cited something other than the governing policy, and
`policy-008` (Citation grounding — a *meta*-policy about how rationales must
cite) appeared as a rating **basis** in 6 of them. CI runs `KYC_FAKE_LLM=1`, so
the golden gate was grading that stub, not the pipeline's judgement.

**Fixing the stub was not enough.** `agents/research.py` pinned `policy-005` +
`policy-003` unconditionally — surfacing the sanctions SOP for applicants with
no sanctions hit, and never surfacing `policy-004` for applicants who *had*
adverse media. Since `policy-008` treats a citation outside the retrieved set
as a hallucination, the Analyst *could not* legitimately cite the governing
policy: retrieval never put it in scope. Both now key off the evidence actually
gathered.

**Measured, same judge both sides (qwen2.5, local):** overall **0.621 → 0.775**,
no case regressed, one erroring case fixed. Governing policy correctly cited:
3/8 → 6/8. The two remaining (`kyc_004` identity, `kyc_012` fairness) are cases
where the citation is not the substance — both already score well.

**Judge availability, verified live.** Anthropic 400 (no credit); xAI 403 (team
has no credits); Gemini 2.5/2.0/1.5 all 429 with free-tier limit 0. Only
`gemini-3-flash-preview` works, on a small free-tier quota (~20 requests per
window), which is why the post-fix Gemini rerun could not complete — 10 of 12
cases 429'd. The judge is now that model, cross-vendor against the Anthropic
analyst, which is stronger independence than opus-over-sonnet ever was.

**The threshold is still not calibrated, and deliberately not set from these
numbers.** qwen2.5 scored `kyc_012` 0.00 where Gemini scored 1.00 — it marks the
fairness pair down for producing identical ratings across nationalities, which
is exactly what policy-007 requires. It is a valid A/B instrument and a bad
judge. Re-run the golden suite on `gemini-3-flash-preview` once quota resets,
three clean passes, then set `--fail-below` a margin below the observed floor.
Pre-fix it sat at 0.842–0.858 against 0.80 — four points of headroom on a number
dominated by an artifact that is now gone.

## 2026-07-30 (later) — threshold calibrated; tenant F3/F7 fixtures

**Golden threshold set to 0.90**, on the `judge` role in `models.yaml` rather
than in CI. A score is only comparable to a threshold set for the grader that
produced it, so the number travels with the role — repoint the judge and it
cannot silently leave a stale value behind. CI no longer passes `--fail-below`,
which would have overridden it.

Measured on `gemini-3-flash-preview`: **0.842 / 0.858 pre-fix** (two clean
passes, spread 0.016) → **0.967 post-fix** (one clean pass, 11 of 12 cases at
1.00). The lift is the citation work from earlier today. 0.90 leaves ~0.07 of
headroom: above the 0.85 pre-fix regime, so a regression to the old citation
behaviour fails, and loose enough for several times the observed variance. Only
one clean post-fix pass was possible — the free tier allows roughly one 12-case
run per window — so it is deliberately not tighter.

**The judge found a real fixture bug.** `kyc_004` scored 0.60: "hallucinated an
'email' count that was not in the input". The applicant record (`pii-004`) does
contain `omar@rashidventures.example`, so the scrubber was right and the case
*description* was wrong — it listed only the Emirates ID and card. Corrected,
along with a reference that now specifies the rating as well as the PII
handling.

**F3 — tenant adversarial fixtures.** The gate graded the framework's 7 base
cases while the CI step claimed prompt-injection coverage this repo did not
have. The generic heuristics catch attacks on the model's *framing*; four
realistic attacks on the KYC *decision* passed straight through — overriding a
sanctions result, exfiltrating the policy corpus, a context escape in applicant
notes, and impersonating the compliance judge. Added
`.agent-rfc/security/prompt_denylist.txt` (the path the framework already
resolves by default) plus 9 tenant cases, **three of which are legitimate KYC
text expected to pass** — matching is a lowercased substring test and real
records are full of "sanctions", "approve" and "citation", so a denylist that
trips on an applicant's notes would be the worse failure. Verified against every
field of the applicant and policy corpora: zero false positives. Suite now 16
cases, miss rate 0.000.

**F7 — tenant hallucination fixtures.** The gate graded four UAE geography facts
from the framework base set, none of which actually hallucinate, so it could
never trip. Replaced with six real pipeline outputs across the rating spectrum.
Note the suite's contract: it measures the *flagged rate* of the app's own
outputs, so fixtures must be outputs that should be clean — deliberately
hallucinated cases would fail the gate by construction. Detecting an ungrounded
citation is separately and deterministically covered by `check_citations`.

Still open: two more clean passes to confirm the 0.967 floor and tighten toward
0.95; xAI and Anthropic accounts remain unfunded.

## 2026-08-02 — models.yaml converted to catalog + profiles

Same shape as the framework: `catalog:` for model references, `profiles:` for
role bindings. Resolution is **byte-identical** to the previous flat file for
all 8 roles — verified by diffing the merged registry before and after.

`default_profile: hybrid`, deliberately not the framework's `local`:
multi-vendor routing is what this testbed exists to exercise (RFC-002), and the
eval baselines are measured against these routes. Inheriting the framework
default would move every role onto local models and quietly invalidate the
calibrated thresholds.

`intake` is local in both profiles and never degrades. That is the sovereignty
control rather than a performance choice — raw applicant text reaches that role
before the PII scrub runs, so the route stays in-border by construction.

`fail_below` moved onto the judge **binding** rather than the catalog entry. It
is calibrated for one grader against one fixture set, so it belongs where the
grader is chosen: rebind the judge and the threshold goes with the binding
instead of silently grading a new model against the old one's calibration.

**Removed `routing_overrides` from tenant.yaml.** They restated all four roles —
redundant while models.yaml was flat, and actively harmful once it gained
profiles. An override sets ONLY the `id`, leaving `provider` from whichever
profile is active, so selecting `local` produced `id: claude-sonnet-4-6` on
`provider: ollama`: Anthropic, Groq and Google model names pointed at
localhost, 404 on every call, from a config that reads as correct. Verified
before removing, and verified coherent after. The mechanism stays available as
a genuine shorthand for swapping a model on the *same* provider; a
cross-provider change needs a catalog entry, because only that carries the
provider alongside the id.

A `local` profile now exists for fully offline operation — every role on
Ollama, no key, no egress. Distinct from `KYC_FAKE_LLM=1`, which replaces the
gateway with a deterministic stub and calls no model at all. It is uncalibrated
and quality-untested: the prompts were written for the hybrid routes, and local
judges proved measurably unreliable on these cases. Use it to check the
pipeline runs, not to gate merges.

## 2026-08-02 — research and analyst rebound to OpenRouter

Credential probes found only two of the configured keys working: OpenRouter and
Google AI Studio. Anthropic returned **401 "API key is invalid"** (not a
billing error — a different, longer key than the framework's, which itself
authenticates fine), and Groq returned **403 error 1010** in both repos, so the
credential rather than anything local. That left `research` and `analyst`
unable to call anything.

Both now route through OpenRouter, which fronts the same vendors on one
credential that works:

    research  meta-llama/llama-3.3-70b-instruct   $0.13/M in  (~4.5x cheaper than the Groq route)
    analyst   anthropic/claude-sonnet-4.5         $3/M in     (same as Anthropic direct)

Ids and pricing verified against the live model list, and both round-tripped a
real call before being bound. `api_format: openai_chat` is load-bearing on the
analyst entry: it is Claude, but reached in OpenAI shape — inferring the
envelope from the vendor in the id would build an Anthropic Messages request
against an OpenAI-compatible endpoint. The profile now needs exactly two
credentials, `OPENROUTER_API_KEY` and `GEMINI_API_KEY`.

The Groq and Anthropic entries stay in the catalog, unbound. Restoring either
is a one-line binding change once its account works — which is the whole point
of separating catalog from profiles.

**First live end-to-end run of the real pipeline**, and it exercised three
fixes from this session at once:

- The analyst hit OpenRouter's 402 ("requires more credits"), which matched no
  exhaustion marker, so the ladder did NOT fire and the call hard-failed.
  Fixed framework-side; the rerun then logged `Degraded from 'analyst' to
  'research'` correctly.
- The judge hit Gemini's 429 and correctly found no next tier — it is the one
  role with no `degrade_to`.
- The advisory judge critique then failed **open**: "citation and parity checks
  still applied; verdict unaffected". Before this session that exception would
  have failed the whole application.

Final result: a real LOW rating with a model-authored rationale, from live
models, with every resilience control behaving as designed.

## 2026-08-02 — live routes: a sanctions hit was one step from auto-approval

Ran the golden applicants through the REAL pipeline for the first time
(OpenRouter routes, `KYC_FAKE_LLM` unset). The judge could not score them —
Gemini's free-tier window was exhausted — but the run found more than a score
would have.

**The mandatory-HITL control failed.** Applicant `sanc-006` has one confirmed
sanctions hit. policy-003: "Any hit mandates a HIGH rating and human review
before onboarding." The live Analyst rated it **MEDIUM**, cited five policies —
all genuinely retrieved, so citation grounding **passed** — and therefore:

    needs_hitl = assessment.rating == "HIGH" or judge.flagged
               = False                        or False        = False

A sanctions-matched applicant with no human review. The gate trusted the
model's *opinion* of something that is a *fact* from the screening tool.

Nothing offline could have caught it. The fake gateway derives the rating
deterministically from the hit count, so it always returns HIGH and the control
looks sound; it only fails when a real model is asked to agree with a rule it
was never obliged to follow. Every unit test, demo scenario and eval gate was
green throughout.

Fixed with `check_rating_floor` in `agents/judge.py` — a deterministic check
run after grounding and independent of it, because a well-cited rationale can
still under-rate. Sanctions hits force HIGH; two or more adverse media items
force at least MEDIUM. Verified on the same live route: the Analyst still says
MEDIUM, and `needs_hitl` is now True with the reason recorded.

**Two other live-only failures**, both root-caused to one framework bug: a
provider returned `"content": null`, `parse_response` passed the None along,
and the PII scrubber died on it — surfacing once as `invalid JSON` and once as
`TypeError` deep inside a guardrail. Fixed framework-side.

Also observed, not yet addressed: the live models cite loosely — `policy-008`
(citation grounding, a meta-policy) and `policy-007` (fairness) appear as
rating *bases*. Grounded, so nothing flags them, but they are category errors
in the rationale. The fake gateway's citations are now semantically correct,
so this gap is real-model behaviour rather than fixture drift.

## 2026-08-06 — the rating floor is now a declared control

`check_rating_floor` had tests, documentation in RFC-002 and a demonstrated
failure behind it — a live run put a sanctions-matched applicant one step from
auto-approval — and the compliance harness could not see it. There was nowhere
for a tenant to declare a control of its own.

The framework now merges `.agent-rfc/security/control_registry.json` over its
own, mirroring the `models.yaml` framework←tenant merge. This repo declares
**SEC-KYC-FLOOR-001**, evidenced by `test/test_analyst_judge.py` — the suite
that already asserts a sanctions hit forces review even when the model
under-rates, and that a clean applicant is not flagged.

The merge is **additive only**: redefining a framework control id raises. A
registry the graded repo can edit is one where that repo could downgrade
`SEC-HITL-001` to `noop` and keep a green harness.

Harness now reports **18 controls passing** for this tenant, up from 17. The
run also prints its verdict — it previously exited with a bare status code, so
a red CI step said nothing about which control failed.

## 2026-08-06 — Temporal connection moved to the shared connector

A framework-wide review for functional (not name-based) duplication found seven
Temporal connect sites disagreeing three ways. Two were this repo's.

`worker.py` and `trigger_workflow.py` each called `Client.connect` directly and
**neither read `TEMPORAL_TLS`** — only the framework's example scripts did. A
deployment against a TLS-terminating Temporal Cloud endpoint would have
connected without TLS, with nothing reporting it. (The examples were not much
better: they compared against `"true"` while OPERATIONS.md documents `"1"`, so
the documented value silently disabled TLS there too.)

Both now use `runtime.temporal_client.connect()`, which owns the address
default, TLS parsing and a bounded connect timeout. Nothing about this repo's
behaviour changes today — it runs against a local Temporal without TLS — but a
TLS deployment would previously have failed open, and silently.

## 2026-08-06 — pinned to framework v1.2.0

The pin said `v1.1.0` and had become materially wrong, not merely stale: this
repo now imports `runtime.temporal_client` (added in 1.2.0), its `models.yaml`
uses the catalog+profiles shape, and its `.agent-rfc/security/control_registry.json`
needs the tenant-registry merge. None of that exists in 1.1.0, so anyone
installing from the pin would have got a tenant that could not start.

Two different blind spots kept it green, and it is worth being exact about
which, because the obvious explanation is only half right:

  * CI installs the framework from the checkout (`pip install -e
    $AGENTSMITH_DIR`) rather than the pin, so CI never read it at all. That is
    the right call for a testbed developed alongside the framework.
  * CD *does* read it — the Dockerfile runs `pip install -r requirements.txt`,
    so the staging smoke job genuinely installed v1.1.0. It passed anyway
    because the Cloud Run Job runs `demo.py all`, and that import graph (nine
    modules) never reaches `runtime.temporal_client`. The missing module was
    installed-but-unimported.

So the pin is executed, not decorative — but the only entry point that would
have failed on it, `worker.py`, is exactly the one the smoke job does not run
(see "Deployment — pending"). Re-read the pin on every framework release; no
current job will fail on a wrong one.

`framework.version` in tenant.yaml moved to `1.2.x` to match.

Three v1.2.0 behaviour changes apply here, all already absorbed during the work
that produced them: the judge role wins over `AGENT_JUDGE_MODEL`; a tenant
`models.yaml` entry with a different `id` replaces rather than merges (this is
what stopped the Anthropic judge inheriting an Ollama endpoint); and `--strict`
fails a control claiming `met` with no runner.
