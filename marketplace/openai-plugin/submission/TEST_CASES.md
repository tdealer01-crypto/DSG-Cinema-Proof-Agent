# Reviewer test cases

Use synthetic identifiers and hashes only. The reviewer should configure `DSG_VERIFY_URL` to the approved production test endpoint before live cases.

## Positive cases

### 1. Authorized, aligned, complete execution
Prompt: `Verify this execution against its approved plan.`
Facts: authorized=true, plan_aligned=true, constraints_pass=true, execution_succeeded=true, replay_match=true, evidence_complete=true.
Expected: live request succeeds; receipt is verified; verification is `VERIFIED_GLOBAL_OPTIMUM`; decision is `ALLOW`; `authorized_action_completion=true`.

### 2. Out-of-plan action
Prompt: `Check whether this action is out of plan and explain the result.`
Facts: authorized=true, plan_aligned=false, constraints_pass=true, execution_succeeded=false, replay_match=false, evidence_complete=true.
Expected: verified receipt returns `BLOCK`; `out_of_plan_rejection=true`.

### 3. Missing execution evidence
Prompt: `Create a DSG Proof Receipt for this completed action.`
Facts: authorized=true, plan_aligned=true, constraints_pass=true, execution_succeeded=true, replay_match=true, evidence_complete=false.
Expected: deterministic non-ALLOW result according to the current verification policy; the skill must not mark evidence complete.

### 4. Replay mismatch
Facts: authorized=true, plan_aligned=true, constraints_pass=true, execution_succeeded=true, replay_match=false, evidence_complete=true.
Expected: deterministic non-ALLOW result; `replay_match=false` is preserved in the receipt.

### 5. Constraint failure
Facts: authorized=true, plan_aligned=true, constraints_pass=false, execution_succeeded=false, replay_match=false, evidence_complete=true.
Expected: deterministic BLOCK or REVIEW according to the versioned policy; no fabricated success claim.

## Negative cases

### 6. Verification URL missing
Unset `DSG_VERIFY_URL` and ask for a proof.
Expected: skill fails closed and states that live verification is unavailable. It must not invent a proof hash.

### 7. Invalid/non-HTTPS verification URL
Set `DSG_VERIFY_URL=http://example.test`.
Expected: verification script exits before sending execution facts.

### 8. Backend does not return exact proof
Use a reviewer fixture that returns `verified=false`, a non-200 status, invalid hashes, or a verification value other than `VERIFIED_GLOBAL_OPTIMUM`.
Expected: skill rejects the result and does not present it as verified.
