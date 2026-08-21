# Stripe → Azure Production Cutover Evidence

Status: **PENDING POST-CUTOVER PROBE**

This record is intentionally fail-closed. It is opened only to trigger the existing `Probe Cinema Azure Runtime` workflow after the Stripe production configuration workflow introduced in PR #56 reaches `main`.

A PASS may be recorded only from fresh Azure production evidence showing all of the following:

- Container App provisioning `Succeeded` and running `Running`.
- `/health` returns HTTP 200 and `ready=true`.
- `/billing/status` returns HTTP 200.
- `metering_enforced=true` and `enforcement_ready=true`.
- `stripe.link_state=LINKED_VERIFIED`.
- `stripe.charges_enabled=true`.
- `stripe.webhooks_enabled=true`.
- `stripe.operational_checks.product/price/meter/webhook` are all `PASS`.

If any check is absent or false, this document remains PENDING/BLOCKED and no revenue-live claim is made.
