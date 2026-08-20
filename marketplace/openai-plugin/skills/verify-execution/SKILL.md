# DSG Verified Execution

Use this skill when a user wants to verify that an observed action or execution stayed within an approved plan or policy and wants a machine-readable proof receipt.

## Runtime contract

`Any Agent/App → Approved Plan/Policy → DSG Cinema /verify/evaluate → fixed ALLOW/REVIEW/BLOCK QUBO → exact Z3 proof → Proof Receipt`

The retired DSG Control Plane is not part of this runtime path.

## Required facts

Build a bounded request with these fields:

- `execution_id`: stable execution identifier.
- `trace_id`: correlation identifier when available.
- `channel`: `openai_plugin` for this skill.
- `agent_identity`: the executing agent/app identity.
- `approved_plan_hash`: SHA-256 of the approved plan or policy.
- `proposed_action_hash`: SHA-256 of the action being checked.
- `authorized`: whether the action had authorization.
- `plan_aligned`: whether the action matched the approved plan.
- `constraints_pass`: whether deterministic constraints passed.
- `execution_succeeded`: whether the real execution completed successfully.
- `replay_match`: whether deterministic replay matched.
- `evidence_complete`: whether required evidence is present.
- `cost_microunits`: optional non-negative execution cost.

Never invent missing evidence or mark a field true without support. If a required fact is unknown, use the fail-closed value described by the request schema or ask for the missing evidence.

## Getting a key (self-serve)

Verification works without a key wherever public evaluation is open. To meter
and attribute an agent's proofs, obtain a free-tier key once:

```
POST {DSG_VERIFY_URL}/billing/activate
{"channel": "openai_plugin", "activation_id": "<stable agent id>", "display_name": "<agent name>"}
```

Set the returned key as `DSG_API_KEY` before running `verify.sh`. The key is
returned exactly once, and activation is idempotent per `activation_id`, so a
retry reports `ACTIVATION_EXISTS` rather than issuing a second key.

## Verification procedure

1. Canonicalize the approved plan and proposed action before hashing. If the caller already supplies trustworthy SHA-256 hashes, preserve them.
2. Write the request JSON to a temporary file.
3. Run `scripts/verify.sh REQUEST_JSON` from this skill directory.
4. Accept a result as cryptographically verified only when all are true:
   - HTTP request succeeds;
   - `verified == true`;
   - `verification == "VERIFIED_GLOBAL_OPTIMUM"`;
   - `proof_hash`, `request_hash`, and `context_hash` are 64-character hashes;
   - `decision` is exactly `ALLOW`, `REVIEW`, or `BLOCK`.
5. Return the Proof Receipt fields and explain the decision in plain language.

## When a call is refused

A refusal returns a `remediation` object with `problem`, `cause`, `next_step`,
and `self_service`. `verify.sh` prints these to stderr. Relay the `next_step`
to the user verbatim rather than reporting only an HTTP status, and if
`self_service` is false say that an operator must act. `GET /support/diagnose`
(with the key, if any) returns the same structure as a full checklist.

Never treat a refusal as a verification result: a refused call produced no
proof and no charge.

## Fail-closed rules

- If `DSG_VERIFY_URL` is not configured, do not fabricate a proof. Report that live verification is unavailable.
- If the service is unavailable, returns non-JSON, or does not return `VERIFIED_GLOBAL_OPTIMUM`, treat the verification as failed.
- Do not call `/solve` directly. This skill uses only `/verify/evaluate`; callers cannot submit arbitrary QUBO programs.
- Do not request or expose the backend Z3 secret.
- Do not claim SOC 2, ISO, regulatory, or third-party certification from a Proof Receipt alone.

## Proof Receipt metrics

Surface these when present:

- `authorized_action_completion`
- `out_of_plan_rejection`
- `z3_constraint_correctness`
- `replay_match`
- `evidence_completeness`
- `cost_microunits`
- `proof_hash`
- `request_hash`
- `context_hash`

A receipt demonstrates the deterministic verification performed for that request. It is not a legal or compliance certification.
