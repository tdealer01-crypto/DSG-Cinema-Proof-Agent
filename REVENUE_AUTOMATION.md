# DSG Verified Execution — Automated Revenue System

The product already proves things. This document describes the layer that turns
a proof into a billable unit, and what is still required before money moves.

## What changed

Before this system, `/verify/evaluate` and `/stripe/evaluate` were public,
unauthenticated, and unmetered: anyone could consume unlimited verified proofs
for free, and nothing recorded who consumed what. There was no customer
identity, no usage counter, no entitlement, and no billing path.

The revenue system adds all four, without changing what the product proves.

## The billable unit

**One Z3 `VERIFIED_GLOBAL_OPTIMUM` proof receipt.**

This is enforced in code, not by convention. `RevenueEngine.record_usage`
refuses any receipt whose `verified` is not `true` or whose `verification` is
not `VERIFIED_GLOBAL_OPTIMUM`, so a failed or timed-out verification can never
produce revenue. A customer is charged only for what was actually proved.

## Request path

```
client
  │  X-DSG-API-Key
  ▼
authorize_request()          ← entitlement resolved BEFORE any solver work
  │  AUTHORIZED / 401 / 402 / 403
  ▼
Cinema → exact Z3 → VERIFIED_GLOBAL_OPTIMUM
  │
  ▼
meter()                      ← proof-bound, idempotent
  │
  ├─→ hash-chained usage ledger  (local evidence)
  └─→ Stripe meter event         (only with a configured key and meter)
```

Denials are fail-closed and never fall through to a free proof:

| Condition | Decision | HTTP |
|---|---|---|
| No key presented, enforcement off | unmetered public evaluation | 200 |
| No key presented, enforcement on | `UNKNOWN_KEY` | 401 |
| Key malformed, unknown, or wrong mode | `UNKNOWN_KEY` | 401 |
| Account suspended or closed | `ACCOUNT_SUSPENDED` | 403 |
| Plan quota exhausted | `QUOTA_EXCEEDED` | 402 |
| Paid plan with no current paid entitlement | `PAYMENT_NOT_LINKED` | 402 |
| Paid enforcement requested without durable single-writer storage | `BILLING_STORAGE_NOT_READY` | 503 |
| A proved receipt cannot be appended safely | `METERING_REFUSED` | 503 |

Presenting a key always opts a caller into authentication: a bad key is
rejected rather than quietly served for free, even while enforcement is off.

## The usage ledger

Every billable unit becomes one append-only entry whose `entry_hash` commits to
the previous entry, so the revenue record is replayable the same way the proof
record is.

```json
{
  "sequence": 12,
  "period": "2026-08",
  "account_id": "acct_dsg_…",
  "sku": "verified_execution",
  "quantity": 1,
  "unit_price_micros": 100000,
  "amount_micros": 100000,
  "proof_hash": "…",
  "context_hash": "…",
  "prev_hash": "…",
  "entry_hash": "…"
}
```

- `verify_chain()` recomputes the whole chain and raises on the first mismatch.
- Reopening a tampered ledger file fails closed rather than loading it.
- Billing is idempotent on `sha256(account | sku | context_hash)`, so replaying
  the same verification context is recorded once and billed once.
- Quota recheck, included-unit pricing, and append occur under the same ledger
  lock. Two requests authorized before either proof finishes cannot cross a
  hard cap or consume the same included unit.
- Entry amounts are fixed at append time, so included-unit accounting never
  changes retroactively.

## Pricing

All money is integer micro-USD (1 USD = 1,000,000 micros); no float arithmetic
touches a price. The live catalog is served from `GET /billing/status`.

| Plan | Base / month | Included proofs | Overage | Cap |
|---|---:|---:|---:|---|
| `free` | $0 | 25 | — | hard cap at 25 |
| `metered` | $0 | 0 | $0.10 / proof | uncapped |
| `team` | $490 | 5,000 | $0.08 / proof | uncapped |
| `enterprise` | contract | 0 | contract rate | uncapped |

Per-account overrides (`unit_price_micros`, `hard_cap_units`) take precedence
over the plan, which takes precedence over the SKU list price.

## API surface

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /billing/status` | public | Catalog, checkout state, ledger head, truth boundary |
| `GET /billing/usage` | `X-DSG-API-Key` | This account's current-period usage and amount |
| `GET /billing/report` | admin bearer | All accounts for a period, with chain verification |
| `GET /billing/ledger/verify` | admin bearer | Recompute the whole hash chain |
| `POST /billing/accounts` | admin bearer | Issue an account and its one-time API key |
| `PATCH /billing/accounts/{id}` | admin bearer | Change plan, status, or entitlement |
| `POST /billing/webhook/stripe` | Stripe signature | Apply subscription and payment events |

API keys are `dsg_{live,test}_{key_id}_{secret}`. Only `sha256(secret)` is
stored, the plaintext is returned exactly once, and comparison is constant-time.

## Stripe link

The link is optional and fail-closed in both directions:

- A `STRIPE_SECRET_KEY` by itself is only `CONFIGURED_UNVERIFIED` and cannot
  make `charges_enabled` true. The public status route verifies the configured
  product, price, payment link, meter, and webhook endpoint against Stripe before it reports
  `LINKED_VERIFIED`.
- Missing or failed operational checks keep `checkout_status` at
  `NOT_VERIFIED_NOT_LINKED`; meter events remain `PENDING_UNLINKED` until the
  key and meter configuration are present.
- No `STRIPE_WEBHOOK_SECRET` → inbound webhooks are rejected with 503 rather
  than trusted, so entitlement can never be granted by an unsigned caller.

Signatures are verified against Stripe's `t=…,v1=…` scheme with a 300-second
tolerance window. A signed event must also match the configured DSG
product/price and the account's exact subscription. Event IDs and paid invoice
IDs are persisted for idempotency, test/live mode must match the configured
Stripe key, and field-level event cursors prevent stale entitlement regressions
without dropping a late plan update from another event stream.

## Automation

| Workflow | Trigger | What it does |
|---|---|---|
| `revenue-verify.yml` | PR / push / dispatch | Tests, credential scan, AST check that entitlement is resolved before the solver runs, ledger determinism, report rendering |
| `revenue-autopilot.yml` | daily 02:15 UTC / dispatch | Probes production, verifies the live chain, files evidence, and fails for any unavailable, malformed, or broken required probe |
| `deploy-cinema-production.yml` | push to main | Uses a stable configured admin credential when present, records UNAVAILABLE when absent, rejects bad keys, and checks for secret leakage |

`scripts/revenue_report.py` renders the reconciliation. It reports
`UNAVAILABLE` for any probe that failed and never estimates a missing number —
an unreachable service is not reported as zero revenue.

## Configuration

| Variable | Required | Meaning |
|---|---|---|
| `DSG_REVENUE_ADMIN_SECRET` | for admin routes | ≥32 chars; admin bearer credential |
| `DSG_REVENUE_ENFORCE` | no (default off) | `1` makes an API key mandatory on verification routes |
| `DSG_REVENUE_ACCOUNT_STORE` | no | JSON file path for the account registry |
| `DSG_REVENUE_LEDGER_STORE` | no | JSON file path for the usage ledger |
| `DSG_REVENUE_ACCOUNTS` | no | JSON array of bootstrap accounts (hashes only; plaintext secrets are rejected) |
| `STRIPE_SECRET_KEY` | to charge | Enables meter-event push |
| `STRIPE_WEBHOOK_SECRET` | for webhooks | Verifies signed inbound events |
| `STRIPE_PRODUCT_ID` | to charge | Exact DSG Stripe product scope |
| `STRIPE_PRICE_ID` | to charge | Exact DSG Stripe price scope |
| `STRIPE_PAYMENT_LINK_ID` | to claim checkout ready | Payment Link verified by `/billing/status` |
| `STRIPE_METER_ID` | to charge | Meter verified by `/billing/status` and required for pushes |
| `STRIPE_WEBHOOK_ENDPOINT_ID` | to claim ready | Registered endpoint verified through Stripe |
| `STRIPE_WEBHOOK_ENDPOINT_URL` | to claim ready | Exact public `/billing/webhook/stripe` URL |
| `STRIPE_METER_EVENT_NAME` | no | Defaults to `dsg_verified_execution` |
| `DSG_REVENUE_STORAGE_DURABLE` | before enforcement | Operator attestation that both stores are durable |
| `DSG_REVENUE_SINGLE_WRITER` | before enforcement | Operator attestation that exactly one writer serves the stores |

## Truth boundary

**Supported and verified by tests in `tests/test_revenue.py`:**

- Proof-bound metering: an unverified receipt cannot be billed.
- Fail-closed entitlement resolved before any solver work.
- Hash-chained, replayable, tamper-evident usage ledger.
- Idempotent billing per verification context.
- Signature-verified Stripe webhooks; forged and stale signatures rejected.
- Product, price, and subscription scoped webhook mutations with persisted
  event idempotency and ordering checks.
- Team base revenue is capped at the actual USD `amount_paid` for that period;
  a zero-value or missing paid amount grants neither included use nor base
  recognition.
- Hash-only API key storage with constant-time comparison.

**Not claimed:**

- **No active checkout link.** `checkout_status` stays
  `NOT_VERIFIED_NOT_LINKED` until Stripe independently confirms the configured
  product, price, Payment Link, meter, and webhook endpoint; the landing page continues to say so.
- **No durable billing storage.** The bundled stores are process memory and a
  single JSON file. Azure Container Apps filesystems are ephemeral and this
  deployment runs up to two replicas, so the ledger is **not** durable or
  single-writer in production today. This is why `DSG_REVENUE_ENFORCE`
  defaults to off: quota enforcement across restarts would not be reliable.
- **No audited revenue claim.** Recorded usage is not an invoice. The separate
  recognized figure is limited to scoped USD `invoice.paid` amounts and still
  is not an independent financial audit.
- **No completed Stripe marketplace review.**

## Activation sequence

Each step is independently verifiable, in order:

1. **Set the admin credential.** Add repository secret
   `DSG_REVENUE_ADMIN_SECRET` (≥32 chars) and redeploy. Confirm
   `GET /billing/ledger/verify` returns `verified: true`.
2. **Issue a first key.** `POST /billing/accounts` with the admin bearer.
   Store the returned `api_key`; it is not retrievable again.
3. **Confirm metering without charging.** Call `/verify/evaluate` with the key
   and check the `billing` block in the receipt and `GET /billing/usage`.
   Nothing is charged: `checkout_status` is still `NOT_VERIFIED_NOT_LINKED`.
4. **Attach durable storage.** Mount an Azure Files volume (or move the store
   to Postgres) and point `DSG_REVENUE_LEDGER_STORE` and
   `DSG_REVENUE_ACCOUNT_STORE` at it. Until this is done, do not enable
   enforcement — this is the one genuine blocker to charging.
5. **Link Stripe.** Create the product, price, Payment Link, meter, and webhook matching
   the catalog, then configure all Stripe variables above. Confirm
   `GET /billing/status` reports `LINKED_VERIFIED`, and update the landing page's
   checkout line in the same change so the public claim stays true.
6. **Turn on enforcement.** Run a single writer, set both storage attestations,
   then set `DSG_REVENUE_ENFORCE=1` and redeploy. If any prerequisite is absent,
   verification fails closed with `BILLING_STORAGE_NOT_READY` instead of
   silently serving paid traffic from unsafe storage.
