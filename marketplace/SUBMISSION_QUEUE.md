# Marketplace Submission Queue

Status meanings:

- `LIVE` — publicly discoverable/installable now.
- `READY_FOR_EXTERNAL_SUBMIT` — code/listing package prepared; external marketplace account action remains.
- `READY_FOR_EXTERNAL_UPLOAD` — production-bound artifact exists and validates; upload must happen before credentials and review evidence can be completed.
- `BLOCKED_EXTERNAL` — marketplace-specific seller/publisher onboarding or billing integration is still required.
- `SPEC_ONLY` — product/plugin artifact is not built yet.
- `IN_REMEDIATION` — a verified blocker exists; do not submit the current artifact.

Step-by-step submission instructions with pre-filled listing copy for every
channel are in [`SUBMIT_RUNBOOK.md`](SUBMIT_RUNBOOK.md).

| Priority | Channel | Status | Evidence / package | External action that cannot be performed by the current chat connector |
|---:|---|---|---|---|
| 1 | Stripe Apps Marketplace | READY_FOR_EXTERNAL_UPLOAD | PR #108 remediation, PR #109 SDK upgrade, and PR #110 deploy repair are merged. Production deploy run #56 passed; package run #127 produced artifact `stripe-app-v2.7.1-submission` (artifact `9508761420`, SHA-256 `f3b1ffc3bc46b461a2248918f82d83ede6e60ab611d385f33a5f05f1d0373bc9`). Production reports `ACTION_REQUIRED` because the app signing secret, test/sandbox developer keys, and three Dashboard-issued authorize URLs are not bound. Screenshots remain placeholders. | Upload v2.7.1, bind the generated signing secret plus exact live/test/sandbox OAuth values, rerun production until every status check is `PASS`, run External Test, capture real Dashboard evidence, then submit for review |
| 2 | GitHub Marketplace Action | LIVE_V1, V2_IN_REVIEW | v1.1.0 listing live; v2 open as `dsg-secure-deploy-gate-action#10` (Bats green) | Merge PR #10, release `v2.0.0`, tick Publish this Action to GitHub Marketplace |
| 3 | OpenAI Skills | READY_FOR_EXTERNAL_SUBMIT | `marketplace/openai-plugin/`; `scripts/validate.sh` passes | Publisher verification and external submission |
| 4 | Microsoft Marketplace | READY_FOR_EXTERNAL_SUBMIT | `marketplace/azure/offer.md` | Partner Center Marketplace enrollment and SaaS Contact-me offer submission |
| 5 | AWS Marketplace | BLOCKED_EXTERNAL | `marketplace/aws/offer.md` | Seller onboarding plus AWS Marketplace SaaS billing/entitlement integration |
| 6 | JetBrains Marketplace | SPEC_ONLY | `marketplace/jetbrains/offer.md` | Build/sign plugin ZIP, account/trader declaration, upload for manual review |
| 7 | Direct API | LIVE | Production `/health`, `/verify/evaluate`, `/docs` reachable; `/billing/status` reports `checkout_status: LINKED`, `stripe.link_state: LINKED_VERIFIED`, and metering enforced | No launch unblocker; continue post-deploy runtime monitoring |

## Do not mark a channel LIVE until

1. The marketplace itself shows the listing as public/approved, or the channel is directly verified as publicly installable.
2. The package points to the current Cinema + exact Z3 runtime, not the retired Control Plane runtime.
3. Production evidence confirms the endpoint used by the package is healthy.
4. Pricing/billing claims match the marketplace's actual billing mode.
5. Legal/compliance language does not claim certifications that have not been independently obtained.
