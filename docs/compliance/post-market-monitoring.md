# DSG Cinema — Post-Market Monitoring Procedure

**Purpose:** Define a systematic monitoring process for production Cinema deployments and provide evidence that can support EU AI Act Article 72 obligations where they apply.

This procedure does not itself establish that Cinema is a high-risk AI system. Applicability depends on the classification record and deployment use case.

## Monitoring scope

Collect and review production evidence from:

- `/health`
- `/api/v1/status`
- MCP availability and errors
- plan creation/approval failures
- `ALLOW`, `WAITING_PERMISSION`, and `BLOCK` outcomes
- out-of-plan attempts
- permission/capability denials
- remote browser pairing/session failures
- execution failures
- evidence submission failures
- native Z3 verification/proof failures
- deployment workflow failures
- security/authentication anomalies
- customer-reported incidents and complaints

## Review cadence

- **Per release:** verify deployment evidence and material control changes.
- **Monthly:** aggregate operating metrics and identify trend/drift.
- **Quarterly:** formal risk review, classification review, and control effectiveness review.
- **Event driven:** immediate review after SEV-1/SEV-2 incident, security event, material false allow/block, or proof-integrity failure.

## Minimum monitoring record

Each review should record:

- review period;
- product/version/commit;
- production deployment identifier/run;
- observed metrics and notable events;
- incidents/nonconformities;
- risk-register changes;
- corrective actions;
- owner;
- review date;
- decision: `NO_ACTION`, `CORRECTIVE_ACTION`, `RECLASSIFICATION_REVIEW`, or `STOP/ROLLBACK`.

## Trigger thresholds

Escalate for investigation when any of the following occurs:

- evidence/proof integrity failure;
- verified out-of-plan execution;
- unauthorized remote-session execution;
- unexpected bypass of approval/capability controls;
- repeated verifier mismatch;
- material increase in execution failures or permission anomalies;
- production source/deploy provenance mismatch;
- serious customer impact or fundamental-rights/safety concern in a regulated deployment.

## Corrective action loop

1. Detect signal.
2. Preserve evidence.
3. Triage severity and affected versions/customers.
4. Contain or rollback if required.
5. Identify root cause.
6. Implement corrective action.
7. Re-test and verify production evidence.
8. Update risk register, documentation, and instructions where necessary.
9. Evaluate whether a regulatory report is required.

## Evidence retention

Monitoring records must be retained with the applicable product/version evidence and must not be overwritten by later reviews. Retention duration must be set by the deployment's legal/commercial requirements and documented policy; do not infer a statutory retention period solely from this file.

## Output

The intended audit output is a versioned post-market monitoring report that links runtime metrics, incidents, corrective actions, and production artifacts to an exact Cinema release.