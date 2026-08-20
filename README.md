# DSG ONE — Verified Execution

DSG ONE turns a bounded automation decision into a deterministic, replayable
Proof Receipt. Cinema derives an `ALLOW`, `REVIEW`, or `BLOCK` policy decision,
the exact Z3 backend proves the global optimum, and the caller receives hashes
that bind the request, context, and proof.

This repository is the current DSG ONE system. Legacy Control Plane links and
retired runtimes are not part of the active product path.

## Public surfaces

| Surface | URL | Evidence state |
|---|---|---|
| Azure 3D landing | https://dsgoneverifiedweb.z1.web.core.windows.net/ | Receipt tracked in `.deployment/azure-3d-landing.json` |
| Render landing | https://dsg-one-verified-execution.onrender.com/ | Secondary public UI |
| Cinema API docs | https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/docs | Bounded verification API |
| GitHub Marketplace | https://github.com/marketplace/actions/dsg-secure-deploy-gate | Public v1.1.0 Action; v2 package remains prepared in this repo |

The Azure deployment receipt is the source of truth for the official landing
URL. A prepared package is not described as approved or public until the
marketplace itself confirms that state.

## End-to-end contract

```text
Marketplace / agent / app
        ↓ bounded facts + optional X-DSG-API-Key
Cinema entitlement check
        ↓ authorized before solver work
Deterministic policy mapping
        ↓ fixed ALLOW / REVIEW / BLOCK problem
Exact Z3 global-optimum proof
        ↓ verified receipt only
Proof-bound ledger + channel attribution
```

The product proves one bounded decision. It does not claim SOC 2, ISO,
regulatory compliance, legal approval, or third-party certification.

## Run a live proof

The fastest path is the [Azure 3D landing](https://dsgoneverifiedweb.z1.web.core.windows.net/).
It provides fixed, synthetic scenarios and displays a result only when the
response contains:

- `verified: true`
- `verification: VERIFIED_GLOBAL_OPTIMUM`
- a valid `decision` (`ALLOW`, `REVIEW`, or `BLOCK`)
- 64-character `proof_hash`, `request_hash`, and `context_hash`

The receipt can be downloaded as JSON. An unavailable backend never becomes an
`ALLOW` result.

For API use, activate a free key and send one bounded request:

```bash
export CINEMA_URL="https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io"

curl -X POST "$CINEMA_URL/billing/activate" \
  -H 'Content-Type: application/json' \
  -d '{"channel":"api","activation_id":"example-client-001","display_name":"Example client"}'

curl -X POST "$CINEMA_URL/verify/evaluate" \
  -H "X-DSG-API-Key: $DSG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data @verification-request.json
```

The activation key is shown once and only its hash is retained. Self-serve
activation grants the capped free plan; it cannot grant paid capacity.

## Marketplace state

| Channel | Current repository state | Next external step |
|---|---|---|
| GitHub Marketplace Action | Public v1.1.0; Verified Execution v2 prepared | Release v2 from the dedicated Action repository and publish the Marketplace update |
| Stripe Apps Marketplace | Native v2.7 package prepared | External test, Stripe CLI upload, and Stripe review |
| OpenAI Skills | Skills-only submission package prepared | Publisher verification and external submission |
| Microsoft Marketplace | Contact-me offer pack prepared | Partner Center enrollment and offer submission |
| AWS Marketplace | Blocked externally | Seller onboarding plus AWS billing and entitlement integration |
| JetBrains Marketplace | Specification only | Build/sign a plugin ZIP and submit for review |
| Direct API | Public bounded API | Keep paid enforcement off until storage and commerce gates pass |

All prepared listing metadata uses the receipt-verified Azure landing as the
product website. Detailed state and blockers live in:

- `marketplace/launch-manifest.json`
- `marketplace/SUBMISSION_QUEUE.md`
- `marketplace/README.md`
- `CHANNEL_DELIVERY.md`

## Revenue and entitlement

The billable unit is one Z3 `VERIFIED_GLOBAL_OPTIMUM` Proof Receipt. The revenue
layer provides:

- hash-only API keys and fail-closed entitlement checks before solver work;
- atomic quota recheck, included-unit pricing, and ledger append;
- a SHA-256 hash-chained usage ledger;
- event- and invoice-idempotent Stripe webhooks scoped to the configured DSG
  product, price, subscription, and test/live mode;
- scoped paid-invoice reporting that excludes unrelated invoice lines;
- reconciliation that reports `UNAVAILABLE` instead of inventing zero revenue.

Current commercial boundary:

- Checkout remains `NOT_VERIFIED_NOT_LINKED` until Stripe verifies the exact
  product, price, Payment Link, meter, webhook endpoint, API key, and secret.
- Paid enforcement also requires durable account and ledger stores plus a
  single revenue writer. If any prerequisite is absent, it fails closed with
  `BILLING_STORAGE_NOT_READY`.
- Recorded usage is not a paid invoice. Scoped `invoice.paid` receipts are
  reported separately and are not presented as an independent financial audit.

Inspect the deployed state:

```bash
curl "$CINEMA_URL/billing/status"
curl -H "X-DSG-API-Key: $DSG_API_KEY" "$CINEMA_URL/billing/usage"
curl -H "X-DSG-API-Key: $DSG_API_KEY" "$CINEMA_URL/support/diagnose"
```

See `REVENUE_AUTOMATION.md` for storage, Stripe, deployment, and reconciliation
activation gates.

## Repository map

| Path | Purpose |
|---|---|
| `cinema_main.py` | Public Cinema API, proof validation, support diagnosis |
| `marketplace_verification.py` | Bounded request and deterministic decision contract |
| `z3_main.py` | Authenticated exact Z3 backend |
| `revenue/` | Accounts, activation, pricing, entitlement, ledger, Stripe sync |
| `landing/` and `azure-landing/` | One shared browser UI artifact |
| `marketplace/` | Channel adapters, listing packs, and status evidence |
| `stripe-app/` | Stripe-native UI extension package |
| `.github/workflows/` | CI, deployment, packaging, and reconciliation |
| `tests/` | API, billing, UI-contract, and marketplace regressions |

## Local verification

```bash
python3 -m pip install -r requirements.txt -r requirements-cinema.txt pytest pyyaml
python3 -m pytest -q
bash landing/validate.sh
bash marketplace/openai-plugin/scripts/validate.sh
bash -n marketplace/github-action-v2/scripts/verified-execution.sh
```

CI additionally installs and type-checks the Stripe App package, validates the
Marketplace manifests, and runs production deployment smoke tests after merge.

## Deployment ownership

- `.github/workflows/deploy-cinema-production.yml` deploys Cinema and runs the
  production API, CORS, Marketplace, Stripe, and revenue smoke tests.
- `.github/workflows/deploy-azure-3d-landing.yml` publishes the shared landing
  artifact and writes the public Azure receipt.
- `.github/workflows/revenue-autopilot.yml` reconciles production daily and
  fails when required evidence is missing or invalid.

Paid enforcement is intentionally left off until every documented prerequisite
is present. Core verification and capped free activation remain independently
usable.
