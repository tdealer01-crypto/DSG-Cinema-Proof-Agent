# Marketplace Submission Queue

Status meanings:

- `LIVE` — publicly discoverable/installable now.
- `READY_FOR_EXTERNAL_SUBMIT` — code/listing package prepared; external marketplace account action remains.
- `BLOCKED_EXTERNAL` — marketplace-specific seller/publisher onboarding or billing integration is still required.
- `SPEC_ONLY` — product/plugin artifact is not built yet.

Step-by-step submission instructions with pre-filled listing copy for every
channel are in [`SUBMIT_RUNBOOK.md`](SUBMIT_RUNBOOK.md).

| Priority | Channel | Status | Evidence / package | External action that cannot be performed by the current chat connector |
|---:|---|---|---|---|
| 1 | Stripe Apps Marketplace | READY_FOR_EXTERNAL_SUBMIT | `stripe-app/` v2.7.0; all 5 blockers fixed; OAuth callback served by `revenue/stripe_marketplace.py`; images on a reachable host | Copy the app's OAuth client ID into `DSG_STRIPE_APP_OAUTH_CLIENT_ID` and redeploy, then Stripe CLI upload, External Test, Submit for review |
| 2 | GitHub Marketplace Action | LIVE_V1, V2_BLOCKED_APP_INSTALL | v1.1.0 listing live; v2 commit prepared as `marketplace/github-action-v2/dist/0001-verified-execution-gate-v2.patch` | Install the Claude GitHub App on `dsg-secure-deploy-gate-action` (push and REST both 403 today), apply the patch, release `v2.0.0`, tick Publish to Marketplace |
| 3 | OpenAI Skills | READY_FOR_EXTERNAL_SUBMIT | `marketplace/openai-plugin/`; `scripts/validate.sh` passes | Publisher verification and external submission |
| 4 | Microsoft Marketplace | READY_FOR_EXTERNAL_SUBMIT | `marketplace/azure/offer.md` | Partner Center Marketplace enrollment and SaaS Contact-me offer submission |
| 5 | AWS Marketplace | BLOCKED_EXTERNAL | `marketplace/aws/offer.md` | Seller onboarding plus AWS Marketplace SaaS billing/entitlement integration |
| 6 | JetBrains Marketplace | SPEC_ONLY | `marketplace/jetbrains/offer.md` | Build/sign plugin ZIP, account/trader declaration, upload for manual review |
| 7 | Direct API | LIVE | Production `/health`, `/verify/evaluate`, `/docs`; Stripe `LINKED_VERIFIED` with metering enforced | None — paid self-service is live |

## Do not mark a channel LIVE until

1. The marketplace itself shows the listing as public/approved, or the channel is directly verified as publicly installable.
2. The package points to the current Cinema + exact Z3 runtime, not the retired Control Plane runtime.
3. Production evidence confirms the endpoint used by the package is healthy.
4. Pricing/billing claims match the marketplace's actual billing mode.
5. Legal/compliance language does not claim certifications that have not been independently obtained.
