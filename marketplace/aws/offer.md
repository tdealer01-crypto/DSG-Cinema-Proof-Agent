# AWS Marketplace — SaaS Offer Pack

## Product

**Name:** DSG Verified Execution

**Short description:** Deterministic Z3 proof receipts for AI and automated actions.

**Product website:** https://dsgoneverifiedweb.z1.web.core.windows.net/

**Long description:** DSG Verified Execution verifies whether an automated action stayed inside an approved plan and deterministic constraints, then returns an exact Z3-backed proof receipt containing authorization completion, out-of-plan rejection, replay match, evidence completeness, proof hashes, and optional cost/run data.

## Recommended AWS offer type

SaaS product.

## Buyer onboarding target

After an AWS Marketplace buyer subscribes, the buyer should be sent to a DSG registration/onboarding page that:

1. accepts the AWS Marketplace registration token,
2. identifies the subscribed customer,
3. creates or links the DSG workspace,
4. grants the purchased entitlement,
5. sends usage/metering only through the AWS Marketplace integration for the AWS-billed plan.

## Technical integration still required before a paid public listing

- AWS Marketplace Seller onboarding
- SaaS registration endpoint
- ResolveCustomer/customer identity integration
- entitlement/subscription lifecycle handling
- AWS Marketplace metering or contract entitlement integration
- SNS/EventBridge subscription event handling where applicable
- billing dimensions/pricing configured in AWS Marketplace

## Billing truth boundary

For an AWS Marketplace SaaS plan, customer payment for the listed product must be handled through AWS Marketplace billing dimensions. Do not route an AWS Marketplace subscriber to a separate card checkout for the same listed entitlement.

## Initial listing assets

**Category:** DevOps / Security / AI governance (choose the closest categories available in Seller Portal)

**Highlights:**

- Agent-neutral Verified Execution API
- exact Z3 global-optimum proof
- deterministic Proof Receipt hashes
- plan alignment and out-of-plan rejection evidence
- replay/evidence completeness fields

**Support surface:** repository documentation and issue tracker until a dedicated support portal is published.

## Status

`SUBMISSION_PACK_PREPARED` — not yet a paid AWS Marketplace public listing. External seller-account and billing/entitlement integration are required before submission can truthfully claim transactable SaaS readiness.
