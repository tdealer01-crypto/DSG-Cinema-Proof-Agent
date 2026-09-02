# DSG Cinema — Incident Response and Regulatory Escalation

## Severity

- **SEV-1:** unauthorized/out-of-plan execution, approval bypass, evidence/proof integrity failure, security compromise affecting execution authority, or widespread production outage of safety/governance controls.
- **SEV-2:** partial governance degradation, repeated verifier mismatch, remote-session control failure without confirmed unauthorized execution, or significant customer impact with workaround.
- **SEV-3:** non-critical defect or documentation/monitoring gap with no material control failure.

## Detect

Check and preserve:

- `/health`
- `/api/v1/status`
- relevant MCP/REST error
- plan and exact plan hash
- preflight result
- agent/session identity and capability state
- execution/evidence record
- native Z3 proof result
- production deployment SHA/run/artifact

Do not mutate or delete evidence needed for investigation.

## Triage

Record:

- first-known timestamp;
- discovery timestamp;
- affected product/version;
- customer/deployment scope;
- affected actions/agents;
- safety/security/fundamental-rights impact if any;
- whether execution must be paused or rolled back;
- regulatory jurisdictions/use cases potentially involved.

## Containment

Depending on incident type:

- disable or revoke affected remote/session authority;
- block affected route/action/capability;
- fail closed on proof/verification uncertainty;
- roll back the affected production deployment;
- suspend the affected integration while preserving unaffected service where safe.

## Root cause and corrective action

Every SEV-1/SEV-2 requires:

1. root-cause statement;
2. affected boundary/control;
3. corrective change;
4. regression test/evidence;
5. production verification;
6. risk-register update;
7. post-market monitoring update if needed;
8. customer/regulatory communication decision.

## Regulatory escalation

This repository does not assume every Cinema incident is an EU AI Act serious incident. For a deployment where a regulatory reporting obligation applies:

1. determine the applicable role and legal regime;
2. record when DSG/the responsible provider became aware;
3. assess whether the event meets the applicable serious-incident definition;
4. start the applicable reporting clock;
5. preserve the technical facts, chronology, affected versions, mitigation, and causal assessment;
6. submit through the competent authority/process within the legally applicable deadline.

Legal deadlines must be checked against the law and current regulatory guidance at the time of the incident; do not rely on a hard-coded deadline in application logic.

## Closure

An incident is closed only when:

- containment is complete;
- corrective action is implemented;
- regression tests pass;
- production evidence is verified;
- affected risk entries are reviewed;
- required notifications are complete or documented as not applicable;
- post-incident review is recorded.

## Post-incident record template

- Incident ID
- Severity
- Product/version/commit
- Detection time
- Awareness time
- Customer/use-case scope
- Technical impact
- Root cause
- Containment
- Corrective action
- Verification evidence
- Regulatory assessment
- Notifications
- Owner
- Closure date
