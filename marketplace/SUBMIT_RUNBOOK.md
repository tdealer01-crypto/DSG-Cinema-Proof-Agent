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

**Status:** four of five blockers fixed. **One blocker is still open and will
cause a second rejection if submitted as-is** — see below.

| Blocker | Fix |
|---|---|
| Technical description | Rewritten for customers |
| `payment.detail` view | Removed; `views` is now empty |
| Missing marketing images | Three 1600×900 PNGs, now on a reachable host |
| Manifest validity | `stripe-app.template.json` parses clean |
| Missing OAuth | ⚠️ **STILL BROKEN** — redirect URL points nowhere |

### ⚠️ Open blocker — OAuth redirect URL

The manifest declares:

```json
"oauth": { "redirect_urls": ["https://dsg.pics/auth/stripe/callback"] }
```

Two independent problems, both verified on 2026-08-23:

1. **`dsg.pics` does not serve HTTPS.** It resolves to Google Cloud addresses
   but every request returns connection failure (`HTTP 000`). The Azure landing
   page returns `200` from the same network, so this is the host, not the
   probe.
2. **No such route exists anywhere.** Production `/openapi.json` lists 51
   routes. There is no `/auth/stripe/callback` and no Stripe OAuth callback
   under any prefix — only `/stripe/evaluate`, `/billing/webhook/stripe`, and
   `/marketplace/github/callback` (GitHub only).

Stripe tests the redirect URL during review. Resolve one of these before
submitting:

- **Build the endpoint.** Add a Stripe OAuth callback to Cinema (mirroring
  `/marketplace/github/callback`) and point `redirect_urls` at
  `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/marketplace/stripe/callback`.
  This is the durable fix.
- **Stand up `dsg.pics`.** Serve HTTPS on the domain and implement the callback
  there, keeping the URL as written.
- **Drop the `oauth` block.** Only if the app genuinely does not need OAuth —
  it now declares no UI views, so confirm against Stripe's rejection notice
  whether OAuth was actually required or was inferred.

I could not pick for you: the first two need infrastructure only you can
deploy, and the third needs the original rejection text.

### Marketing images — fixed

They previously pointed at `https://dsg.pics/images/stripe-marketplace/*.png`,
which fails for the same reason as above. Now repointed to
`raw.githubusercontent.com`, verified `HTTP 200` with `content-type: image/png`
and correct byte counts on all three. The files are valid 1600×900 8-bit RGB
PNGs in `public/stripe-marketplace/`.

> These URLs only resolve once this branch is merged to `main`. Merge before
> uploading to Stripe.

### Submit (after the OAuth blocker is closed)

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

Stripe still first — it is the only channel where approval directly unlocks
revenue that is already wired end to end — but close the OAuth redirect blocker
before uploading. Submitting tomorrow without it spends another review cycle to
be told the same thing.

GitHub v2 second: the patch is written and only needs the app install. OpenAI
third — it is genuinely ready. Microsoft's enrollment can run in the background
alongside all of them. AWS and JetBrains are later quarters.

Fastest path to revenue if the OAuth endpoint takes time: OpenAI Skills and
GitHub v2 both ship without it, and the Direct API is already live and billing
today.

## Truth boundary

Nothing here is approved by any marketplace. "Ready" means the artifact
validates and the production endpoint it points at is healthy — it does not
mean a vendor has reviewed it. Do not claim SOC 2, ISO, or any third-party
certification on any listing.
