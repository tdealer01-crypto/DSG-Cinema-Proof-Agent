# Working on this repository

DSG Verified Execution: a FastAPI service (Cinema) that returns ALLOW / REVIEW /
BLOCK decisions only when an exact Z3 verifier proves `VERIFIED_GLOBAL_OPTIMUM`,
plus the marketplace packages that distribute it.

This file exists because several agents work on this repository and each one has
so far rediscovered the same constraints by breaking CI. Read it before changing
anything.

## Before you claim something works

- **Run the suite from the repo root.** `python3 -m pytest -q` — 355 tests,
  seconds to run. Green is the bar for a push.
- **Fetch `/openapi.json` before asserting a route exists.** Several documents
  in this repository describe endpoints that were never built. The live spec is
  the only authority:
  `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/openapi.json`
- **Probe, don't infer.** Claims about production belong to `curl`, not to
  reading the deployment workflow and assuming it ran.

## Hard rules — CI enforces every one of these

| Rule | Enforced by |
|---|---|
| `landing/index.html` and `azure-landing/index.html` must be byte-identical | `test_azure_and_render_landings_share_one_user_flow` compares `read_bytes()` |
| Nothing under `marketplace/` may contain a retired Control Plane URL | a `grep -R` in `marketplace-launch-verify.yml` |
| `launch-manifest.json` must not claim a payment link the product lacks | a `jq` assertion on `revenue_automation.not_claimed` |
| `product.checkout_status` is pinned | both `test_marketplace_surfaces.py` and a `jq` assertion |
| A Stripe OAuth redirect URL must sit under the backend being built for | `stripe-app/scripts/generate-manifest.mjs` throws |

The marketplace grep is blunt on purpose: a **diff or patch file that merely
removes** a retired URL still contains the string, and still fails. Do not commit
patch files under `marketplace/`.

The truth-boundary guards exist to stop the manifest over-claiming. Loosening
them is a deliberate decision for the repository owner on presented evidence —
never a side effect of another change. If your change needs a guard relaxed,
raise it; do not relax it and move on.

## Facts that are easy to get wrong

- **`checkout_status` has exactly two values**, defined in `revenue/api.py`:
  `LINKED` and `NOT_VERIFIED_NOT_LINKED`. `LINKED_VERIFIED` is
  `stripe.link_state` — a different field in the same `/billing/status`
  response. Conflating them fails CI.
- **`dsg.pics` resolves but serves no HTTPS.** Every request returns `HTTP 000`
  (connection failure, not a status code) while the Azure landing returns `200`
  from the same network. Never point a redirect URL, image, or callback there.
- **`stripe-app/stripe-app.json` is generated and gitignored.** Run
  `node scripts/generate-manifest.mjs` with `CINEMA_API_BASE` set before any
  upload. `src/runtime.ts` is committed holding the `__CINEMA_API_BASE__`
  placeholder — do not commit the substituted version.
- **GitHub reserves the `GITHUB_` prefix for secrets.** User-managed values use
  `DSG_` and are mapped to their runtime names inside Azure.

## Deployment

Everything live is Azure. Vercel, Render and Railway appear only in retired
documents.

| Component | Target |
|---|---|
| Cinema API | Container App `dsg-cinema-production` |
| Z3 verifier | Container App `dsg-z3-verifier-production` |
| Images | ACR `tdealer01acr` |
| Resource group | `rg-t.dealer01-0468` (westus3) |
| Landing | Azure Storage static site `dsgoneverifiedweb.z1.web.core.windows.net` |

CI reaches Azure over OIDC; no Azure password is stored. Deploys run on push to
`main`, so a change to `revenue/**` or a deploy workflow reaches production as
soon as it merges.

## Things no agent can do

Each of these blocks completely and has no API to call:

- **Publish an Action to GitHub Marketplace** — a checkbox on the release form.
- **`stripe apps upload`** — needs `stripe login`, which is interactive. A
  restricted key technically works in CI, but Stripe's own guidance is not to
  automate the upload, so do not build that step. The Stripe CLI also has **no
  `android-arm64` build**; Termux cannot run it.
- **Submit for review** in the Stripe Dashboard, Partner Center, or AWS
  Marketplace.
- **Push to a repository the Claude GitHub App is not installed on** — both git
  and the REST API return `403 Resource not accessible by integration`.

When you hit one of these, say so plainly and hand the exact steps back. Do not
work around it.

## Working alongside another agent

More than one agent targets this repository. The failure mode is branch
collision, not disagreement.

- **Work on your own branch. Never commit to `main` directly.**
- **`git fetch origin main` and check for drift before every push.**
- **If CI never starts on a PR, check `mergeable_state` first.** `dirty` means a
  merge conflict, and GitHub will not run any workflow until it is resolved —
  which presents as "CI is broken", not as "there is a conflict". Squash-merging
  one branch while another carries the same original commits causes exactly
  this.
- **Divide by directory rather than by message.** `stripe-app/` and `revenue/`
  are one coherent area; deployment workflows and the landing pages are another.
  Two agents editing `marketplace/launch-manifest.json` at once will collide
  every time.

## Reporting

State what you verified and how. "Tests pass" means you ran them; "deployed"
means you probed the endpoint afterwards. If part of a task is blocked, finish
everything else and say exactly what you left and why — scaling the work down is
the owner's call.
