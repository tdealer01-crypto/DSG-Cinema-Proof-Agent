# Stripe → Azure Production Cutover Evidence

Status: **PASS — AZURE STRIPE LINK VERIFIED**

Verified against the current Azure production Container App after the Stripe cutover merged in PR #58.

## Fresh production evidence

Probe source: `Probe Cinema Azure Runtime`, run `32476388333`, rerun job `96755792331`.

Observed at `2026-08-21T11:26:17Z`:

- Azure Container App `dsg-cinema-production` provisioning: `Succeeded`.
- Running status: `Running`.
- Latest revision: `dsg-cinema-production--0000021`.
- `/health`: HTTP 200, `ready=true`.
- `/billing/status`: HTTP 200.
- `checkout_status=LINKED`.
- `metering_enforced=true`.
- `enforcement_ready=true`.
- `stripe.link_state=LINKED_VERIFIED`.
- `stripe.configured=true`.
- `stripe.catalog_scope_configured=true`.
- `stripe.operational_scope_configured=true`.
- `stripe.charges_enabled=true`.
- `stripe.webhooks_configured=true`.
- `stripe.webhooks_enabled=true`.
- `stripe.operational_checks.product=PASS`.
- `stripe.operational_checks.price=PASS`.
- `stripe.operational_checks.meter=PASS`.
- `stripe.operational_checks.webhook=PASS`.
- Azure env-presence checks confirm `STRIPE_PRODUCT_ID`, `STRIPE_PRICE_ID`, `STRIPE_METER_ID`, `STRIPE_METER_EVENT_NAME`, `STRIPE_WEBHOOK_ENDPOINT_ID`, `STRIPE_WEBHOOK_ENDPOINT_URL`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET` are all present.

Probe artifact: `cinema-runtime-probe-e2404a446076a373004e3062853afed6ca177c0e`, artifact id `9444713973`.

## Verified live catalog

The non-mutating production diagnostic immediately before cutover verified:

- Product: `prod_V6xAufMNUNF6KV` — active live.
- Price: `price_1U6jRJAZNzhgTUPVUfr3tWaD` — active live USD $0.05 per verified proof.
- Billing Meter: `mtr_61VG7AFaN4e6m4T9C41AZNzhgTUPVFWq` — active live.
- Meter event: `dsg_verified_execution`.
- Azure webhook target: `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/billing/webhook/stripe`.

## Truth boundary

This proves that the Azure production billing integration is configured and operationally linked to Stripe and that the service is ready to create self-serve Checkout Sessions when requested by an authenticated eligible account.

It does **not** by itself prove a completed customer payment, signed `checkout.session.completed` delivery, paid entitlement promotion, subsequent billable proof, or settlement. Those require a real buyer transaction and its resulting evidence chain.

GitHub Marketplace is a separate billing channel and remains `ACTION_REQUIRED` until its webhook secret and OAuth client credentials are configured and a real Marketplace purchase is observed end to end.
