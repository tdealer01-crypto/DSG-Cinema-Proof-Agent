# OpenAI plugin submission checklist

This checklist follows the structure of the referenced `aws-cdk-project-init/submission` example. The publisher portal remains authoritative for current eligibility, fields, and policy attestations.

## Technical package

- [x] Skills-only plugin manifest is present.
- [x] `SKILL.md`, verification script, UI metadata, submission docs, and logo are bundled.
- [x] Verification uses the current Cinema `/verify/evaluate` path.
- [x] Retired Control Plane runtime is excluded from the plugin path.
- [x] Arbitrary solver/QUBO input is not exposed to plugin users.
- [x] Exact Z3 `VERIFIED_GLOBAL_OPTIMUM` is required for a verified receipt.
- [x] Live verification fails closed when the endpoint is missing or invalid.
- [x] Long-lived solver credentials are not requested or included.
- [x] Three starter prompts are provided.
- [x] Five positive and three negative reviewer cases are provided.
- [x] Repeatable validation and ZIP packaging scripts are provided.
- [ ] Production Cinema `/verify/evaluate` endpoint is deployed from the reviewed commit and current E2E evidence passes.
- [ ] Public privacy/terms text is finalized to match production retention, billing, jurisdiction, and support commitments.
- [ ] Public repository URLs and support/security-reporting paths are checked without authentication.

## Publisher action required

- [ ] Confirm the publisher organization/account that will own `dsg-verified-execution`.
- [ ] Complete publisher identity/organization verification required by the current OpenAI submission portal.
- [ ] Confirm the account has the write permission required to create/update plugin submissions.
- [ ] Open the current OpenAI plugin/app publishing portal and choose the Skills-only submission type if still offered.
- [ ] Confirm `DSG Verified Execution` and `dsg-verified-execution` are accepted as the public name/identifier.
- [ ] Run `./scripts/package.sh` and upload `dist/dsg-verified-execution-plugin-1.0.0.zip`.
- [ ] Enter `submission/LISTING.md` and upload `assets/logo.png`.
- [ ] Enter the starter prompts and reviewer test cases.
- [ ] Enter the release notes and complete all current policy attestations.
- [ ] Submit for review.
- [ ] After approval, publish the approved version from the portal.

Do not mark the plugin as submitted, approved, or live until the publisher portal provides that state.
