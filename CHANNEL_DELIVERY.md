# Sales Channel → Delivered Value → Instant Resolution

The verification product had listings and a working API, but the two were not
joined. Someone who found the product on GitHub, Stripe, or an agent
marketplace could not get from "interested" to "working proof" without a human:
the landing page's paid call to action opened a GitHub issue form, an API key
required an operator, and every refusal returned a bare HTTP status.

This document describes the automated path that closes those gaps.

## The funnel, end to end

```
marketplace listing / landing page
        │
        ▼
POST /billing/activate          ← self-serve, no operator, free tier
        │  api_key (returned once)
        ▼
POST /verify/evaluate           ← entitlement checked before any solver work
        │  X-DSG-API-Key
        ▼
Cinema → exact Z3 → VERIFIED_GLOBAL_OPTIMUM
        │
        ├─→ proof receipt to the caller
        └─→ metered + attributed to the acquiring channel
```

At every refusal the response carries a `remediation` object, so a blocked user
is told what to do rather than left to decode a status code.

## 1. Activation: from listing to working key

`POST /billing/activate`

```json
{"channel": "github", "activation_id": "acme-corp/deploy-pipeline", "display_name": "Acme Deploy"}
```

Returns `201` with a one-time `api_key`, the granted plan, and the next call to
make. Three properties keep it safe to expose publicly:

- **Idempotent** on `(channel, activation_id)`, case-insensitively. Concurrent
  retries are serialized in the running service and return
  `409 ACTIVATION_EXISTS` instead of quietly creating a second account.
- **Rate limited** by a sliding window, per channel and overall, with
  `retry_after_seconds` and a `Retry-After` header when limited.
- **Free tier only.** Activation grants the `free` plan and nothing else. A paid
  entitlement still requires Stripe, so this route can never hand out billable
  capacity.

The `activation_id` is stored only as a SHA-256 reference, so a private repo
slug or agent identifier is never retained in clear text.

Set `DSG_ACTIVATION_ENABLED=0` to turn self-serve activation off; the endpoint
then returns `503 ACTIVATION_DISABLED` with the operator path.

## 2. Attribution: which channel actually earns

Two different questions get two different answers, and the report keeps them
apart:

| Field | Meaning |
|---|---|
| `accounts_acquired` | Accounts whose **activation** came through this channel |
| `units` / `amount_micros` | Proofs **delivered** through this channel this period |
| `active_accounts` | Distinct accounts that verified through this channel |

A customer acquired through GitHub (`github`) who later verifies through the
direct API (`api`) is counted once in each column, not double-counted as
revenue. The browser landing records `azure`, `render`, or `api` from its actual
host instead of attributing every browser proof to Azure.
`GET /billing/report` includes the breakdown as `by_channel`.

## 3. Remediation: every refusal carries its fix

Every denial returns the same shape, from every surface:

```json
{
  "code": "QUOTA_EXCEEDED",
  "problem": "This billing period's proof quota is used up.",
  "cause": "The plan's hard cap was reached, so further proofs are refused rather than served free.",
  "next_step": "Move to the metered plan and link a payment method, or wait for the next UTC month when the free quota resets.",
  "self_service": true,
  "endpoint": "GET /billing/usage",
  "docs": "…"
}
```

`self_service` tells the caller whether they can fix it alone or need an
operator, so a client never sends someone in circles.

## 4. Diagnosis: answering "why is this not working?"

`GET /support/diagnose` takes an optional `X-DSG-API-Key` and needs no other
credential. It returns a checklist and the single blocking problem:

| Check | Answers |
|---|---|
| `service_configuration` | Is the deployment configured at all? |
| `verification_backend` | Is the exact Z3 verifier ready? |
| `billing_storage` | Is paid enforcement backed by durable single-writer storage? |
| `api_key` | Was a key presented, and does it match an account? |
| `account_status` | Is the account active? |
| `quota` | How many proofs are used and how many remain? |
| `paid_entitlement` | Is the required payment method linked and the current base invoice paid? |

Overall `status` is `READY`, `ACTION_REQUIRED` (the caller can fix it), or
`SERVICE_UNAVAILABLE` (the service must). An unrecognised key gets only
pass/fail — the route never confirms whether a specific key exists.

## Channel wiring

| Channel | How it connects | On refusal |
|---|---|---|
| **GitHub Action v2** | Optional `api_key` input sent as `X-DSG-API-Key` | Writes the problem and next step to `$GITHUB_STEP_SUMMARY` and exposes a `remediation` output |
| **OpenAI Skill** | Optional `DSG_API_KEY` env var; `SKILL.md` documents activation | `verify.sh` prints problem, cause, next step, and `self_service` for the agent to relay |
| **Stripe App** | Sends bounded transaction context as before | Banner shows the next step and whether the merchant can resolve it, still failing closed to REVIEW |
| **Landing page** | "Activate a free key" button calls `/billing/activate`, stores the key in the browser, and sends it on the next proof | Result panel shows the problem and the next step instead of an HTTP code |

Every channel keeps working without a key wherever public evaluation is open.
A key adds metering and attribution; it is not a gate until
`DSG_REVENUE_ENFORCE=1`.

## Truth boundary

**Supported, and covered by `tests/test_channel_delivery.py`:**

- Self-serve activation that is idempotent, rate limited, and free-tier only.
- Channel attribution separating acquisition from delivery.
- A concrete, non-empty next step for every denial code.
- A diagnosis endpoint that names the blocking problem without leaking account
  existence for an unknown key.

**Not claimed:**

- **No checkout.** Activation grants the free tier. `checkout_status` remains
  `NOT_VERIFIED_NOT_LINKED` until Stripe is configured, and the landing page
  still says so.
- **No durable storage.** Activation records live in the same non-durable store
  as the rest of the revenue system, so an activation can be lost on restart
  until a durable store is attached. Cross-replica idempotency is therefore not
  claimed. See `REVENUE_AUTOMATION.md`.
- **No marketplace listing status changes.** Wiring a package to the API does
  not publish or approve it; `marketplace/SUBMISSION_QUEUE.md` remains the
  source of truth for each channel's real listing state.
