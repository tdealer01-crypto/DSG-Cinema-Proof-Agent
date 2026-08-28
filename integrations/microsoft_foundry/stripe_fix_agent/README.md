# Microsoft Foundry Stripe fix agent

This integration turns Microsoft Foundry tools into a fail-closed operator for
the remaining Stripe Marketplace configuration. It can diagnose production,
request an already-approved fixed action, and return read-back evidence. It
cannot choose a GitHub destination, bypass DSG plan authorization, upload a
Stripe App, run External Test, submit for review, or publish.

## Safety boundary

The Foundry-visible OpenAPI tool contains only these anonymous `GET` routes:

- `/health`
- `/openapi.json`
- `/marketplace/stripe/status`

The only mutation tool is
`apply_approved_stripe_production_values`. Its JSON schema has no parameters.
The local host reads Stripe-issued values only after the live OpenAPI document
proves that the incremental executor is deployed. Values never enter the
prompt, conversation, function arguments, URL, result, or Foundry trace.

The host sends only checks that are not `PASS`, using this fixed mapping:

| Readiness check | GitHub destination |
|---|---|
| `app_signing_secret` | environment secret `STRIPE_APP_SIGNING_SECRET` |
| `oauth_test_secret_key` | environment secret `STRIPE_APP_OAUTH_TEST_SECRET_KEY` |
| `oauth_sandbox_secret_key` | environment secret `STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY` |
| `oauth_test_authorize_url` | environment secret `STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL` |
| `oauth_sandbox_authorize_url` | environment secret `STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL` |
| `oauth_live_authorize_url` | repository variable `DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL` |

Test-mode and managed-sandbox keys must be different. The production readiness
endpoint reports `REUSED` and remains `ACTION_REQUIRED` if they are identical.

## Install

Use Python 3.11 or later and Microsoft Foundry 2.x:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r integrations/microsoft_foundry/stripe_fix_agent/requirements.txt
az login
```

The operator needs the Foundry User role on the project. `DefaultAzureCredential`
is used; no Azure credential is stored in this repository.

## Prepare an approved run

Create and approve a DSG plan whose only step is:

```json
{
  "step_id": "stripe-production-setup",
  "action": "configure_stripe_app",
  "target": "pics.dsg.governance",
  "parameters": {}
}
```

The approved identity must match `DSG_STRIPE_FIX_AGENT_IDENTITY`. Load control
inputs locally:

```bash
export FOUNDRY_PROJECT_ENDPOINT='https://RESOURCE.services.ai.azure.com/api/projects/PROJECT'
export FOUNDRY_MODEL_DEPLOYMENT_NAME='gpt-5-mini'
export DSG_STRIPE_FIX_AGENT_IDENTITY='microsoft-foundry-stripe-fix-agent'
export DSG_STRIPE_FIX_PLAN_ID='APPROVED_PLAN_ID'
read -rsp 'DSG API key: ' DSG_API_KEY && export DSG_API_KEY && printf '\n'
```

Load only Stripe values named as non-PASS by the live status. Use silent input
for secrets and bearer-style authorize links so they do not enter shell history:

```bash
read -rsp 'Stripe App signing secret: ' STRIPE_APP_SIGNING_SECRET && export STRIPE_APP_SIGNING_SECRET && printf '\n'
read -rsp 'Test developer key: ' STRIPE_APP_OAUTH_TEST_SECRET_KEY && export STRIPE_APP_OAUTH_TEST_SECRET_KEY && printf '\n'
read -rsp 'Sandbox developer key: ' STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY && export STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY && printf '\n'
read -rsp 'Test authorize URL: ' STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL && export STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL && printf '\n'
read -rsp 'Sandbox authorize URL: ' STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL && export STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL && printf '\n'
read -rp 'Public live install URL: ' DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL && export DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL
```

Prefer Azure Key Vault for long-lived copies. Never put a Stripe key or
invite-style authorize URL in a prompt, issue, commit, `.env` file, or command
argument.

## Run

```bash
python -m integrations.microsoft_foundry.stripe_fix_agent.agent
```

Optional Code Interpreter can analyze non-secret readiness data. Its sandbox
has no outbound network access and is not used to execute the configuration:

```bash
export FOUNDRY_ENABLE_CODE_INTERPRETER=1
python -m integrations.microsoft_foundry.stripe_fix_agent.agent
```

The local host can also run without a model:

```bash
python -m integrations.microsoft_foundry.stripe_fix_agent.secure_config
```

`WAITING_DEPLOYMENT` means the live service still advertises the legacy
all-six-values-required schema (or its contract cannot be verified). No Stripe
value is read in that state. `WAITING_OPERATOR_INPUT`, `WAITING_PERMISSION`, or
`BLOCK` also means no successful configuration may be claimed.

After an `ALLOW` write, merge/deploy the Cinema change and probe both
`/openapi.json` and `/marketplace/stripe/status`. Continue only when every check
is `PASS` and status is `READY`.

## Research-only mode

Research is a separate Responses request with Web Search and no OpenAPI mutation
or local function tool:

```bash
export FOUNDRY_RESEARCH_MODEL_DEPLOYMENT_NAME='gpt-5.5'
python -m integrations.microsoft_foundry.stripe_fix_agent.agent \
  --mode research \
  'Research current Stripe Apps Marketplace review requirements with citations.'
```

Deep research can run for several minutes. Use it for vendor documentation and
review requirements, not for carrying credentials or making production writes.

Current implementation follows Microsoft Foundry 2.x guidance for
[OpenAPI tools](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/openapi),
[function calling](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/function-calling),
[Code Interpreter](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/code-interpreter),
and [Web Search / Deep Research](https://learn.microsoft.com/azure/foundry/openai/how-to/web-search).
