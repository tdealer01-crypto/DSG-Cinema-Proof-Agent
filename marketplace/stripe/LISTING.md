# Stripe App Marketplace listing — DSG Governance Gate

Use this copy only after version 2.7.1 passes its sandbox External Test. Fields
marked **BLOCKED** must not be filled with placeholder evidence.

## Identity

- **App name:** DSG Governance Gate
- **App ID:** `pics.dsg.governance`
- **Version for review:** `2.7.1`
- **Built by:** Thanawat Suparongsuwan
- **Category:** Data and analytics
- **Works with:** Payments
- **Subtitle:** Exact Z3-verified policy decisions for Stripe payments.
- **Website:** https://dsgoneverifiedweb.z1.web.core.windows.net/
- **Support URL:** https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues
- **Support email:** t.dealer01@dsg.pics
- **Expected support response:** Within 2 business days.
- **Privacy policy:** https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/stripe/PRIVACY.md
- **Pricing page:** https://dsgoneverifiedweb.z1.web.core.windows.net/#pricing
- **Public OAuth onboarding URL for review:** https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/marketplace/stripe/setup?link_type=live
- **Supported language:** English
- **BLOCKED — Based in:** Confirm the legal headquarters location in the Stripe Dashboard; do not infer it from repository or account data.

## Description

**About field (under 1,000 characters):** DSG builds deterministic verification
tools for teams that need auditable automation decisions. DSG Governance Gate
reads bounded payment context from the Stripe Dashboard and returns ALLOW,
REVIEW, or BLOCK only when its backend receives an exact Z3 global-optimum
proof; it never captures, refunds, or blocks payments automatically.

The app reads the current payment amount, currency, status, and available Radar
risk level using the permissions approved during installation. The panel shows
the decision, plain-language reason, risk score, policy version, and shortened
proof and context hashes. Missing context, authentication, entitlement,
availability, or proof validity remains REVIEW rather than approval. The app
does not read card numbers, accept arbitrary solver programs, or expose a
solver credential.

## Key features

1. **Verified payment decision** — Shows ALLOW, REVIEW, or BLOCK with the
   factors and risk score on the payment detail page.
2. **Exact proof receipt** — Shows proof and transaction-binding references
   only after the backend returns `VERIFIED_GLOBAL_OPTIMUM`.
3. **Fail-closed result** — Authentication, entitlement, timeout, or proof
   failures remain REVIEW with an actionable next step.

## Pricing

- **Dashboard pricing selection:** Free. The permanent 25-proof monthly plan
  remains usable without payment; optional paid upgrades are disclosed below.
- **Free evaluation:** 25 verified proofs; no payment method required.
- **Metered:** $0 monthly base; $0.10 per Stripe policy decision proof.
- **Team:** $490 per month, including 5,000 proofs; $0.08 per additional proof.
- **Enterprise:** Contract pricing.

Installation grants only the free evaluation plan. A paid plan requires a
separate Stripe Checkout flow and a current linked entitlement.

## Reviewer test instructions

1. Open `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/marketplace/stripe/setup?link_type=sandbox`,
   install version 2.7.1 in a Stripe sandbox, and complete the DSG onboarding
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
