# Stripe Marketplace submission checklist

Do not submit until every required item is checked with current evidence.

## Build and production

- [x] v2.7.1 application changes are merged to `main` by PR #108.
- [x] PR #110 fixed the deployment order and production deploy run #56 passed.
- [x] PR #109 upgraded `stripe` to 22.5.0. Registry recheck on 2026-08-24 still
      returned `stripe` 22.5.0 and `@stripe/ui-extension-sdk` 9.2.1.
- [x] Backend tests, UI build, manifest generation, and manifest validation passed in package run #127.
- [x] Production is deployed from merge commit `ee2431b6076ad2200673213f6d6f73d055afadc0`.
- [x] `GET /health` returns `200` and ready.
- [x] CI artifact `stripe-app-v2.7.1-submission` exists as artifact `9508761420`
      with recorded SHA-256 digest and a 2026-09-23 expiry.
- [ ] `GET /marketplace/stripe/status` returns `READY` with every check `PASS`.
- [ ] The production app has `STRIPE_APP_SIGNING_SECRET` bound from a real `absec_...` secret.
- [ ] The managed-sandbox developer key is bound as `STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY`.
- [ ] The exact Dashboard-issued sandbox OAuth link is stored as repository
      secret `STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL` (or in Key Vault), not in
      a public repository variable.
- [ ] `/marketplace/stripe/setup?link_type=sandbox` renders the onboarding
      instructions; its **Continue to Stripe** action redirects to
      `https://marketplace.stripe.com/oauth/v2/authorize` with the
      sandbox-specific callback URL and signed, single-use mode state.
- [ ] Live, test-mode, and managed-sandbox install links each use their own
      declared callback and matching developer key.
- [ ] `oauth_live_authorize_url` passes only with the exact Public Install URL
      copied from the app's **Settings** tab; no generic or External Test URL is
      accepted as a fallback.

## Publisher eligibility

- [ ] The Stripe account is activated and its email and business verification
      are complete.
- [ ] The account is not a Connect-enabled platform account.
- [ ] This is the only app published from the Stripe account.
- [ ] The account owner confirms the business purpose is not prohibited or
      restricted and that location/sanctions requirements permit publication.

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
- [ ] The uploaded listing logo is the same `stripe-app/icon.png` used by the
      manifest, square, at least 300×300, and under 10 MB.
- [ ] Description and pricing match `LISTING.md` and the live catalog.
- [ ] Website, support, and privacy URLs open without authentication.
- [ ] The support email is monitored and has been tested.
- [ ] The legal **Based in** location is confirmed by the account owner.
- [ ] The listing states English support and an expected response within 2 business days.
- [ ] Each of the three features has a title no longer than 80 characters, a
      description no longer than 300 characters, and a matching real Stripe
      Dashboard screenshot at least 1600 pixels wide and under 10 MB.
- [ ] Placeholder images from `public/stripe-marketplace/` are not submitted.
- [ ] The App Review URL opens the production onboarding page, whose action uses
      the Public Install URL from **Settings**, never an External Test URL.
- [ ] Reviewer guidance covers onboarding and all three key features against
      production, and a final screen recording is attached for the complex flow.
- [ ] The credentials field says no external credentials are required and
      explains the install-granted free entitlement; no real account or secret
      is submitted.
- [ ] No certification, fraud-prevention, or automatic-enforcement claim exceeds the tested product.

## Final action

- [ ] Review all entered fields in the Stripe Dashboard.
- [ ] Confirm the exact listing data and version immediately before clicking **Submit for review**.
- [ ] Record the resulting Stripe submission status and timestamp in this repository.
- [ ] Allow four business days for approval or feedback and address every item
      before resubmitting.
- [ ] After approval, open **Review and publish**, verify the final listing, and
      click **Publish**. Approval alone does not make the app public.
