# DSG Cinema — AI Management System (AIMS)

**Scope:** DSG Cinema hosted governed-execution runtime, including plan approval, permission/capability checks, remote browser authority, execution evidence, native Z3 verification, and production release evidence.

**Status:** Internal management-system documentation. This is not an ISO/IEC 42001 certificate.

## 1. Policy

Cinema follows these operating principles:

- Actions execute only when supported by the approved plan and required authority.
- Missing capability yields `WAITING_PERMISSION`; it is not silently treated as approval.
- Out-of-plan actions are blocked.
- Unsupported claims must not be presented as verified.
- Security, audit, and proof evidence must be linked to the exact runtime/version where possible.
- External certification, CE marking, marketplace approval, or independent audit must never be inferred from internal proof.

## 2. Roles and responsibility

- **Product owner:** approves policy/risk acceptance and external claims.
- **Runtime maintainer:** owns implementation, test, deployment, and rollback evidence.
- **Compliance owner:** maintains classification, risk register, incident/post-market records, and evidence pack.
- **Customer operator:** approves plans and privileged actions within their deployment context.

A single person may hold more than one role, but the responsibility must still be recorded.

## 3. Risk management

The lifecycle risk register is `risk-register.md`.

Risk review is required on:

- authorization or decision-core changes;
- evidence/proof schema changes;
- remote browser/agent pairing changes;
- identity/auth changes;
- production deployment architecture changes;
- new regulated customer use cases;
- incidents or significant verification failures.

## 4. Operational control

Canonical execution flow:

1. Create or receive plan.
2. Approve exact plan hash.
3. Run preflight.
4. Return `ALLOW`, `WAITING_PERMISSION`, or `BLOCK`.
5. If remote execution is required, bind short-lived session authority to the approved plan/step.
6. Execute only the authorized action.
7. Record evidence.
8. Run deterministic verification / native Z3 proof where required.
9. Emit receipt or fail-closed verification outcome.

## 5. Change and release control

Every material production release should have:

- source commit SHA;
- CI/test result;
- production deployment workflow result;
- deployment evidence artifact where available;
- updated risk review if a controlled boundary changed;
- updated compliance evidence references if behavior changed.

A successful deploy is release evidence, not certification evidence.

## 6. Performance evaluation

Review at least monthly:

- `ALLOW`, `WAITING_PERMISSION`, `BLOCK` rates;
- execution failures;
- proof/verification failures;
- remote-session/auth failures;
- unexpected out-of-plan attempts;
- incident count/severity;
- production health/readiness;
- evidence-chain/proof integrity checks.

## 7. Internal review and improvement

Nonconformities and gaps must be tracked to closure with:

- problem statement;
- root cause;
- containment;
- corrective action;
- verification evidence;
- closure date.

This repository's compliance documents must be reviewed when runtime truth changes. Historical claims that no longer match current production must be corrected rather than preserved for marketing continuity.

## 8. External certification boundary

ISO/IEC 42001 certification requires an applicable external certification process. This AIMS is intended to reduce audit preparation work and provide traceable implementation evidence; it does not substitute for certification.