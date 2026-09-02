# DSG Cinema — Lifecycle Risk Register

This register tracks product and compliance risks across design, deployment, operation, monitoring, and change management.

| ID | Risk | Likelihood | Impact | Existing treatment | Residual status | Evidence / control | Review trigger |
|---|---|---:|---:|---|---|---|---|
| CIN-R01 | Out-of-plan action executes | Low | Critical | Plan hash binding + preflight + fail-closed decision core | Controlled / verify continuously | approved plan, preflight decision, execution trace | decision-core change |
| CIN-R02 | Caller has credential but insufficient capability | Medium | High | `WAITING_PERMISSION`; capability and remote-session authority separated from API-key identity | Controlled | permission state, agent pairing/session evidence | auth/pairing change |
| CIN-R03 | Evidence claim accepted without evidence | Low | High | proof/evidence verification; unsupported claims must remain unverified | Controlled | evidence record + proof receipt | evidence schema change |
| CIN-R04 | Audit/evidence tampering | Low | High | cryptographic hashes, proof receipts, deployment artifacts | Controlled / test periodically | receipt/proof hashes; CI evidence artifacts | storage/proof change |
| CIN-R05 | Remote browser session exceeds approved authority | Low | Critical | short-lived plan-bound agent credentials; separate executor/verifier authority | Controlled | remote status, session TTL, plan/step binding | remote-browser change |
| CIN-R06 | Z3/verifier unavailable or inconsistent | Medium | High | separate verifier boundary; fail closed / no verified claim on missing proof | Controlled / monitor | verifier health, verification failure logs | verifier release/outage |
| CIN-R07 | Production artifact differs from reviewed source | Low | High | canonical deployment workflow + commit-linked production evidence | Controlled | GitHub Actions run, head SHA, evidence artifact | every release |
| CIN-R08 | Incorrect regulatory classification/claim | Medium | High | use-case classification record; prohibit universal Annex III/CE/certification claims | Open — governance review required | `classification.md`, product docs review | new sector/use case |
| CIN-R09 | Serious incident not escalated within applicable deadline | Medium | High | incident procedure, severity classification, regulatory clock recording | Open until drill proven | incident log + drill evidence | quarterly / incident |
| CIN-R10 | Post-market monitoring detects drift too late | Medium | High | health/status, execution outcomes, proof failures, auth/permission failures, production evidence review | Open until metrics baseline proven | monitoring report | monthly / release |
| CIN-R11 | Personal/sensitive data is captured beyond intended scope | Medium | High | data minimisation, secret masking, marketplace privacy controls | Partial — deployment-specific assessment | privacy docs, logs review | integration/customer change |
| CIN-R12 | Compliance documentation diverges from runtime | Medium | High | evidence-bounded docs; version/commit references; review on releases | Open until automated check exists | docs + release evidence | every release |

## Review rule

- Review before every production release that changes authorization, evidence, browser, verifier, identity, or data handling.
- Review after every SEV-1/SEV-2 incident.
- Review at least quarterly even when no code change occurs.
- New high-risk customer use cases require a use-case-specific classification and additional risks before production enablement.

## Acceptance rule

A risk can be marked `Accepted` only when an accountable owner records the rationale, residual risk, review date, and supporting evidence. Passing CI alone is not sufficient risk acceptance.