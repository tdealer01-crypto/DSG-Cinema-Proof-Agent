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
  product, price, meter, and webhook endpoint against Stripe before it reports
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
| `STRIPE_METER_ID` | to charge | Meter verified by `/billing/status` and required for pushes |
| `STRIPE_WEBHOOK_ENDPOINT_ID` | to claim ready | Registered endpoint verified through Stripe |
| `STRIPE_WEBHOOK_ENDPOINT_URL` | to claim ready | Exact public `/billing/webhook/stripe` URL |
| `STRIPE_METER_EVENT_NAME` | no | Defaults to `dsg_verified_execution` |
| `DSG_REVENUE_STORAGE_DURABLE` | before enforcement | Operator attestation that both stores are durable |
| `DSG_REVENUE_SINGLE_WRITER` | before enforcement | Operator attestation that exactly one writer serves the stores |

### Supplying these to production

The production deployment reads the Stripe catalog ids from repository
*variables*, not secrets: an object id identifies what to charge for, it does
not authorise a charge. The credentials stay in Key Vault.

| Repository variable | Becomes |
|---|---|
| `DSG_STRIPE_PRODUCT_ID` | `STRIPE_PRODUCT_ID` |
| `DSG_STRIPE_PRICE_ID` | `STRIPE_PRICE_ID` |
| `DSG_STRIPE_METER_ID` | `STRIPE_METER_ID` |
| `DSG_STRIPE_METER_EVENT_NAME` | `STRIPE_METER_EVENT_NAME` (defaults to `dsg_verified_execution`) |
| `DSG_STRIPE_WEBHOOK_ENDPOINT_ID` | `STRIPE_WEBHOOK_ENDPOINT_ID` |
| `DSG_STRIPE_WEBHOOK_ENDPOINT_URL` | `STRIPE_WEBHOOK_ENDPOINT_URL` |

A product and a price together are the minimum catalog scope. Below that the
app has nothing to charge against, so it scopes webhooks closed however many
credentials it holds, and the deployment asserts exactly that rather than
claiming checkout is ready on the strength of a key.

## Durable storage

Enforcement refuses to start until the ledger and the account registry survive a
restart and have a single writer. The production deployment now arranges both:

- An Azure Files share is created and registered with the Container Apps
  environment, then mounted at `/revenue`. `DSG_REVENUE_ACCOUNT_STORE` and
  `DSG_REVENUE_LEDGER_STORE` point at that mount, so the data outlives any
  revision.
- `DSG_REVENUE_SINGLE_WRITER` is **derived from the replica ceiling, not
  declared**. When `DSG_REVENUE_ENFORCE=1` the Cinema app is pinned to one
  replica; otherwise the attestation stays `0`. An attestation that did not
  match the deployment would let paid gating run on a ledger two replicas were
  racing to rewrite.
- After deploying, the workflow verifies the ledger head, restarts the revision,
  and requires the same head to come back. A ledger on ephemeral storage returns
  a genesis head and fails the deployment.

### Why the stores lock across processes

A Container Apps revision switch briefly runs the old and new replica together.
Persistence rewrites the whole file from memory, so two processes each holding a
stale view silently drop each other's writes — and the surviving chain still
verifies, which makes the loss invisible.

Measured on the pre-fix code with four concurrent writers appending 100 entries
in total: **25 entries survived, 75 were lost, three writers crashed racing the
same temporary filename, and `verify_chain` still reported `verified: true`.**

Both stores now take an advisory `flock` on a sidecar file and re-read before
every read-modify-write. The lock is on a sidecar because the data file is
replaced by rename, which would drop a lock held on the old inode. The same
scenario now keeps all 100 entries with a dense sequence and an intact chain.

This also fixed a live entitlement bug: a Stripe webhook upgrading a paying
customer on one replica was reverted to the free plan by an unrelated write on
another.

**Scale path.** Azure Files with one writer is correct, not fast. A shared JSON
file rewritten per append is fine at current volume and becomes the bottleneck
long before it becomes wrong. Postgres remains the answer for concurrency across
many writers.

### PostgreSQL cutover contract

`DSG_REVENUE_DATABASE_URL` selects the PostgreSQL account registry **and** the
PostgreSQL ledger, as well as guarded evidence. Adding that secret is therefore
not a guarded-evidence-only change and must never switch a populated deployment
by itself.

The production switch is owned by the manual
`cutover-revenue-postgres.yml` workflow. It runs only from `main` after the
operator types `CUTOVER_REVENUE_TO_POSTGRES`, and performs this fail-closed
sequence:

1. Confirm the live backend is the durable file store, guarded memory contains
   zero rows, and the app uses single-revision mode.
2. Deploy a read-only revision, prove mutations return retryable HTTP 503, and
   require the ledger count and chain head to stop changing.
3. Disable ingress and download the authoritative `accounts.json` and
   `ledger.json` directly from the mounted Azure Files share.
4. Validate every source row and the complete ledger chain. If PostgreSQL
   already contains divergent rows, replacement is refused unless the operator
   explicitly enables archival. The displaced account, ledger, and guarded
   rows are retained in `dsg_revenue_cutover_archive`.
5. Replace the target inside one advisory-locked transaction, read every row
   back, and commit only when account fingerprint, ledger count, chain head, and
   every stored field match.
6. Start PostgreSQL in read-only mode, verify the running service reports the
   PostgreSQL backends and the exact frozen ledger head, then unfreeze writes.

Any failure before the frozen PostgreSQL runtime proves exact parity updates the
Container App back to the unchanged file stores and re-enables ingress. Once
that runtime passes, PostgreSQL becomes authoritative before writes are
unfrozen; a later unfreeze/probe failure deliberately leaves PostgreSQL
read-only instead of risking loss of a newly accepted database write. A
successful cutover writes `DSG_REVENUE_POSTGRES_ENABLED=1` to the live Container
App; later deployments preserve PostgreSQL only when that marker is present and
refuse to fall back if the database secret is unavailable. Re-running the
cutover workflow with that marker present verifies the current database chain
and safely resumes an interrupted unfreeze; it never imports the files again.

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

- **No Payment Link for the metered price.** `checkout_status` stays
  `NOT_VERIFIED_NOT_LINKED` until Stripe independently confirms the configured
  product, price, meter, and webhook endpoint. Current production has passed
  those checks and reports `LINKED`. Stripe Payment Links do not support
  usage-based prices, so checkout is a server-created Checkout Session against
  the same product/price instead.
- **Durable storage is arranged by the deployment, not by this repository.**
  The share is created on first deploy; until that deploy has run against the
  subscription, the stores are memory-only and enforcement stays refused.
- **One writer, not many.** Correctness comes from pinning to a single replica.
  This caps throughput and means enforcement and horizontal scale cannot both be
  on until the stores move to Postgres.
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
3. **Confirm metering before upgrade.** Call `/verify/evaluate` with the free
   key and check the `billing` block in the receipt and `GET /billing/usage`.
   The free plan itself creates no charge even when production
   `checkout_status` is `LINKED`.
4. **Attach durable storage.** Mount an Azure Files volume (or move the store
   to Postgres) and point `DSG_REVENUE_LEDGER_STORE` and
   `DSG_REVENUE_ACCOUNT_STORE` at it. Until this is done, do not enable
   enforcement — this is the one genuine blocker to charging.
5. **Link Stripe.** Create the product, price, meter, and webhook matching
   the catalog (a Payment Link cannot be used — Stripe does not support
   metered prices on Payment Links), then configure all Stripe variables
   above. Confirm `GET /billing/status` reports `LINKED_VERIFIED`, and update
   the landing page's checkout line in the same change so the public claim
   stays true.
6. **Turn on enforcement.** Run a single writer, set both storage attestations,
   then set `DSG_REVENUE_ENFORCE=1` and redeploy. If any prerequisite is absent,
   verification fails closed with `BILLING_STORAGE_NOT_READY` instead of
   silently serving paid traffic from unsafe storage.
