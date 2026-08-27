# DSG ONE CI/CD, GitHub Actions, Test Coverage & E2E Reference

_Last source inventory reviewed: 2026-08-27 UTC_

This document maps the current `DSG-Cinema-Proof-Agent` verification and delivery system from source change to production evidence. It is an implementation reference, not a generic DevOps diagram.

## Truth boundary

At the reviewed revision, the repository contains:

- **43 GitHub Actions workflow files** under `.github/workflows/`.
- **40 primary pytest modules** under `tests/test_*.py`.
- **2 additional test/check utilities** under `tests/check_*.py`.
- **1 additional hackathon client test module** at `hackathons/agents-for-humans/test_dsg_client.py`.
- Staging and production E2E workflows that build/deploy or call real external/runtime surfaces.
- Persisted deployment and client evidence artifacts.

### Numeric source-code coverage is not currently measured

No `pytest-cov` configuration or dependency was found in the reviewed repository, and `requirements-cinema.txt` does not include `coverage`/`pytest-cov`. Therefore this repository must **not** publish a line-coverage or branch-coverage percentage from the current CI configuration.

The word **coverage** in this document is split into three different concepts:

1. **Test-surface coverage** — which contracts, modules, adapters and failure modes have executable tests.
2. **E2E path coverage** — which real deployment/client paths are exercised end to end.
3. **Instrumented source coverage** — line/branch percentages collected by a coverage tool. **Status: NOT MEASURED in current CI.**

A high number of tests or passing E2E runs is not a substitute for instrumented line/branch coverage.

---

## CI/CD architecture

```text
SOURCE CHANGE / PR
        |
        v
Path-scoped GitHub Actions triggers
        |
        +--> compile / syntax / package validation
        |
        +--> unit + contract + integration tests
        |
        +--> deterministic governance assertions
        |
        +--> marketplace / revenue / browser regressions
        |
        +--> staging or live E2E where the workflow owns that boundary
        |
        v
MERGE TO main
        |
        +--> production deploy workflow(s)
        |
        +--> production health / readiness / proof probes
        |
        +--> replay / hash / exact-proof validation
        |
        v
PERSISTED EVIDENCE
  .deployment/*.json
  evidence/client/*.json
  docs/evidence/*.md
  GitHub Actions artifacts / run records
```

The release model is deliberately layered. A unit-test PASS does not imply production is live. A deployment PASS means only the checks encoded in that deployment workflow passed for that revision and target.

---

## Core CI gates

### `api-v1-verify.yml` — DSG ONE v1 API and control-plane contract

This workflow is path-scoped to API v1, mobile, OpenAPI, web, selected revenue/Marketplace files and their tests. It:

- compiles `cinema_main.py`, API v1 modules and Marketplace/pricing bridge modules;
- runs the API, contract, console, GitHub Marketplace, Cinema, mobile, decision-core, execution-boundary and Stripe executor tests;
- asserts REST, MCP and mobile authorization paths share the canonical decision core;
- asserts caller-supplied verdict fields cannot be accepted as computed truth;
- asserts verified receipts are built only behind an exact proof;
- prevents the disconnected UI markup from shipping pre-baked PASS/VERIFIED states;
- asserts GitHub Marketplace entitlements cannot be double-billed through Stripe;
- validates production Marketplace configuration guards and API/image contract consistency.

The canonical authorization outcome set checked by this workflow is:

```text
ALLOW
WAITING_PERMISSION
BLOCK
```

### `verify-z3.yml` — exact solver contract

Owns the Z3 verifier contract and regression boundary. It is separate from the Cinema orchestration layer so candidate computation and formal proof behavior can fail independently.

### `marketplace-launch-verify.yml` — multi-marketplace launch pack

Runs Cinema and marketplace-surface tests, validates the launch manifest, revenue claims, GitHub Action package, OpenAI Skills package, Stripe App typecheck, Pydantic runtime contract, landing validation and retired-runtime reference rejection.

### `revenue-verify.yml` — commercial/runtime integrity

Compiles the revenue system and executes revenue, channel, Cinema, Z3 and durable-store tests. It also asserts:

- channel packages can reach the live contract;
- activation cannot grant a paid plan;
- denial codes have actionable remediation;
- credential rotation is fail-closed;
- shared stores use locking/reload semantics before writes;
- live credential material is not committed;
- entitlement is checked before solver work and unverified proof cannot be metered;
- ledger/report behavior stays deterministic and usage is not misrepresented as recognized revenue.

### Other verification gates

Specialized workflows cover agent-plugin conformance, Azure DevOps extension packaging, remote-browser verification, Stripe surfaces, revenue lifecycle waves and ActiveCampaign projections. They remain separate so a channel-specific failure is visible rather than hidden inside one monolithic CI job.

---

## CD and production release gates

### `deploy-cinema-production.yml`

Production Cinema deployment workflow. The repository manifest identifies it as the Cinema deployment plus production E2E owner. Production promotion is not equivalent to image build success: the workflow performs convergence/probe checks against the deployed runtime.

### `deploy-z3-azure.yml`

Owns the Azure Z3 deployment boundary. Its trigger scope is intentionally separated from broad unrelated test changes so revenue-only changes do not unnecessarily redeploy the solver.

### `deploy-azure-3d-landing.yml`

The Azure landing deployment performs all of the following before/after publishing:

- validates the current-system landing contract;
- requires the Azure and mirror landing `index.html` files to remain byte-identical;
- activates a free capped API key for release verification;
- validates browser CORS and the production `/verify/evaluate` contract;
- requires `decision == ALLOW`, `verified == true` and `verification == VERIFIED_GLOBAL_OPTIMUM` for the release probe;
- deploys through Azure OIDC;
- verifies the public landing after upload;
- persists `.deployment/azure-3d-landing.json` as deployment evidence.

### `probe-cinema-azure.yml`

Production probe surface for Cinema/Azure readiness and current integration status. This is operational evidence, not a replacement for unit/integration tests.

### Guarded operational workflows

`apply-guarded-migration.yml`, production configuration workflows and credential/webhook workflows perform bounded operational mutations. Their existence does not authorize arbitrary mutation; each workflow owns a defined deployment/configuration scope.

---

## E2E verification matrix

| E2E path | Environment / external boundary | What is actually exercised | Evidence / failure boundary |
|---|---|---|---|
| `cinema-e2e-azure.yml` | isolated Azure staging | build Z3 image → deploy Z3 → exact proof → build Cinema → deploy Cinema → health → Cinema→Z3 proof twice/replay | requires exact witness/energy/hashes and `VERIFIED_GLOBAL_OPTIMUM`; failure does not become PASS |
| `cinema-browserbase-planbound-production-e2e.yml` | production Cinema + Browserbase | self-activate → create plan → approve → remote enable → connect → navigate → extract → screenshot → out-of-plan block → disconnect | uploads sanitized evidence; requires evidence hashes and a real 403 for out-of-plan navigation |
| `copilot-cli-full-governed-e2e.yml` | GitHub Copilot CLI + public plugin + authenticated DSG MCP | install plugin → authenticate Copilot → activate DSG → add MCP → create/approve plan → alignment → constraints → execution → evidence → verify → fetch proof | independently re-fetches plan/execution/proof and requires computed truth plus receipt hash verification |
| `copilot-cli-mcp-auth-e2e.yml` | Copilot CLI + authenticated DSG MCP | plugin install → Copilot auth gate → DSG activation → MCP add → direct `dsg_status` → agent-driven tool call | explicitly reports `ACTION_REQUIRED` when headless Copilot auth is unavailable; no fake PASS |
| `copilot-cli-plugin-e2e.yml` | public plugin/client package | plugin installation and plugin-facing execution contract | client artifact evidence |
| `browserbase-production-smoke.yml` | Browserbase production | provider/session smoke boundary | live provider reachability/surface behavior |
| `stripe-browserbase-surface-smoke.yml` | Stripe + browser provider surface | UI/browser-facing Stripe surface smoke | does not equal Stripe marketplace approval |
| `deploy-cinema-production.yml` | production Azure | deploy + production runtime convergence/E2E | deploy run and live probes |
| `deploy-azure-3d-landing.yml` | production Azure static web + Cinema | browser contract + public website release | persisted `.deployment/azure-3d-landing.json` |

### Azure isolated E2E specifics

`cinema-e2e-azure.yml` creates per-run secrets, builds isolated images, deploys isolated Container Apps, then proves the solver directly and through Cinema. Its exact-proof assertion includes:

```text
verified == true
verification == VERIFIED_GLOBAL_OPTIMUM
witness == [1,0,0]
energy_exact == -4
proof_hash length == 64
request_hash length == 64
```

Cinema is then called repeatedly to establish the current Cinema→Z3 exact-proof/replay path rather than merely checking HTTP health.

### Plan-bound production browser E2E specifics

The Browserbase production E2E proves both the allowed and denied paths. It binds the browser to an approved plan for `example.com`, obtains navigation/extraction/screenshot evidence hashes, then deliberately attempts `example.org` and requires the governed path to return a 403. The evidence artifact omits live credentials and stores hashes/IDs instead.

---

## Test-surface coverage matrix

### Core API, authorization and runtime contract

- `tests/test_api_v1.py`
- `tests/test_api_contract.py`
- `tests/test_decision_core.py`
- `tests/test_decision_core_channels.py`
- `tests/test_execution_boundary.py`
- `tests/test_mobile_control.py`
- `tests/test_chatgpt_remote_actions.py`
- `tests/test_console_prototype.py`

Covers API schema/behavior, canonical authorization semantics, channel consistency, execution boundaries, mobile/control adapters, remote-action contract and console truth states.

### Solver, proof and Cinema

- `tests/test_z3_main.py`
- `tests/test_cinema_main.py`
- `tests/test_deploy_z3_azure_rest.py`

Covers exact proof behavior, Cinema proof validation/fail-closed mapping and Azure solver deployment REST behavior.

### Remote execution, MCP and browser

- `tests/test_browserbase_executor.py`
- `tests/test_remote_browser.py`
- `tests/test_remote_mcp.py`
- `tests/test_remote_pairing.py`

Covers browser execution/provider boundaries, plan-bound remote browser behavior, MCP bridge behavior and pairing/session contracts.

### Durable state, mutation and evidence integrity

- `tests/test_durable_store.py`
- `tests/test_guarded_mutation.py`
- `tests/test_shared_store_durability_contract.py`

Covers durable persistence assumptions, guarded write boundaries and shared-store durability contracts.

### Marketplace and delivery channels

- `tests/test_agent_plugin_v1.py`
- `tests/test_azure_devops_marketplace.py`
- `tests/test_channel_delivery.py`
- `tests/test_github_marketplace.py`
- `tests/test_marketplace_surfaces.py`
- `tests/test_stripe_app_executor.py`
- `tests/test_stripe_marketplace.py`
- `tests/test_stripe_marketplace_adaptive_form.py`
- `tests/test_stripe_marketplace_shared_browser.py`
- `tests/test_stripe_payment_proof.py`

Covers plugin conformance, Azure/GitHub/Stripe marketplace contracts, channel activation/delivery/remediation, shared browser/UI behavior and payment-proof boundaries.

### Revenue lifecycle and commercial integrity

- `tests/test_revenue.py`
- `tests/test_revenue_checkout.py`
- `tests/test_revenue_events.py`
- `tests/test_revenue_intent.py`
- `tests/test_revenue_lifecycle.py`
- `tests/test_revenue_signals.py`
- `tests/test_lifecycle_store.py`
- `tests/test_activecampaign_mcp_users.py`
- `tests/test_activecampaign_projection.py`
- `tests/test_activecampaign_revenue.py`

Covers pricing/metering/ledger/checkout, lifecycle events/intents/signals/storage and deterministic ActiveCampaign projection/reconciliation surfaces.

### Observability

- `tests/test_sentry_integration.py`

Covers Sentry/error-monitoring integration behavior separately from business-state correctness.

### Additional checks

- `tests/check_activation_patch.py`
- `tests/check_app_js_syntax.py`
- `hackathons/agents-for-humans/test_dsg_client.py`

The hackathon client test explicitly fails closed when a receipt is unverified, has the wrong verification state/decision, has malformed hashes, or lacks a context hash.

---

## Complete GitHub Actions workflow inventory

The following is the reviewed set of **43** workflow files in `.github/workflows/`:

1. `activecampaign-revenue-reconcile.yml`
2. `activecampaign-revenue-verify.yml`
3. `agent-plugin-conformance.yml`
4. `agents-for-humans-strands.yml`
5. `api-v1-verify.yml`
6. `apply-guarded-migration.yml`
7. `azure-devops-extension.yml`
8. `bind-browserbase-production.yml`
9. `browserbase-ci-session-cleanup.yml`
10. `browserbase-credential-diagnostic.yml`
11. `browserbase-production-smoke.yml`
12. `cinema-browserbase-connect-diagnostic.yml`
13. `cinema-browserbase-planbound-production-e2e.yml`
14. `cinema-e2e-azure.yml`
15. `configure-github-marketplace-production.yml`
16. `configure-stripe-production.yml`
17. `copilot-cli-full-governed-e2e.yml`
18. `copilot-cli-mcp-auth-e2e.yml`
19. `copilot-cli-plugin-e2e.yml`
20. `deploy-azure-3d-landing.yml`
21. `deploy-cinema-production.yml`
22. `deploy-dashboard-production-trigger.yml`
23. `deploy-z3-azure.yml`
24. `diagnose-stripe-webhooks.yml`
25. `marketplace-launch-verify.yml`
26. `probe-cinema-azure.yml`
27. `remote-browser-verify.yml`
28. `retire-legacy-stripe-webhooks.yml`
29. `revenue-autopilot.yml`
30. `revenue-checkout-verify.yml`
31. `revenue-verify.yml`
32. `revenue-w1a-events-verify.yml`
33. `revenue-w1b-lifecycle-verify.yml`
34. `revenue-w1c-intent-verify.yml`
35. `revenue-w1d-messaging-verify.yml`
36. `revenue-w2a-lifecycle-store-verify.yml`
37. `revenue-w2b-signals-verify.yml`
38. `revenue-w2c-stripe-proof-verify.yml`
39. `revenue-w2d-ac-projection-verify.yml`
40. `stripe-app-v2-7.yml`
41. `stripe-browserbase-provider-diagnostic.yml`
42. `stripe-browserbase-surface-smoke.yml`
43. `verify-z3.yml`

### Workflow responsibility groups

| Group | Representative workflows | Boundary |
|---|---|---|
| Core verification | `api-v1-verify`, `verify-z3`, `marketplace-launch-verify`, `agent-plugin-conformance`, `remote-browser-verify` | source/contract correctness |
| Revenue/commercial | `revenue-verify`, checkout, W1/W2 waves, ActiveCampaign verify/reconcile | entitlement, lifecycle, metering, projections |
| Browser/provider | Browserbase diagnostics/smoke/binding, Cinema Browserbase workflows | remote provider/session behavior |
| Client E2E | Copilot CLI full/MCP/plugin workflows | real client + plugin + MCP path |
| Deployment | deploy Cinema/Z3/Azure landing/dashboard trigger | promotion and release |
| Production probes | `probe-cinema-azure`, Browserbase/Stripe smoke | deployed-state evidence |
| Guarded operations | migration, Stripe/GitHub Marketplace configuration, webhook diagnosis/retirement | bounded mutation/configuration |

---

## Complete primary pytest inventory

The reviewed `tests/` directory contains these **40** `test_*.py` modules:

1. `test_activecampaign_mcp_users.py`
2. `test_activecampaign_projection.py`
3. `test_activecampaign_revenue.py`
4. `test_agent_plugin_v1.py`
5. `test_api_contract.py`
6. `test_api_v1.py`
7. `test_azure_devops_marketplace.py`
8. `test_browserbase_executor.py`
9. `test_channel_delivery.py`
10. `test_chatgpt_remote_actions.py`
11. `test_cinema_main.py`
12. `test_console_prototype.py`
13. `test_decision_core.py`
14. `test_decision_core_channels.py`
15. `test_deploy_z3_azure_rest.py`
16. `test_durable_store.py`
17. `test_execution_boundary.py`
18. `test_github_marketplace.py`
19. `test_guarded_mutation.py`
20. `test_lifecycle_store.py`
21. `test_marketplace_surfaces.py`
22. `test_messaging_policy.py`
23. `test_mobile_control.py`
24. `test_remote_browser.py`
25. `test_remote_mcp.py`
26. `test_remote_pairing.py`
27. `test_revenue.py`
28. `test_revenue_checkout.py`
29. `test_revenue_events.py`
30. `test_revenue_intent.py`
31. `test_revenue_lifecycle.py`
32. `test_revenue_signals.py`
33. `test_sentry_integration.py`
34. `test_shared_store_durability_contract.py`
35. `test_stripe_app_executor.py`
36. `test_stripe_marketplace.py`
37. `test_stripe_marketplace_adaptive_form.py`
38. `test_stripe_marketplace_shared_browser.py`
39. `test_stripe_payment_proof.py`
40. `test_z3_main.py`

`test_messaging_policy.py` belongs to the revenue messaging-policy boundary and is kept in the complete inventory even though it is not repeated in the grouped list above.

---

## Evidence inventory

Examples of persisted evidence surfaces currently present in the repository include:

- `.deployment/azure-3d-landing.json`
- `docs/evidence/ui-e2e-2026-08-21.md`
- `evidence/client/copilot-cli-full-governed-e2e-2026-08-21.json`
- `evidence/client/copilot-cli-mcp-auth-e2e-2026-08-21.json`
- `evidence/client/copilot-cli-plugin-e2e-2026-08-21.json`
- `evidence/client/copilot-cli-agent-auth-preflight-2026-08-21.json`
- `docs/GITHUB_MARKETPLACE_E2E_CUTOVER.md`
- `docs/STRIPE_AZURE_CUTOVER_EVIDENCE.md`

Evidence files are scoped observations. Their presence does not prove later revisions unless commit/run bindings establish that relationship.

---

## What each PASS means

| Result | What it proves | What it does **not** prove |
|---|---|---|
| Unit/contract test PASS | encoded behavior passed for the tested revision/input | production deployment is healthy |
| CI workflow PASS | every executed gate in that workflow passed | workflows that did not run passed |
| Staging E2E PASS | the encoded end-to-end path worked in that isolated staging run | production path is identical/live |
| Production smoke/probe PASS | the named production observations passed at that run time | all product behavior or future availability |
| Deployment PASS | deployment + workflow-specific post-deploy checks passed | third-party certification/marketplace approval |
| Exact Z3 PASS | the encoded formal proof obligation was established | legal/compliance correctness outside the encoded problem |
| Marketplace package PASS | package/manifest/UI contract is internally valid | external marketplace acceptance |

**No run = no PASS claim. Missing evidence = unresolved, not success.**

---

## Coverage hardening gap

The remaining measurable gap is instrumented source-code coverage. A future hardening change should add a dedicated coverage job rather than infer a percentage from test count. A suitable implementation would:

1. add `pytest-cov` as an explicit CI/dev test dependency;
2. run the intended complete test set with `--cov` against the selected first-party packages/modules;
3. produce `coverage.xml` plus a human-readable report;
4. upload the report as a GitHub Actions artifact;
5. define an initial threshold only after a baseline run is observed;
6. increase thresholds deliberately without excluding difficult control/exception paths simply to improve the number.

Until that is implemented and a report is attached to a concrete commit, the correct public status remains:

```text
Test-surface coverage: DOCUMENTED
E2E path coverage: DOCUMENTED + EXECUTABLE
Instrumented line coverage: NOT MEASURED
Instrumented branch coverage: NOT MEASURED
```

---

## Release review checklist

Before describing a revision as production-verified:

- [ ] Identify the exact commit SHA.
- [ ] Identify which path-scoped CI workflows actually triggered.
- [ ] Require all relevant triggered gates to complete successfully.
- [ ] Check staging/live E2E only when the changed boundary requires it.
- [ ] Verify production deploy workflow completion for changed deployable surfaces.
- [ ] Verify production health/proof/browser probes as applicable.
- [ ] Retain the run ID and non-secret evidence artifact/receipt.
- [ ] Do not convert a skipped, cancelled, untriggered or externally blocked check into PASS.
- [ ] Do not publish numeric source coverage until a real coverage report exists.
