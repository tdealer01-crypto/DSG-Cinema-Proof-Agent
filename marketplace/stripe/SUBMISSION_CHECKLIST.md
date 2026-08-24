# Stripe Marketplace submission checklist

Do not submit until every required item is checked with current evidence.

## Build and production

- [ ] v2.7.1 changes are merged to `main`.
- [ ] Backend tests, UI build, manifest generation, and manifest validation pass in CI.
- [ ] Production is deployed from the merged commit.
- [ ] `GET /health` returns `200` and ready.
- [ ] `GET /marketplace/stripe/status` returns `READY` with every check `PASS`.
- [ ] The production app has `STRIPE_APP_SIGNING_SECRET` bound from a real `absec_...` secret.
- [ ] The managed-sandbox developer key is bound as `STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY`.
- [ ] The exact Dashboard-issued sandbox OAuth link is stored as repository
      secret `STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL` (or in Key Vault), not in
      a public repository variable.
- [ ] `/marketplace/stripe/setup?link_type=sandbox` redirects to
      `https://marketplace.stripe.com/oauth/v2/authorize` with the sandbox-specific callback URL and signed, single-use mode state.
- [ ] Live, test-mode, and managed-sandbox install links each use their own
      declared callback and matching developer key.

## Stripe upload and external test

- [ ] The latest Stripe CLI and Apps plugin are installed and authenticated to `pics.dsg.governance`.
- [ ] `stripe apps upload` accepts version 2.7.1.
- [ ] Version 2.7.1 is installed in a sandbox.
- [ ] The app is exercised with live-mode and test-mode External Test links,
      and with administrator plus restricted user roles where Stripe permits.
- [ ] The sandbox OAuth callback exchanges its code with the sandbox developer key, not the live billing key.
- [ ] A signed charge verification succeeds without a DSG API key in the UI.
- [ ] Forged, unlinked, and unavailable-backend cases remain refused or REVIEW.
- [ ] Stripe External Test passes.

## Listing

- [ ] App name exactly matches the manifest: DSG Governance Gate.
- [ ] Description and pricing match `LISTING.md` and the live catalog.
- [ ] Website, support, and privacy URLs open without authentication.
- [ ] The support email is monitored and has been tested.
- [ ] The legal **Based in** location is confirmed by the account owner.
- [ ] The listing states English support and an expected response within 2 business days.
- [ ] Three real Stripe Dashboard screenshots are captured at 1600×900 or wider.
- [ ] Placeholder images from `public/stripe-marketplace/` are not submitted.
- [ ] Public install URL—not an External Test URL—is entered for OAuth review.
- [ ] Reviewer instructions reproduce an actual sandbox result.
- [ ] No certification, fraud-prevention, or automatic-enforcement claim exceeds the tested product.

## Final action

- [ ] Review all entered fields in the Stripe Dashboard.
- [ ] Confirm the exact listing data and version immediately before clicking **Submit for review**.
- [ ] Record the resulting Stripe submission status and timestamp in this repository.
