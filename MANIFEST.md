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
| `.github/workflows/coverage-verify.yml` | Complete pytest run plus measured overall/line/branch coverage gate and artifacts |
| `.github/workflows/marketplace-launch-verify.yml` | Multi-Marketplace package and UI validation |
| `.github/workflows/stripe-app-v2-7.yml` | Stripe UI validation and production package |
| `.github/workflows/revenue-verify.yml` | Entitlement, ledger, Stripe, and channel regressions |
| `.github/workflows/revenue-autopilot.yml` | Daily evidence-backed reconciliation |

## Verification coverage

The complete workflow/test/E2E inventory and coverage contract is maintained in:

- [`docs/CI_CD_TEST_E2E_COVERAGE.md`](docs/CI_CD_TEST_E2E_COVERAGE.md)

Current reviewed inventory: **44 GitHub Actions workflow files**, **40 primary `tests/test_*.py` modules**, two additional test/check utilities, and one additional hackathon client test module.

The first successful instrumented baseline on PR #151 ran **509 tests** and measured **76.16% overall**, **79.79% line coverage**, and **62.77% branch coverage** across 56 selected active runtime files. The enforced floors are **76.00% overall**, **79.50% line**, and **62.50% branch**. The coverage workflow emits `coverage.xml`, `coverage.json`, `coverage-gate.json`, and HTML evidence as commit-bound GitHub Actions artifacts.

These measurements establish tested execution coverage only; they do not replace staging/production E2E, deployment proof, external marketplace acceptance, legal correctness, or certification claims.

## Commercial truth boundary

- Free activation is capped and cannot grant a paid plan.
- Checkout is not live until `/billing/status` verifies every configured Stripe
  commerce object.
- Paid enforcement stays off until durable account/ledger storage and a single
  writer are configured.
- Recorded usage is not represented as collected revenue. Only exact scoped
  paid-invoice evidence is reported, separately from usage, and no independent
  financial audit is claimed.

See `README.md`, `CHANNEL_DELIVERY.md`, `REVENUE_AUTOMATION.md`, and
`docs/CI_CD_TEST_E2E_COVERAGE.md` for the current operating and verification contract.
