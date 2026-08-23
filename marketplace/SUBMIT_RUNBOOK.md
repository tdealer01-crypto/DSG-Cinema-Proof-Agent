# Marketplace Submission Runbook

Every artifact in this repository is validated and submit-ready. What remains
on each channel is an authenticated action in a vendor dashboard that no API
exposes — there is no marketplace in this list that can be submitted to
programmatically. This runbook reduces each one to copy-paste plus clicks.

Verified against production on 2026-08-23:

| Probe | Result |
|---|---|
| `GET /health` | `200` — `{"status":"ready","backend":"ready"}` |
| `GET /marketplace/github/status` | `200` — `READY`; durable_store, webhook_secret, oauth_client_id, oauth_client_secret all `PASS` |
| `GET /billing/status` | `200` — Stripe `LINKED_VERIFIED`, `charges_enabled: true`, metering enforced, 0 blockers |
| Ledger | 335 entries, hash-chained |

Live catalog: `verified_execution` $0.05/proof, `stripe_policy_decision`
$0.10/proof. Plans: free (25 proofs), metered, team ($490/mo + 5,000 included
+ $0.08 overage), enterprise.

---

## 1 — GitHub Marketplace Action v2

**Status:** package complete and committed; blocked on GitHub App installation.

The v2 upgrade is built and validated. It could not be pushed to
`tdealer01-crypto/dsg-secure-deploy-gate-action` because the Claude GitHub App
is not installed on that repository — both `git push` and the REST API returned
403 `Resource not accessible by integration`.

### Unblock, then apply

1. Install the app on the Action repo:
   https://github.com/apps/claude/installations/select_target
2. Apply the prepared commit:

```bash
git clone https://github.com/tdealer01-crypto/dsg-secure-deploy-gate-action
cd dsg-secure-deploy-gate-action
git checkout -b verified-execution-gate-v2
git am < /path/to/marketplace/github-action-v2/dist/0001-verified-execution-gate-v2.patch
git push -u origin verified-execution-gate-v2
```

The patch touches four files: `action.yml` (v2 contract),
`scripts/verified-execution.sh` (new), `MIGRATION.md` (new), `README.md`
(v2-first, retires the dead Vercel URL).

### Then publish

3. Merge to `main`.
4. Draft a release tagged `v2.0.0`, titled
   **v2.0.0 — Verified Execution Gate**.
5. Tick **Publish this Action to GitHub Marketplace**. Categories:
   `Deployment`, `Security`.
6. Publish.

**Listing name:** DSG Verified Execution Gate
**Description:** Verify authorized execution, replay, evidence, and
deterministic constraints with exact Z3 proof receipts.

> Renaming retitles the existing public listing. v1 tags (`v1.0.0`–`v1.1.0`)
> are immutable and keep working; only `@main` consumers move to v2.
> `MIGRATION.md` documents the path.

---

## 2 — Stripe Apps Marketplace

**Status:** all five blockers fixed. One deployment step remains before upload.

| Blocker | Fix |
|---|---|
| Technical description | Rewritten for customers |
| `payment.detail` view | Removed; `views` is now empty |
| Missing marketing images | Three 1600×900 PNGs, repointed to a reachable host |
| Manifest validity | `stripe-app.template.json` parses clean |
| Missing OAuth | Callback built and served by Cinema |

### OAuth redirect — built

The redirect URL used to be `https://dsg.pics/auth/stripe/callback`, which was
broken two independent ways: `dsg.pics` resolves but serves no HTTPS (every
request returned `HTTP 000` while the Azure landing returned `200` from the
same network), and no Stripe callback existed among the 51 routes in production
`/openapi.json`.

`revenue/stripe_marketplace.py` now serves the flow, mirroring the GitHub
Marketplace bridge:

| Route | Purpose |
|---|---|
| `GET /marketplace/stripe/status` | Config readiness, same shape as the GitHub one |
| `GET /marketplace/stripe/setup` | Starts the install, redirects to Stripe with signed state |
| `GET /marketplace/stripe/callback` | The redirect URL Stripe tests |

The callback exchanges the code at `POST /v1/oauth/token`, then reads the
account back through `GET /v1/account` with the issued token before linking —
the `stripe_user_id` returned beside the token is never trusted on its own. A
denied install renders a plain page rather than erroring. Installing grants the
free plan (25 proofs); paid plans still go through the existing checkout, so an
install can never grant paid units on its own.

The manifest now uses the `__CINEMA_API_BASE__` placeholder, so the URL is
substituted at build time and cannot drift from the deployed backend.
`generate-manifest.mjs` fails the build if any redirect URL points outside the
backend — the exact bug that would have caused a second rejection.

Covered by 10 tests in `tests/test_stripe_marketplace.py`; the full suite is
355 passing.

### ⚠️ Deployment step before upload

The endpoint needs the app's OAuth client ID, which Stripe issues when the app
is registered. Until it is set, `/marketplace/stripe/status` reports
`ACTION_REQUIRED`.

1. In the Stripe Dashboard, open the app's OAuth settings and copy the **client
   ID** (`ca_...`).
2. Add it as repository variable `DSG_STRIPE_APP_OAUTH_CLIENT_ID`.
   (`DSG_STRIPE_APP_ID` defaults to `pics.dsg.governance`; set it only if the
   app id differs.)
3. Re-run the Cinema production deploy so the Container App picks both up.
4. Confirm `GET /marketplace/stripe/status` returns `"status": "READY"` with
   all four checks `PASS`.

### Marketing images — fixed

They previously pointed at `https://dsg.pics/images/stripe-marketplace/*.png`,
which failed for the same reason as the callback. Now repointed to
`raw.githubusercontent.com`, verified `HTTP 200` with `content-type: image/png`
and correct byte counts on all three. The files are valid 1600×900 8-bit RGB
PNGs in `public/stripe-marketplace/`.

> These URLs only resolve once this branch is merged to `main`. Merge before
> uploading to Stripe.

### Submit

```bash
cd stripe-app
stripe login
stripe apps upload
```

Then at https://dashboard.stripe.com/apps: open **DSG Governance Gate**, run an
**External Test** install, and **Submit for review**.

**Revenue on approval:** team plan $490/mo, metered $0.05/proof. Stripe billing
is already `LINKED_VERIFIED` with charges enabled, so approval is the only gate
left.

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

Stripe first — it is the only channel where approval directly unlocks revenue
that is already wired end to end. Set the OAuth client ID, redeploy, confirm
`/marketplace/stripe/status` reads `READY`, then upload.

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
