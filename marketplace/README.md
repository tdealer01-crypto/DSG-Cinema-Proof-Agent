# DSG Verified Execution — Marketplace Launch Control Center

Product runtime:

`Any Agent / App → Approved Plan / Policy → Cinema → deterministic policy mapping → exact Z3 proof → Proof Receipt`

The marketplace adapters do not contain the Z3 credential and do not accept arbitrary solver programs. The shared backend endpoint is `/verify/evaluate`.

## Shared product promise

**DSG Verified Execution creates deterministic proof receipts showing whether an automated action was authorized, aligned with the approved plan, constraint-correct, replay-matching, and evidence-complete.**

Supported evidence fields in the receipt:

- `authorized_action_completion`
- `out_of_plan_rejection`
- `z3_constraint_correctness`
- `replay_match`
- `evidence_completeness`
- `cost_microunits`
- `proof_hash`
- `request_hash`
- `context_hash`

The service does **not** claim SOC 2, ISO, regulatory, or third-party certification unless independent certification evidence exists.

## Channel status

| Channel | Current state | What is sellable now | Remaining external action |
|---|---|---|---|
| GitHub Marketplace Action | LIVE v1.1.0 | Existing DSG Secure Deploy Gate is publicly installable | Publish the prepared Verified Execution v2 release from the dedicated Action repo |
| Stripe Apps Marketplace | v2.7.1 upload artifact ready; production status `ACTION_REQUIRED` | Native Stripe payment-detail verification UI/package | Stripe CLI upload, bind six missing Dashboard-issued values, external test, then Submit for review |
| OpenAI Skills | submission package ready | Bounded skill calling `/verify/evaluate` | Complete publisher verification and external submission |
| Microsoft Marketplace | submission metadata ready | Start with `Contact me` SaaS listing for enterprise leads | Partner Center publisher enrollment/offer submission |
| AWS Marketplace | blocked externally | SaaS offer specification only | Seller onboarding plus AWS Marketplace billing/entitlement integration before paid public listing |
| JetBrains Marketplace | plugin specification ready | Developer-channel concept uses the same `/verify/evaluate` API | Build/sign plugin ZIP, declare trader status, upload for manual review |
| Direct API | LIVE | Public bounded verification endpoint, free activation, and proof-bound metering | Attach durable storage and verified Stripe commerce before enabling paid enforcement |

## Commercial model by channel

### GitHub

Use the GitHub Action as the low-friction acquisition surface. The current GitHub Marketplace Action is free. Paid GitHub Marketplace billing applies to GitHub Apps rather than Actions, so a paid GitHub-native plan should be a separate GitHub App owned by a verified organization. The Action can still drive users to the paid verification service.

### Stripe

Use the existing public Stripe App identity `pics.dsg.governance`. The app calls Cinema server-side verification and displays decision → reason → verification → proof. Keep customer-facing claims limited to evidence actually returned by the exact Z3 proof path.

### Microsoft Marketplace

Start with a `Contact me` SaaS offer because it has the lowest technical onboarding burden and can create enterprise leads before Microsoft transactable SaaS fulfillment is implemented. Upgrade later to `Sell through Microsoft` after Entra/MSA onboarding and Marketplace fulfillment integration are complete.

### AWS Marketplace

Prepare as SaaS but do not claim a paid AWS Marketplace launch until AWS Marketplace billing dimensions, entitlement/subscription events, customer registration, and seller onboarding are complete. AWS requires SaaS products sold there to be billed through AWS Marketplace dimensions.

### JetBrains

Use a thin IDE plugin that sends bounded Verified Execution facts to Cinema and renders the Proof Receipt. Do not put Z3 backend credentials in the plugin. A new plugin/version is subject to JetBrains review.

## Listing copy

**Name:** DSG Verified Execution

**Short description:** Deterministic Z3 proof receipts for AI and automated actions.

**Long description:**

DSG Verified Execution verifies whether an automated action stayed inside an approved plan and deterministic constraints, then returns an exact Z3-backed proof receipt. Receipts include authorization completion, out-of-plan rejection, replay match, evidence completeness, hashes for replay/audit correlation, and optional cost/run data. The runtime is agent-neutral and can be called from CI, payment operations, cloud workflows, or IDE integrations.

## Submission gate

A marketplace package is considered submission-ready only when all of these are true:

1. Python compile and regression tests pass.
2. The marketplace adapter accepts no arbitrary QUBO/solver input.
3. Exact proof response requires `verified=true` and `VERIFIED_GLOBAL_OPTIMUM`.
4. No Z3/Cinema secret is embedded in client packages.
5. The listing has no certification claim without evidence.
6. Production URL is resolved from the live deployment, not guessed or hard-coded from stale infrastructure.

## Verified production surfaces

- Landing: `https://dsgoneverifiedweb.z1.web.core.windows.net/`
- Cinema API: `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io`
- API documentation: `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/docs`

Direct Stripe billing is linked and enforced according to the live
`/billing/status` response. That does not make the separate Stripe App
Marketplace channel live; `/marketplace/stripe/status` remains
`ACTION_REQUIRED` until its upload-generated signing secret, mode-specific
OAuth credentials, and exact authorize URLs are bound.
