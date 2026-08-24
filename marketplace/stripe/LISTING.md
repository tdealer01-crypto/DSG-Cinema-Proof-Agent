# Stripe App Marketplace listing — DSG Governance Gate

Use this copy only after version 2.7.1 passes its sandbox External Test and the
same candidate is deployed to production. Fields marked **BLOCKED** must not be
filled with placeholder evidence.

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
- **OAuth source gate:** **BLOCKED** until production status confirms that the
  live authorize URL is the exact Public Install URL copied from the app's
  **Settings** tab. Never substitute an External Test URL.
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

### Feature 1

- **Title:** Verified payment decision
- **Description:** View ALLOW, REVIEW, or BLOCK with a plain-language reason
  and risk score on the payment detail page. DSG provides guidance only and
  never captures, refunds, or blocks a payment automatically.
- **Image:** **BLOCKED** — final Dashboard screenshot of this exact panel state.

### Feature 2

- **Title:** Exact proof receipt
- **Description:** See the policy version and shortened proof reference only
  after the backend returns an exact Z3 global-optimum verification, making the
  displayed decision traceable to its proof receipt.
- **Image:** **BLOCKED** — final Dashboard screenshot showing these exact fields.

### Feature 3

- **Title:** Transaction-bound verification
- **Description:** Match the shortened context reference to the current Stripe
  payment. The binding prevents a verified result for one transaction from
  being presented as the result for another.
- **Image:** **BLOCKED** — final Dashboard screenshot showing this exact field.

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

These steps cover onboarding and all three listed features against the
production Cinema service without requiring a destructive or artificial
outage.

1. Open the App Review URL above. Read the onboarding page, select **Continue
   to Stripe**, review the requested Payments read permission, and approve the
   install in Stripe's review account.
2. After Stripe returns to DSG, return to the Stripe Dashboard and open a
   synthetic test-mode charge or PaymentIntent with a final status.
3. On its payment detail page, open **DSG Governance Gate**. The panel verifies
   the current object automatically; **Retry verification** appears only when
   the first attempt cannot complete.
4. Confirm Feature 1: the panel displays ALLOW, REVIEW, or BLOCK with its reason
   and risk score.
5. Confirm Feature 2: the same completed result displays the policy version,
   **Z3 global optimum verified**, and a shortened proof reference.
6. Confirm Feature 3: the same completed result displays a shortened context
   reference bound to the open charge or PaymentIntent.

**Test credentials:** No external DSG credentials are required. The
Stripe-authorized install grants a free 25-proof monthly entitlement, and UI
requests are signed by Stripe. Do not enter a real customer account, DSG API
key, or shared password in the review form. If the form requires credentials
despite this credential-free flow, contact Stripe Support instead of inventing
an account.

**BLOCKED — screen recording:** Record the final onboarding and three-feature
flow above after production deployment. Use only synthetic Stripe test data and
show no credentials, customer data, debug overlays, or secrets.

## Listing assets

- Icon: `stripe-app/icon.png` — validated at 300×300 PNG.
- **BLOCKED:** Each key-feature screenshot must match its title and description
  and be captured from the final v2.7.1 payment-detail panel at least 1600
  pixels wide, after External Test passes. Use synthetic data and no debug or
  in-progress testing state.
- Do not use the current files in `public/stripe-marketplace/`; they are
  dimensionally valid placeholders, not product screenshots.

## Claims boundary

Do not claim that DSG is Stripe-approved before the Marketplace status says so.
Do not claim regulatory certification, prevention of fraud, or automatic
payment enforcement. The app provides a bounded policy decision and proof
receipt; the Stripe user remains responsible for payment actions.
