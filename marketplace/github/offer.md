# GitHub Marketplace

## Current live channel

- Listing: **DSG Secure Deploy Gate**
- Type: GitHub Action
- Current public version observed: `v1.1.0`
- Marketplace slug: `dsg-secure-deploy-gate`
- Source repository: `tdealer01-crypto/dsg-secure-deploy-gate-action`

## v2 upgrade package

Prepared at `marketplace/github-action-v2/`.

Product website for the v2 listing: https://dsgoneverifiedweb.z1.web.core.windows.net/

- Privacy Policy: https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/github/PRIVACY.md
- Third-party Processors: https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/github/PROCESSORS.md
- Support contact: t.dealer01@dsg.pics
- Rights holder and primary contact: Thanawat Suparongsuwan
- Publisher account: tdealer01-crypto (https://github.com/tdealer01-crypto)

v2 adds a Verified Execution mode backed by Cinema `/verify/evaluate` and exact Z3 verification while keeping marketplace-side logic bounded. The Action writes `dsg-proof-receipt.json` and exposes `decision`, `proof_hash`, and `context_hash` outputs.

### Publisher ownership

The current GitHub App and Marketplace draft are owned by the personal GitHub account **tdealer01-crypto**. The listing will remain under that account; no publisher transfer to an Organization is planned for this version. The rights holder and primary contact is Thanawat Suparongsuwan.

### v2 positioning

**Title:** DSG Verified Execution Gate

**Description:** Verify authorized execution, replay, evidence, and deterministic constraints with exact Z3 proof receipts.

**Categories/tags:** deployment, security

## Monetization

GitHub Actions are the free acquisition surface. If GitHub-native paid billing is required, implement a separate GitHub App. Paid GitHub Marketplace Apps require organization ownership and verified publisher eligibility; do not claim the Action itself processes paid Marketplace plans.

## External publication step

The current chat integration cannot create a release in the dedicated Action repository. After the v2 files are copied there and validated, publish a new GitHub release and select **Publish this Action to GitHub Marketplace**. Existing v1 tags should remain unchanged for backward compatibility.
