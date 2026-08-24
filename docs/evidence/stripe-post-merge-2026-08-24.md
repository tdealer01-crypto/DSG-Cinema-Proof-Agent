# Stripe App post-merge production evidence — 2026-08-24

Status: **PRODUCTION PACKAGE READY FOR EXTERNAL UPLOAD — MARKETPLACE NOT LIVE**

Observed at `2026-08-24T08:07:00Z` against the public Azure production
service and GitHub Actions evidence.

## Merged changes

- PR #108: v2.7.1 application remediation.
- PR #109: Stripe Node SDK 22.5.0 compatibility upgrade, merge commit
  `db855fec37adba391da89f3cb21c3ca0783b9889`.
- PR #110: production deployment-order and review-flow repair, merge commit
  `ee2431b6076ad2200673213f6d6f73d055afadc0`.

## GitHub Actions proof

- `Deploy Cinema + Z3 Production` run #56 (`32695738183`): `success`.
  The production contract tests, Z3 proof, Cinema deployment, replay, CORS,
  revenue truth checks, and evidence upload all passed.
- `Stripe App v2.7 Verify and Package` run #127 (`32695738151`): `success`.
  Both jobs passed, including production URL binding, manifest validation,
  TypeScript build/tests, archive creation, and artifact upload.
- Artifact: `stripe-app-v2.7.1-submission` (`9508761420`).
- Artifact digest:
  `sha256:f3b1ffc3bc46b461a2248918f82d83ede6e60ab611d385f33a5f05f1d0373bc9`.
- Artifact expiry: `2026-09-23T06:04:11Z`.

The downloaded outer archive independently hashed to the same SHA-256 value.
Its inner `stripe-app-v2.7.1.zip` contains 17 entries. The generated manifest
identifies `pics.dsg.governance` version 2.7.1 as a public, sandbox-compatible
OAuth app; binds `stripe.dashboard.payment.detail` to `ChargeGate`; lists only
the three Azure callback URLs; and limits `connect-src` to the production
`/stripe/evaluate` endpoint. Its lockfile resolves `stripe` 22.5.0 and
`@stripe/ui-extension-sdk` 9.2.1.

## Live production proof

- `GET /health`: HTTP 200, `status=ready`, `backend=ready`.
- `GET /openapi.json`: version `1.3.0`; exposes:
  - `/marketplace/stripe/status`
  - `/marketplace/stripe/setup`
  - `/marketplace/stripe/callback/{callback_link_type}`
  - `/stripe/evaluate`
- `GET /billing/status`: HTTP 200; `checkout_status=LINKED`,
  `stripe.link_state=LINKED_VERIFIED`, charges enabled, catalog and operational
  scopes configured, all four operational checks `PASS`, metering enforced,
  and 359 ledger entries with a non-empty `head_hash`.

## Exact remaining Stripe Marketplace blockers

`GET /marketplace/stripe/status` returns HTTP 200 and `ACTION_REQUIRED`.

Passing checks:

- durable store
- app ID
- OAuth client ID
- live/test/sandbox callback URIs
- live OAuth developer key
- billing Stripe secret key

Missing checks:

- `oauth_live_authorize_url`
- `oauth_test_authorize_url`
- `oauth_sandbox_authorize_url`
- `oauth_test_secret_key`
- `oauth_sandbox_secret_key`
- `app_signing_secret`

The app signing secret does not exist until the first Stripe App upload. The
three authorize URLs and non-live developer keys must be copied from the
corresponding Stripe Dashboard Settings or External Test surfaces. They must
not be invented or derived from the live billing key.

## Next executable gate

1. Authenticate the Stripe CLI to `pics.dsg.governance`.
2. Recheck the npm registry, then upload version 2.7.1.
3. Bind the generated app signing secret and exact mode-specific OAuth values.
4. Rerun production and require every `/marketplace/stripe/status` check to be
   `PASS` with overall status `READY`.
5. Run External Test, capture three real Dashboard images and the review
   recording with synthetic data, then submit for review.

This evidence does not claim that Stripe has uploaded, tested, reviewed,
approved, or published the app.
