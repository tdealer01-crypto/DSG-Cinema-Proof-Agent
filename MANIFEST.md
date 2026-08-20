# DSG ONE — Current System Manifest

This manifest describes the active Verified Execution system. It intentionally
does not present retired Control Plane components or historical deployment
scripts as the current product path.

## Runtime

| Component | Files | Responsibility |
|---|---|---|
| Exact verifier | `z3_main.py`, `requirements.txt`, `Dockerfile` | Authenticated exact Z3 solve and proof hashes |
| Cinema | `cinema_main.py`, `marketplace_verification.py`, `requirements-cinema.txt`, `Dockerfile.cinema` | Bounded policy mapping, proof validation, public API, support diagnosis |
| Revenue | `revenue/`, `scripts/revenue_report.py` | Identity, activation, entitlement, atomic metering, scoped Stripe evidence, reconciliation |
| Browser UI | `landing/index.html`, `azure-landing/index.html` | One shared live-proof and Marketplace experience |

## Distribution

| Channel | Artifact |
|---|---|
| GitHub Marketplace | `marketplace/github-action-v2/` |
| Stripe Apps | `stripe-app/` |
| OpenAI Skills | `marketplace/openai-plugin/` |
| Microsoft Marketplace | `marketplace/azure/offer.md` |
| AWS Marketplace | `marketplace/aws/offer.md` |
| JetBrains Marketplace | `marketplace/jetbrains/offer.md` |
| Direct API | Cinema `/verify/evaluate` and `/stripe/evaluate` |

The machine-readable channel state is
`marketplace/launch-manifest.json`; external publication truth is tracked in
`marketplace/SUBMISSION_QUEUE.md`.

## Deployment evidence and automation

| Path | Purpose |
|---|---|
| `.deployment/azure-3d-landing.json` | Receipt-verified official Azure landing URL |
| `.github/workflows/deploy-cinema-production.yml` | Cinema deployment plus production E2E |
| `.github/workflows/deploy-azure-3d-landing.yml` | Shared landing deployment and receipt |
| `.github/workflows/marketplace-launch-verify.yml` | Multi-Marketplace package and UI validation |
| `.github/workflows/stripe-app-v2-7.yml` | Stripe UI validation and production package |
| `.github/workflows/revenue-verify.yml` | Entitlement, ledger, Stripe, and channel regressions |
| `.github/workflows/revenue-autopilot.yml` | Daily evidence-backed reconciliation |

## Verification coverage

- `tests/test_z3_main.py`: exact solver and proof behavior.
- `tests/test_cinema_main.py`: Cinema, CORS, bounded policy, and fail-closed proof behavior.
- `tests/test_marketplace_surfaces.py`: shared UI, status labels, links, and manifest consistency.
- `tests/test_revenue.py`: pricing, atomic quota enforcement, ledger, Stripe scope/order/idempotency, API billing.
- `tests/test_channel_delivery.py`: activation, channel attribution, remediation, and diagnosis.

## Commercial truth boundary

- Free activation is capped and cannot grant a paid plan.
- Checkout is not live until `/billing/status` verifies every configured Stripe
  commerce object.
- Paid enforcement stays off until durable account/ledger storage and a single
  writer are configured.
- Recorded usage is not represented as collected revenue. Only exact scoped
  paid-invoice evidence is reported, separately from usage, and no independent
  financial audit is claimed.

See `README.md`, `CHANNEL_DELIVERY.md`, and `REVENUE_AUTOMATION.md` for the
current operating contract.
