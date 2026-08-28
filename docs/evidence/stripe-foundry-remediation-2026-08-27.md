# Stripe Foundry remediation evidence — 2026-08-27/28 UTC

## Claim boundary

This evidence covers source changes, local tests, and a live pre-deployment
probe. It does **not** claim that the incremental executor is deployed, that
Stripe-issued values have been configured, or that Stripe upload, External
Test, review, approval, or publication has happened.

No Stripe key, signing secret, authorize URL, DSG API key, GitHub credential,
or encrypted value is stored in this document.

## Live baseline

Probed production at `2026-08-28T00:40:56Z`:

`https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io`

| Probe | Observed result |
|---|---|
| `GET /health` | `200`; `status=ready`, `backend=ready` |
| `GET /openapi.json` | OpenAPI `3.1.0`, service version `1.3.0` |
| Required routes | `/health`, `/marketplace/stripe/status`, and `/api/v1/control/configure-stripe-app` present |
| Live executor schema | all six `StripeAppProductionValues` fields still listed in `required` |
| `GET /marketplace/stripe/status` | `ACTION_REQUIRED`, `linked_accounts=0` |

Nine readiness checks passed. Five were missing:

- `oauth_live_authorize_url`
- `oauth_test_authorize_url`
- `oauth_sandbox_authorize_url`
- `oauth_test_secret_key`
- `oauth_sandbox_secret_key`

`app_signing_secret` passed. The production contract therefore cannot safely
accept only the five missing values yet. The local host correctly returns
`WAITING_DEPLOYMENT` before reading any Stripe value while the live schema has
an all-six `required` list.

## Implemented boundary

- The Cinema executor accepts a non-empty subset of six fixed destination
  names and writes/read-backs only the submitted values.
- Secret-only writes require only the GitHub App environment permission;
  variable-only writes require only the variable permission.
- Empty objects and arbitrary destination names remain rejected.
- The readiness endpoint marks identical test-mode and managed-sandbox keys as
  `REUSED`, refuses setup, and remains `ACTION_REQUIRED`.
- The Foundry OpenAPI tool contains only three anonymous `GET` operations.
- The Foundry function schema has an empty object as its only valid argument.
- The local host fetches live OpenAPI first, derives missing fixed names from
  live status, and reads only those names from its process environment.
- Function results are recursively stripped of value-, token-, authorization-,
  and API-key-shaped fields.
- Code Interpreter is optional and sees no secret-bearing input. Research mode
  is separate and receives Web Search only, with no mutation function.

## Local verification

Targeted verification passed before the PR:

```text
53 passed in 1.53s
```

The targeted suite covers the Foundry compatibility gate and tool boundary,
incremental GitHub writes, redaction, missing local inputs, ready/no-op state,
reused non-live keys, and existing Stripe Marketplace OAuth behavior.

The complete repository suite then passed with Work Mode proxy variables
removed from the test process (the tests mock their external requests):

```text
572 passed, 13 warnings in 6.16s
```

Marketplace-specific guards also passed:

- `landing/index.html` and `azure-landing/index.html` are byte-identical.
- `landing/validate.sh` reports `DSG landing validation: PASS`.
- The retired Control Plane URL grep found no match below `marketplace/`.

The pinned Foundry runtime (`azure-ai-projects 2.4.0`, `azure-identity 1.25.3`,
`openai 2.54.0`) successfully constructed `OpenApiTool`, `FunctionTool`,
`CodeInterpreterTool`, and `PromptAgentDefinition` objects locally. No Foundry
project deployment was claimed because project endpoint/RBAC inputs were not
present in this environment.

Full repository, landing, retired-URL, and post-deployment probe results are
recorded separately when run; a pre-deployment result must not be promoted into
a production claim.

## Deployment acceptance criteria

After merge and the Cinema production workflow completes:

1. `/openapi.json` contains all six fixed properties but no `required` list for
   `StripeAppProductionValues`.
2. Existing health and Stripe routes still return `200`.
3. `/marketplace/stripe/status` remains truthful; absent Stripe-issued values
   remain non-PASS rather than being inferred.
4. The secure local host reports `live_contract_incremental=true`.
5. Production is not called `READY` until every readiness check is `PASS`.

## Current platform references

Implementation patterns were checked against Microsoft documentation current
on 2026-08-28:

- [Foundry SDK 2.x overview](https://learn.microsoft.com/azure/foundry/how-to/develop/sdk-overview)
- [OpenAPI tools](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/openapi)
- [Function calling](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/function-calling)
- [Code Interpreter](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/code-interpreter)
- [Web Search and Deep Research](https://learn.microsoft.com/azure/foundry/openai/how-to/web-search)
