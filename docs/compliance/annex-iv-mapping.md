# DSG Cinema — Annex IV Technical Documentation Mapping

**Status:** Internal readiness mapping. Not a declaration of conformity or certification.

This file maps current Cinema-native evidence to common Annex IV technical-documentation categories. A category is `COVERED` only where current repository/runtime evidence supports it; otherwise it remains `PARTIAL` or `NOT VERIFIED`.

| Item | Technical documentation area | Status | Cinema-native evidence |
|---|---|---|---|
| 1 | General description and intended purpose | COVERED | `README.md`, `docs/API_V1_CONTRACT.md`, `docs/compliance/classification.md` |
| 2 | Versions, release/update history | COVERED | Git commit history, canonical production workflow, commit-linked deployment runs/artifacts |
| 3 | System architecture and technical specifications | COVERED | `api_v1/`, MCP/REST contracts, remote browser module, native Z3 verifier boundary |
| 4 | Monitoring/functioning/control mechanisms | COVERED | `/health`, `/api/v1/status`, preflight decisions, execution/evidence/proof records |
| 5 | Input/output and data specifications | PARTIAL | API/MCP models and request schemas exist; deployment-specific data inventory/classification still required |
| 6 | Human oversight measures | COVERED | exact plan approval, `WAITING_PERMISSION`, plan-bound remote session authority, operator takeover path |
| 7 | Accuracy/robustness/cybersecurity evidence | PARTIAL | deterministic gates, fail-closed behavior, auth/session separation, Z3 proof, CI/tests; formal target metrics and lifecycle cybersecurity evaluation still require versioned report |
| 8 | Post-market monitoring | PARTIAL | `post-market-monitoring.md` defines procedure; recurring production reports/metrics baseline must be generated and retained |
| 9 | Incident reporting/corrective action | PARTIAL | `incident-response.md` defines process; periodic drill and incident/CAPA records are required to prove operation |

## Evidence rules

- A Z3 proof is evidence of a defined formal property; it is not an Article 43 conformity assessment.
- A successful GitHub Actions run proves that workflow's result for that source/deployment; it does not establish regulatory conformity by itself.
- An internal mapping is not an external audit.
- High-risk obligations apply only after the relevant product/use-case classification establishes that they apply.

## Current priority gaps

1. Produce a deployment-specific data inventory and input/output specification.
2. Define and record accuracy/robustness/cybersecurity target metrics per release.
3. Generate the first versioned monthly post-market monitoring report.
4. Run and record an incident-response drill / CAPA exercise.
5. Link each technical-documentation item to exact commit/run/proof IDs in an exportable evidence manifest.

## Completion condition

Do not mark this mapping `100%` until all `PARTIAL` items have current, versioned operating evidence rather than procedure text alone.