# DSG ONE v1 — independent verification API

The machine-readable contract is [`openapi/dsg-one-v1.yaml`](../openapi/dsg-one-v1.yaml)
(OpenAPI 3.1). This page is the reasoning behind it.

## Why the old shape was not verification

The pre-v1 marketplace endpoint (`POST /verify/evaluate`) takes booleans:

```json
{ "plan_aligned": true, "constraints_pass": true, "replay_match": true, "evidence_complete": true }
```

Those fields come from the agent being verified. An exact Z3 proof over them proves
that the *decision policy* was applied correctly — it cannot prove the inputs were
true. An agent that reports `plan_aligned: true` after going outside its plan gets
an ALLOW receipt, and the receipt is not wrong about anything it actually claims.
That endpoint stays as it is, for the integrations already built on it.

v1 removes the gap. It accepts raw material only, and computes every verdict itself.

| Verdict | v1 computes it from |
|---|---|
| `plan_aligned` | each observed action matched against the approved plan's steps and parameters |
| `constraints_pass` | the declared constraints evaluated over facts DSG derived from the execution |
| `execution_succeeded` | recorded action statuses plus coverage of every non-optional approved step |
| `replay_match` | each action's declared `output_sha256` against digests DSG computed over submitted artifacts |
| `evidence_complete` | artifacts covering the steps the plan says require evidence, content-verified |
| `authorized` | plan approval state, plan-hash identity, and agent identity |

A request that carries any of those fields is refused with **422
`AGENT_ASSERTED_VERDICT_REJECTED`** before it reaches the engine. The rejection is
part of the contract, and `tests/test_api_contract.py` fails the build if the
published schema ever offers one of those fields as input.

## The flow

```
POST /api/v1/plans                          register the raw plan   → plan_hash (computed by DSG)
POST /api/v1/plans/{id}/approve             approve, echoing plan_hash → plan locked
POST /api/v1/verify/plan-alignment          per-action alignment findings
POST /api/v1/verify/constraints             constraint evaluation + exact Z3 proof
POST /api/v1/executions                     record the observed action trace
POST /api/v1/executions/{id}/evidence       submit artifacts; DSG hashes them itself
POST /api/v1/executions/{id}/verify         recompute everything, prove, issue the receipt
GET  /api/v1/proofs/{id}                    read the receipt with its hash recomputed
POST /api/v1/mcp                            the same flow as MCP tools (JSON-RPC 2.0)
GET  /api/v1/status                         readiness — the console shows NOT CONNECTED without it
```

### Approval names exactly what was read

`POST /plans` returns the `plan_hash` DSG computed over its canonical encoding of the
plan. The approval must echo that hash; a mismatch is `PLAN_HASH_MISMATCH`. An
approver therefore cannot approve one text while a different one is stored, and the
receipt's `approval_hash` commits to both.

### Evidence: hashed, or explicitly not verified

* `content` / `content_base64` — DSG hashes the bytes. A `declared_sha256` that
  disagrees is **422 `EVIDENCE_HASH_MISMATCH`**; the submission is rejected, not
  flagged.
* `declared_sha256` alone — recorded as `HASH_ONLY`. It never satisfies a step that
  requires evidence and never counts toward `replay_match`. Attestation is not
  verification, and the receipt says which it had.

### Replay is a hash comparison, not a claim

An action may declare the digest of the output it produced. Replay matches only when
some content-verified artifact hashes to exactly that digest. No declared digests at
all means `replay_match: false` with reason `NO_DECLARED_OUTPUT` — silence is not a
match.

### Facts DSG derives beat facts the agent reports

`observed_facts` on an execution is merged *under* the facts DSG derives itself
(`cost_microunits`, `environment`, `channel`, `agent_identity`, `actions_failed`,
`targets`, `actions`, `evidence_artifacts`). An agent cannot report a cheaper cost
than the one it recorded to slip past a cost cap.

### Decision, then proof

```
BLOCK   not authorized, or out of plan, or a block-severity constraint violated
REVIEW  review-severity findings, incomplete execution, replay mismatch, or incomplete evidence
ALLOW   none of the above
```

The decision is encoded as a bounded 3-variable QUBO (`api_v1/verifier.py`, shared
with the pre-v1 routes) and the Z3 backend must prove its global optimum *and* return
the witness matching the decision DSG derived. If the verifier is unreachable, the
call is **502** and no receipt exists. There is no degraded mode.

### The receipt commits to its own inputs

Every hash a verdict was computed from is in `inputs`: `plan_hash`, `approval_hash`,
`action_trace_hash`, `alignment_hash`, `constraints_hash`, `facts_hash`,
`evidence_hash`, `replay_hash`. `receipt_hash` covers the whole receipt except
itself and the billing block, and `GET /proofs/{id}` recomputes it on read
(`receipt_hash_verified`).

## Universal MCP Connect

`POST /api/v1/mcp` speaks JSON-RPC 2.0 — no SSE, no session to keep alive.
`GET` returns 405 with the transport explained rather than hanging a client that
expects a stream.

Methods: `initialize`, `ping`, `tools/list`, `tools/call`, `resources/list`,
`prompts/list`. Tools: `dsg_status`, `dsg_create_plan`, `dsg_read_plan`,
`dsg_approve_plan`, `dsg_verify_plan_alignment`, `dsg_verify_constraints`,
`dsg_record_execution`, `dsg_submit_evidence`, `dsg_verify_execution`,
`dsg_get_proof`. Tool arguments go through the same verdict rejection, so an MCP
client has no shortcut the REST caller does not have. A refusal comes back as a tool
result with `isError: true` carrying the same `{error, message, remediation}` body.

## Auth, metering, storage

* `X-DSG-API-Key` is optional while `DSG_REVENUE_ENFORCE` is off — anonymous callers
  get unmetered public evaluation, and an unusable key is rejected rather than
  silently served. With a key, `POST /executions/{id}/verify` meters one
  `verified_execution` unit through the existing ledger.
* `DSG_V1_STORE_PATH` selects the record store. Set, it is a lock-guarded JSON file:
  durable for one replica. Unset, records live in process memory and are lost on
  restart. `GET /api/v1/status` reports `storage.mode` and `storage.durable`, so a
  client never has to guess. Multi-replica deployments need a transactional store —
  the same boundary as the revenue ledger (see `REVENUE_AUTOMATION.md`).

## The console

`web/dsg-one-3d/index.html` is served by the API itself at **`GET /app`**, same
origin, so it needs no CORS grant and no configured base URL. It renders only what
the API returned: every tile starts at NOT CONNECTED, becomes PENDING once
`/api/v1/status` answers, and only shows PASS / MATCH / COMPLETE / a decision when a
response carried the corresponding computed field. When the flow fails, it says NOT
VERIFIED and shows the remediation — it has no code path that invents a verdict.
`tests/test_console_prototype.py` enforces that.

## Error codes

| Code | Meaning |
|---|---|
| `AGENT_ASSERTED_VERDICT_REJECTED` | the body carried a verdict DSG computes |
| `PLAN_NOT_FOUND` / `PLAN_NOT_APPROVED` / `PLAN_ALREADY_APPROVED` | plan lifecycle |
| `PLAN_HASH_MISMATCH` | the approval names text other than what is stored |
| `AGENT_IDENTITY_MISMATCH` | the executing agent is not the approved one |
| `EXECUTION_NOT_FOUND` / `EXECUTION_ALREADY_VERIFIED` | execution lifecycle |
| `EVIDENCE_HASH_MISMATCH` / `EVIDENCE_DECODE_FAILED` | the artifact misdescribes itself |
| `PROOF_NOT_FOUND` | no such receipt |
| `BACKEND_UNAVAILABLE` / `VERIFICATION_NOT_PROVED` | fail-closed: no proof, no receipt |

Every one carries a `remediation` block with the single next action that resolves it.
