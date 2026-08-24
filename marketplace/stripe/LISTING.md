# Stripe App Marketplace listing — DSG Governance Gate

Use this copy only after version 2.7.1 passes its sandbox External Test. Fields
marked **BLOCKED** must not be filled with placeholder evidence.

## Identity

- **App name:** DSG Governance Gate
- **App ID:** `pics.dsg.governance`
- **Version for review:** `2.7.1`
- **Short description:** Deterministic ALLOW, REVIEW, or BLOCK decisions with an exact Z3 proof for Stripe payments.
- **Website:** https://dsgoneverifiedweb.z1.web.core.windows.net/
- **Support URL:** https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues
- **Privacy policy:** https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/stripe/PRIVACY.md

## Description

DSG Governance Gate adds a verification panel to Stripe charge and
PaymentIntent detail pages. It reads the current payment amount, currency,
status, and available Radar risk level using the permissions approved during
installation. It sends only that bounded context to the DSG Cinema backend in
a Stripe-signed request.

Cinema deterministically maps the transaction context to ALLOW, REVIEW, or
BLOCK and returns a result only when the server-side Z3 verifier proves the
global optimum. The panel shows the decision, plain-language reason, risk
score, policy version, and shortened proof and context hashes. If transaction
context, authentication, entitlement, backend availability, or proof validity
is missing, the panel shows REVIEW rather than approval.

The app does not read card numbers, accept arbitrary solver programs, expose a
solver credential, or automatically change, capture, refund, or block a Stripe
payment.

## Key features

1. **Verified payment decision** — Shows ALLOW, REVIEW, or BLOCK with the
   factors and risk score on the payment detail page.
2. **Exact proof receipt** — Shows proof and transaction-binding references
   only after the backend returns `VERIFIED_GLOBAL_OPTIMUM`.
3. **Fail-closed result** — Authentication, entitlement, timeout, or proof
   failures remain REVIEW with an actionable next step.

## Pricing

- **Free evaluation:** 25 verified proofs; no payment method required.
- **Metered:** $0 monthly base; $0.10 per Stripe policy decision proof.
- **Team:** $490 per month, including 5,000 proofs; $0.08 per additional proof.
- **Enterprise:** Contract pricing.

Installation grants only the free evaluation plan. A paid plan requires a
separate Stripe Checkout flow and a current linked entitlement.

## Reviewer test instructions

1. Install version 2.7.1 in a Stripe sandbox and complete the DSG onboarding
   redirect.
2. Create or open a test-mode charge or PaymentIntent.
3. Open its payment detail page and locate **DSG Governance Gate**.
4. Confirm the panel reaches ALLOW, REVIEW, or BLOCK and displays a risk score,
   policy version, proof reference, and transaction binding.
5. Temporarily make the Cinema endpoint unavailable or use an unlinked install
   and confirm the safe state is REVIEW, never ALLOW.

No reviewer password or DSG API key is required. The Stripe-signed install is
resolved to the free evaluation entitlement.

## Listing assets

- Icon: `stripe-app/icon.png` — validated at 300×300 PNG.
- **BLOCKED:** Key feature screenshots must be captured from the actual v2.7.1
  sandbox payment-detail panel at 1600×900 or wider after External Test passes.
- Do not use the current files in `public/stripe-marketplace/`; they are
  dimensionally valid placeholders, not product screenshots.

## Claims boundary

Do not claim that DSG is Stripe-approved before the Marketplace status says so.
Do not claim regulatory certification, prevention of fraud, or automatic
payment enforcement. The app provides a bounded policy decision and proof
receipt; the Stripe user remains responsible for payment actions.
