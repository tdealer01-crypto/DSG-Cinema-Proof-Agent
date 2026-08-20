# Release notes — 1.0.0

Initial Skills-only submission of DSG Verified Execution.

- Adds the bounded Verified Execution schema for approved-plan/action checks.
- Uses the current DSG Cinema `/verify/evaluate` backend rather than the retired Control Plane runtime.
- Requires exact Z3 `VERIFIED_GLOBAL_OPTIMUM` before returning a verified Proof Receipt.
- Returns ALLOW, REVIEW, or BLOCK with proof/request/context hashes.
- Surfaces authorized-action completion, out-of-plan rejection, Z3 constraint correctness, replay match, evidence completeness, and cost/run fields.
- Fails closed when the live endpoint is unavailable or returns an invalid proof.
- Does not expose backend solver credentials and does not accept arbitrary QUBO input.
