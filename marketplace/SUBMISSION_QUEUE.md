# Marketplace Submission Queue

Status meanings:

- `LIVE` — publicly discoverable/installable now.
- `READY_FOR_EXTERNAL_SUBMIT` — code/listing package prepared; external marketplace account action remains.
- `BLOCKED_EXTERNAL` — marketplace-specific seller/publisher onboarding or billing integration is still required.
- `SPEC_ONLY` — product/plugin artifact is not built yet.

| Priority | Channel | Status | Evidence / package | External action that cannot be performed by the current chat connector |
|---:|---|---|---|---|
| 1 | GitHub Marketplace Action | LIVE | Existing `DSG Secure Deploy Gate` v1.1.0 listing; v2 package under `marketplace/github-action-v2/` | Copy v2 to the dedicated Action repo, create a release, select Publish this Action to GitHub Marketplace |
| 2 | Stripe Apps Marketplace | READY_FOR_EXTERNAL_SUBMIT | `stripe-app/` v2.7.0 + production packaging workflow | Stripe CLI upload, External Test, Submit for review in Stripe Dashboard |
| 3 | OpenAI Skills | READY_FOR_EXTERNAL_SUBMIT | `marketplace/openai-plugin/` | Publisher verification and external submission |
| 4 | Microsoft Marketplace | READY_FOR_EXTERNAL_SUBMIT | `marketplace/azure/offer.md` | Partner Center Marketplace enrollment and SaaS Contact-me offer submission |
| 5 | AWS Marketplace | BLOCKED_EXTERNAL | `marketplace/aws/offer.md` | Seller onboarding plus AWS Marketplace SaaS billing/entitlement integration |
| 6 | JetBrains Marketplace | SPEC_ONLY | `marketplace/jetbrains/offer.md` | Build/sign plugin ZIP, account/trader declaration, upload for manual review |
| 7 | Direct API | LIVE | Production `/health`, `/verify/evaluate`, and `/docs` | Add customer auth/metering before paid self-service |

## Do not mark a channel LIVE until

1. The marketplace itself shows the listing as public/approved, or the channel is directly verified as publicly installable.
2. The package points to the current Cinema + exact Z3 runtime, not the retired Control Plane runtime.
3. Production evidence confirms the endpoint used by the package is healthy.
4. Pricing/billing claims match the marketplace's actual billing mode.
5. Legal/compliance language does not claim certifications that have not been independently obtained.
