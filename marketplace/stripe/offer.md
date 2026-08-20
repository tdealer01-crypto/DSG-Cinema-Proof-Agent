# Stripe Apps Marketplace

## Existing app identity

- App ID: `pics.dsg.governance`
- Target version: `2.7.0`
- Distribution: public
- Runtime: Stripe UI → Cinema `/stripe/evaluate` → server-side Z3 exact proof
- Client package contains no Z3 credential
- Product website: https://dsgoneverifiedweb.z1.web.core.windows.net/

## Listing copy

**Name:** DSG Governance Gate

**Short description:** Deterministic verification for Stripe payment operations with exact Z3 proof receipts.

**Core user flow:**

1. Open a supported Stripe object in the Dashboard.
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

## Submission steps outside this connector

1. Resolve the current production Cinema URL.
2. Generate the production `stripe-app.json` CSP binding.
3. Run Stripe App validation/typecheck.
4. Upload the app with Stripe CLI.
5. Complete the Stripe external test.
6. Submit version `2.7.0` for Marketplace review in the Stripe Dashboard.

The repository workflow `.github/workflows/stripe-app-v2-7.yml` already prepares a production-bound submission artifact after the live Cinema proof endpoint passes its smoke test.
