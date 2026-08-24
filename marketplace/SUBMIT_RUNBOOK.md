# Marketplace Submission Runbook

Marketplace status must be verified per artifact. PR #108 merged the Stripe App
v2.7.1 remediation, PR #109 upgraded `stripe` to 22.5.0, and PR #110 fixed the
confirmed Cinema deployment-order failure. Production deploy run #56 and Stripe
package run #127 both passed from merge commit
`ee2431b6076ad2200673213f6d6f73d055afadc0`.

Production runtime probes were refreshed at `2026-08-24T08:07:00Z`. They prove
the repaired Cinema/OAuth contract and production-bound package are live; they
do not prove that the package was uploaded, externally tested, reviewed,
approved, or published by Stripe.

| Probe | Result |
|---|---|
| `GET /health` | `200` — `{"status":"ready","backend":"ready"}` |
| `GET /openapi.json` | `200` — exposes Stripe status, setup, mode-specific callback, and evaluate routes |
| `GET /marketplace/stripe/status` | `200` — `ACTION_REQUIRED`; app ID, OAuth client ID, three callback URIs, live developer key, and billing secret pass. Three authorize URLs, test/sandbox developer keys, and app signing secret are missing. |
| `GET /marketplace/github/status` | `200` — `READY`; durable_store, webhook_secret, oauth_client_id, oauth_client_secret all `PASS` |
| `GET /billing/status` | `200` — `stripe.link_state: LINKED_VERIFIED`, `charges_enabled: true`, metering enforced, 0 blockers |
| Ledger | 359 entries with a non-empty public `head_hash` at the time of the probe |
| Stripe package | Run #127 artifact `9508761420`, digest `sha256:f3b1ffc3bc46b461a2248918f82d83ede6e60ab611d385f33a5f05f1d0373bc9` |

Live catalog: `verified_execution` $0.05/proof, `stripe_policy_decision`
$0.10/proof. Plans: free (25 proofs), metered, team ($490/mo + 5,000 included
+ $0.08 overage), enterprise.

---

## 1 — GitHub Marketplace Action v2

**Status:** pushed and open for review as
[dsg-secure-deploy-gate-action#10](https://github.com/tdealer01-crypto/dsg-secure-deploy-gate-action/pull/10).

The branch carries four files: `action.yml` (v2 contract),
`scripts/verified-execution.sh` (new), `MIGRATION.md` (new), `README.md`
(v2-first, retiring the dead Vercel URL). The v1 scripts stay in place, and the
repo's Bats suite passes against them unchanged.

### To publish

1. Merge PR #10 to `main`.
2. Draft a release tagged `v2.0.0`, titled
   **v2.0.0 — Verified Execution Gate**.
3. Tick **Publish this Action to GitHub Marketplace**. Categories:
   `Deployment`, `Security`.
4. Publish.

> The repo's second CI job, `Python – verify-proof.py unit tests`, fails with
> `No module named pytest`. That is red on `main` at the base commit too — the
> workflow never installs pytest — so it is not PR #10's failure. A two-line
> fix (`python3 -m pip install --quiet pytest` before the test step) closes it,
> as a separate change.

**Listing name:** DSG Verified Execution Gate
**Description:** Verify authorized execution, replay, evidence, and
deterministic constraints with exact Z3 proof receipts.

> Renaming retitles the existing public listing. v1 tags (`v1.0.0`–`v1.1.0`)
> are immutable and keep working; only `@main` consumers move to v2.
> `MIGRATION.md` documents the path.

---

## 2 — Stripe Apps Marketplace

**Status:** v2.7.0 must not be submitted. The v2.7.1 remediation, SDK upgrade,
and production rollout repair are merged and deployed. CI has produced the
production-bound archive. Stripe CLI upload and all Stripe-side configuration,
External Test, evidence, and review actions remain.

| Blocker found in PR #106 / v2.7.0 | v2.7.1 remediation |
|---|---|
| Manifest has 11 schema errors | Remove listing-only fields; use `permission`/`purpose`, `stripe_api_access_type`, and `allowed_redirect_uris` |
| Empty UI view list despite listing UI claims | Wire `stripe.dashboard.payment.detail` to `ChargeGate` |
| UI expects full objects in `objectContext` | Read the object ID/type from context and retrieve the charge/PaymentIntent through Stripe's authenticated extension client |
| UI calls Cinema without authentication | Use `fetchStripeSignature`; verify the raw request body and installed account server-side |
| Production metering requires a DSG key the iframe cannot hold | Resolve the signed Stripe account to its linked DSG account and apply the same entitlement gate by account ID |
| Three 1600×900 files contain placeholder bars/text | Capture real Dashboard screenshots only after the sandbox external test passes |

### OAuth redirect — built

The redirect URL used to be `https://dsg.pics/auth/stripe/callback`, which was
broken two independent ways: the host remained unusable from the verification
network (`HTTP 000` on 2026-08-23 and `502` on 2026-08-24 while the Azure
landing returned `200`), and the Stripe callback was absent from the production
OpenAPI document at the time. Production now exposes the Azure callback; do not
restore the retired `dsg.pics` redirect unless it independently serves HTTPS.

The merged `revenue/stripe_marketplace.py` defines the replacement flow,
mirroring the GitHub Marketplace bridge. `/openapi.json` now shows these routes
after successful production run #56:

| Route | Purpose |
|---|---|
| `GET /marketplace/stripe/status` | Config readiness, same shape as the GitHub one |
| `GET /marketplace/stripe/setup` | Explains onboarding; its continue action redirects to Stripe with signed state |
| `GET /marketplace/stripe/callback/{live,test,sandbox}` | Mode-specific redirect URLs Stripe tests |

The callback exchanges the code at `POST /v1/oauth/token`, then reads the
account back through `GET /v1/account` with the issued token before linking —
the `stripe_user_id` returned beside the token is never trusted on its own. A
denied install renders a plain page rather than erroring. Installing grants the
free plan (25 proofs); paid plans still go through the existing checkout, so an
install can never grant paid units on its own.

The v2.7.1 manifest uses the `__CINEMA_API_BASE__` placeholder, so the URL is
substituted at build time and cannot drift from the deployed backend.
`generate-manifest.mjs` fails the build if any redirect URL points outside the
backend — the exact bug that would have caused a second rejection.

The signed path adds tests for valid linked installs, forged signatures,
account mismatch, unlinked accounts, missing signing-secret configuration, and
the Stripe iframe CORS preflight. Record the final count only from CI after the
branch is pushed.

### Required production configuration

Production already passes the app ID, OAuth client ID, all three callback URIs,
the live developer key, and the billing secret-key checks. The remaining setup
starts with the first app upload:

1. Upload v2.7.1 once. Stripe creates the app signing secret only after upload.
2. Store the `absec_...` value as `STRIPE_APP_SIGNING_SECRET` (or set
   `DSG_KEY_VAULT_STRIPE_APP_SIGNING_NAME` to the Key Vault secret name).
3. Configure **External test**, then copy the managed-sandbox developer API key
   used by the sandbox OAuth link
   and store it as `STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY` (or set
   `DSG_KEY_VAULT_STRIPE_APP_OAUTH_SANDBOX_NAME`). Store the separate test-mode
   developer key as `STRIPE_APP_OAUTH_TEST_SECRET_KEY`; sandbox compatibility
   requires both test-mode and general-sandbox flows to work.
4. Copy the exact sandbox authorize link from Stripe's **External test** tab
   into repository secret `STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL` (or use
   `DSG_KEY_VAULT_STRIPE_APP_OAUTH_SANDBOX_URL_NAME`). Treat this invite-style
   URL as a bearer capability rather than a public identifier. Store the
   test-mode link in secret `STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL`; store the
   exact Public Install URL from **Settings** in
   `DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL` before review. The service has no
   generic live-link fallback: this check must remain missing until the real
   Settings URL is supplied.
5. Re-run the Cinema production deploy so the Container App picks up all
   identifiers and secrets.
6. Confirm `GET /marketplace/stripe/status` returns `"status": "READY"` with
   `app_signing_secret`, `oauth_live_secret_key`,
   `oauth_test_secret_key`, `oauth_sandbox_secret_key`, both non-live authorize
   URLs, all three mode-specific redirect URIs, and every other
   required check `PASS`.
7. Open `/marketplace/stripe/setup?link_type=sandbox`, read the onboarding
   instructions, and use **Continue to Stripe** for External Test. Verify the
   authorize path is exactly `/oauth/v2/authorize` and its `redirect_uri` ends
   in `/marketplace/stripe/callback/sandbox`; the obsolete
   `/oauth/v2/{app_id}/authorize` shape and a shared cross-mode callback must
   not be used.

### Marketing images — still blocked

The three PNG files have the required pixel dimensions but are placeholder
graphics, not screenshots showing the app inside the Stripe Dashboard. Do not
upload them to the listing. After External Test and production deployment,
capture one matching image for each listed feature from the final candidate,
at least 1600 pixels wide, using synthetic data and no debug/testing state.
Also record the complete onboarding and three-feature flow for review guidance.

### Submit

```bash
cd stripe-app
stripe login
CI=true npm ci --no-audit --no-fund
CINEMA_API_BASE=https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io npm run manifest:generate
npm run manifest:validate
npm run build
npm test
stripe apps upload
```

Upload happens before `fetchStripeSignature` testing. Bind the generated signing
secret, redeploy, install in a sandbox, run the **External Test**, and replace
the screenshot placeholders. Only then open **DSG Governance Gate** and use
**Submit for review**.

Production billing already reports a verified Stripe catalog and metering. That
does not remove the remaining app gates: v2.7.1 upload, app signing secret,
external test, real screenshots, listing verification, and Stripe review.

---

## 3 — OpenAI Skills

**Status:** `scripts/validate.sh` passes. Ready to submit.

```bash
cd marketplace/openai-plugin
bash scripts/package.sh
```

Pre-filled listing fields:

| Field | Value |
|---|---|
| Plugin name | DSG Verified Execution |
| Identifier | `dsg-verified-execution` |
| Submission type | Skills only |
| Category | Developer Tools |
| Short description | Verify actions against approved plans with Z3 proof. |
| Website | https://dsgoneverifiedweb.z1.web.core.windows.net/ |
| Support | https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues |
| Privacy | `marketplace/openai-plugin/PRIVACY.md` (raw GitHub URL) |
| Terms | `marketplace/openai-plugin/TERMS.md` (raw GitHub URL) |

Long description is in `submission/LISTING.md`. Publisher identity must be
verified in the submission organization before review opens.

**Prerequisite:** enable private vulnerability reporting on the repo, and
confirm every listed URL opens without signing in.

---

## 4 — Microsoft Marketplace (Partner Center)

**Status:** submission pack prepared. Blocked on Partner Center enrollment.

Take the **Contact me** SaaS listing first — it opens the enterprise lead
channel without the transactable fulfillment integration.

1. Enrol the publisher in the Microsoft Marketplace program (this is the long
   pole; verification can take days).
2. New offer → **Software as a Service** → **Contact me**.
3. Paste the offer summary and keywords from `marketplace/azure/offer.md`.
4. Product website: https://dsgoneverifiedweb.z1.web.core.windows.net/
   Demo/trial URL: `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/app`
5. Configure lead routing, then submit for certification.

Do not describe the product as Microsoft-certified until Partner Center says
so.

---

## 5 — AWS Marketplace

**Status:** blocked on seller onboarding — the deepest blocker in this list.

A paid SaaS listing requires AWS Marketplace entitlement and metering
integration, which means a second billing path alongside the existing Stripe
ledger. Do not start this until Stripe revenue is running; the integration work
is larger than the other five channels combined.

Order: seller registration → tax and banking → entitlement/metering integration
→ listing. See `marketplace/aws/offer.md`.

---

## 6 — JetBrains Marketplace

**Status:** spec only — no plugin artifact has been built.

Requires a signed IDE plugin ZIP that does not exist yet, plus an account and a
trader declaration under EU DSA rules. Lowest priority: it needs real build
work before any submission step applies. See `marketplace/jetbrains/offer.md`.

---

## Recommended order

Stripe first, but do not submit v2.7.0. PR #109 and the deployment-order fix in
PR #110 are already merged, production run #56 passed, and package run #127
created the candidate archive. Recheck the npm registry immediately before
upload, upload v2.7.1 once, bind the signing secret and exact Dashboard-issued
links, confirm
`/marketplace/stripe/status` reads `READY`, run External Test, and capture real
screenshots and a recording before submission.

GitHub v2 second: the patch is written and only needs the app install. OpenAI
third — it is genuinely ready. Microsoft's enrollment can run in the background
alongside all of them. AWS and JetBrains are later quarters.

The Direct API is already live and billing today, so none of these is a
prerequisite for revenue — they are each an additional channel into it.

## Truth boundary

Nothing here is approved by any marketplace. "Ready" means the artifact
validates and the production endpoint it points at is healthy — it does not
mean a vendor has reviewed it. Do not claim SOC 2, ISO, or any third-party
certification on any listing.
