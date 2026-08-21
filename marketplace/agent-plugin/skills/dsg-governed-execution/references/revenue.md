# DSG Revenue Handoff

The Agent Plugin governs executions. It does not embed billing credentials and it does not autonomously purchase a plan.

## Free start

A user or application can activate a free DSG API key with:

```http
POST /billing/activate
Content-Type: application/json

{
  "channel": "agent_plugin",
  "activation_id": "<stable-client-or-installation-id>",
  "display_name": "<human-readable-name>"
}
```

The current free plan includes 25 verified proofs with a hard cap. The API key is returned once. Store it using the client or application's credential mechanism, never in `plugin.json`, `mcp.json`, `SKILL.md`, source control, evidence, or logs.

## Metered upgrade

When the user explicitly chooses paid usage, the authenticated application can create a Stripe-hosted Checkout Session:

```http
POST /billing/checkout/session
X-DSG-API-Key: <client-managed-key>
Content-Type: application/json

{
  "plan": "metered",
  "checkout_id": "<stable-idempotency-id>"
}
```

A successful session creation returns a Checkout URL and the state `CHECKOUT_CREATED_NOT_ENTITLED`. That state is intentionally **not** a paid entitlement.

DSG promotes the account only after a valid signed Stripe webhook confirms the configured product, price, customer, and subscription scope. Browser redirects and client claims do not grant paid access.

## Billable unit

The direct metered SKU is one `verified_execution` receipt. A failed verifier call, timeout, refusal, or result without `verified=true` and `VERIFIED_GLOBAL_OPTIMUM` is not a billable proof unit.

## User-facing refusal handling

When the server returns a `remediation` object, show:

- `problem`: what failed;
- `cause`: why it failed;
- `next_step`: what the user should do;
- `self_service`: whether the user can resolve it without an operator.

Do not reduce a billing refusal to only an HTTP status code.
