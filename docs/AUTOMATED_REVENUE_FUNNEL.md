# DSG ONE Automated Revenue Funnel

## User path

```text
Free activation
  → 25 verified proofs, hard cap, no card
  → POST /billing/checkout/session
  → Stripe-hosted Checkout
  → signed + catalog-scoped Stripe webhook
  → metered entitlement
  → verified proof
  → local hash-chained usage ledger
  → Stripe meter event
  → /billing/usage + /billing/report reconciliation
```

The browser redirect is never payment evidence. Creating a Checkout Session
returns `CHECKOUT_CREATED_NOT_ENTITLED`; DSG keeps the account on its current
plan until a valid signed Stripe webhook confirms the exact configured
subscription.

## Self-serve upgrade

The current self-serve paid path intentionally supports only `metered` because
the runtime currently has one direct-billing `STRIPE_PRICE_ID` and one exact
catalog scope. Team and Enterprise are not silently mapped to that Price.

```http
POST /billing/checkout/session
X-DSG-API-Key: dsg_live_...
Content-Type: application/json

{
  "plan": "metered",
  "checkout_id": "stable-client-generated-id"
}
```

A successful response contains a Stripe-hosted `checkout_url`, but also reports
`entitled: false`. The client should navigate to that URL. After Checkout, the
existing signed webhook path binds the Stripe customer/subscription to the DSG
account and promotes the plan only when the configured product and price match.

## Current direct catalog

The runtime catalog in `revenue/pricing.py` is authoritative:

- `free`: 25 included verified proofs, hard cap 25, no payment method.
- `metered`: no monthly minimum; `verified_execution` currently resolves to
  **$0.05 per verified proof**.
- `team`: $490/month, 5,000 included, $0.08/proof after included usage.
- `enterprise`: contract pricing.

The Team card is a catalog offer, not a claim that Team Checkout is wired. A
separate verified Stripe price model is required before Team can become a
self-serve button.

## Fail-closed checks before Checkout

The checkout endpoint refuses to create a paid Session unless all of these are
true:

1. The caller presents a valid **live** DSG API key.
2. The account is not already billed by GitHub Marketplace.
3. The account is not already an active metered subscriber.
4. The configured Stripe key is live mode.
5. Product, Price, Billing Meter, and webhook endpoint are verified against
   Stripe by the existing operational-link check.
6. The Stripe customer id is persisted on the DSG account before Session
   creation, so fast webhooks can resolve the correct account.

No failed or timed-out verification becomes a billable unit. Existing metering
still bills only proof receipts with `verified=true` and
`VERIFIED_GLOBAL_OPTIMUM`.

## Evidence states

| State | What it proves | Entitled? |
|---|---|---:|
| `free` account | free activation succeeded | Free only |
| `CHECKOUT_CREATED_NOT_ENTITLED` | Stripe accepted Session creation | No |
| signed scoped subscription event applied | Stripe subscription matches DSG catalog | Yes |
| verified proof ledger entry | one proved result was recorded | Yes, one usage unit |
| Stripe meter sync `SYNCED` | usage event was accepted by Stripe | Billing transport confirmed |

## Production truth boundary

Repository code can implement and test the funnel, but it cannot by itself prove
that the currently deployed Azure revision has the matching live Stripe objects.
`GET /billing/status` remains the runtime source of truth. A deployment must not
show checkout as ready until `stripe.charges_enabled` is true from live
operational verification.
