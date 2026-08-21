# Microsoft Marketplace — SaaS Offer Pack

## Product

**Name:** DSG Verified Execution

**Short description:** Deterministic proof receipts for AI and automated actions using Cinema + exact Z3 verification.

**Official product website:** https://dsgoneverifiedweb.z1.web.core.windows.net/

**Interactive product / customer conversion surface:** https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/app

The static Azure landing remains the repository's official public product website and discovery surface. The Cinema `/app` route is the interactive product and conversion surface because it is served by the runtime that owns verification and revenue status. Marketplace material should preserve both roles rather than replacing one with the other.

## Fastest launch path

Start with a **Contact me** SaaS listing. This creates an enterprise discovery/lead channel without requiring the transactable SaaS fulfillment integration on day one.

Azure DevOps Marketplace is a separate distribution surface. Paid Azure DevOps extensions use BYOL, so the extension must reuse DSG's existing entitlement service and must not create a second billing ledger. See `marketplace/azure-devops/`.

## Listing copy

**Offer summary:**

DSG Verified Execution verifies whether an automated action stayed inside an approved plan and deterministic constraints. It returns a replayable proof receipt with authorization status, out-of-plan rejection, exact Z3 verification, replay match, evidence completeness, trace correlation, hashes, and optional cost/run data.

**Search keywords:** AI governance, agent verification, deterministic verification, Z3, audit evidence, CI/CD governance, verified execution

**Primary use cases:**

- AI/agent action verification
- CI/CD execution proof
- regulated or audit-sensitive automation evidence
- deterministic replay and evidence correlation

## Phase 1 — Contact me

External Partner Center actions:

1. Ensure the publisher is enrolled in the Microsoft Marketplace program.
2. Create a new Software as a Service offer.
3. Choose the Contact me listing option.
4. Enter the listing copy and available evidence assets.
5. Configure lead handling in Partner Center.
6. Submit the offer for certification/review.

Use the official product website wherever Partner Center requests the product website. Use the Cinema `/app` URL wherever Partner Center permits a demo, trial, or conversion URL.

## Phase 2 — Transactable SaaS

Only switch to a transactable listing after the product implements the required Microsoft buyer onboarding and fulfillment path, including the applicable Microsoft account / Entra authentication, landing/onboarding flow, Marketplace fulfillment APIs, subscription lifecycle handling, and any selected metered-billing integration.

Microsoft can facilitate billing for transactable SaaS offers. This is different from Azure DevOps paid extensions, where BYOL leaves billing and licensing with the publisher.

## Truth boundary

`SUBMISSION_PACK_PREPARED` does not mean Microsoft has certified or approved the offer. Do not describe the product as Microsoft-certified unless Marketplace review/offer status explicitly supports that claim.
