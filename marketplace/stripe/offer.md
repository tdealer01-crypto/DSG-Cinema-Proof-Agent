# Stripe Apps Marketplace

## Existing app identity

- App ID: `pics.dsg.governance`
- Target version: `2.7.1`
- Distribution: public
- Runtime: Stripe UI → Cinema `/stripe/evaluate` → server-side Z3 exact proof
- Client package contains no Z3 credential
- Product website: https://dsgoneverifiedweb.z1.web.core.windows.net/

## Listing copy

**Name:** DSG Governance Gate

**Short description:** Deterministic verification for Stripe payment operations with exact Z3 proof receipts.

**Core user flow:**

1. Open a charge or PaymentIntent in the Stripe Dashboard.
2. DSG evaluates bounded transaction context.
3. Cinema maps the context to ALLOW / REVIEW / BLOCK.
4. Z3 proves the exact global optimum.
5. The Stripe App displays decision, reason, verification status, and proof hash.

## Review truth boundary

Supported claims:

- exact Z3-backed decision proof
- deterministic context hash
- bounded Stripe transaction policy input
- fail-closed behavior when proof is missing or invalid

Do not claim certification or regulatory compliance without independent evidence.

## Submission sequence

1. Resolve the current production Cinema URL.
2. Generate the production `stripe-app.json` CSP binding.
3. Run manifest validation, backend tests, and the UI build.
4. Upload the app with Stripe CLI. Upload must happen before signed-request
   testing because Stripe creates the app signing secret during the first upload.
5. Bind the app signing secret to production as `STRIPE_APP_SIGNING_SECRET`.
6. Bind the test-mode and managed-sandbox developer keys as
   `STRIPE_APP_OAUTH_TEST_SECRET_KEY` and
   `STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY`; OAuth codes are exchanged with the
   key matching both the callback path and signed, single-use `state`.
7. Copy the managed-sandbox External Test authorize URL into its secret and
   the exact live Public Install URL from the app's **Settings** tab into
   `DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL`. Never use an External Test URL
   for App Review.
8. Start sandbox onboarding at
   `/marketplace/stripe/setup?link_type=sandbox`, read the instructions, select
   **Continue to Stripe**, install version `2.7.1`, and complete External Test.
9. Deploy the same candidate to production and verify every Stripe Marketplace
   status check passes, including the live Settings URL.
10. Capture three real Stripe Dashboard screenshots at least 1600 pixels wide
    plus a screen recording from the final candidate, using synthetic data.
11. Fill the listing, verify support/privacy links and publisher eligibility,
    submit version `2.7.1`, and publish only after Stripe approves it.

The repository workflow `.github/workflows/stripe-app-v2-7.yml` prepares a
production-bound submission artifact only after the live Cinema proof endpoint,
manifest contract, backend tests, and UI build pass. The workflow artifact is
not Marketplace approval and is not sufficient without the external test.
