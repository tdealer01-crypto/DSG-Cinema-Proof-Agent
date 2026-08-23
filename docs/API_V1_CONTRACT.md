# DSG ONE v1 — plan-authorized execution + independent verification

The machine-readable contract is [`openapi/dsg-one-v1.yaml`](../openapi/dsg-one-v1.yaml)
(OpenAPI 3.1). This page explains the production behavior behind it.

## One rule before execution

DSG does **not** block work merely because it is powerful, writes to production,
or needs a credential. The authorization question is narrower and deterministic:

- **`ALLOW`** — the exact action is inside an approved plan and its required
  server-side capabilities are ready. DSG emits a scoped capability grant and the
  executor may run that exact step.
- **`WAITING_PERMISSION`** — the exact action is still inside the approved plan,
  but a required server-side credential/tool/infrastructure capability is not ready.
  The plan remains authorized. The orchestrator resolves the capability and retries
  the same step **without asking the user to approve it again**.
- **`BLOCK`** — the action is outside the approved boundary: the plan is not
  approved, the executing agent is different, or the action/target/parameters do
  not match the approved step. The audited Android adapter also blocks a different
  mobile build identity.

This rule lives in `api_v1/decision_core.py`. REST, MCP and the Android adapter call
that same core rather than implementing their own approval semantics.

## Capabilities are resolved server-side

A caller may say which capability an approved step requires, but it cannot say that
capability is already available. `api_v1/capability_broker.py` derives readiness
from trusted server configuration and never returns secret values.

Current registered capability names include:

- `dsg_verifier`
- `cinema_bridge`
- `revenue_admin`
- `stripe_api`
- `stripe_webhook`
- `azure_oidc`
- `sentry`

An unknown or unconfigured capability produces `WAITING_PERMISSION`, not an
out-of-plan `BLOCK`. That distinction prevents DSG governance from turning into a
blanket execution blocker.

Useful endpoints:

```text
GET  /api/v1/control/contract       canonical decision semantics
GET  /api/v1/control/capabilities   server-derived capability readiness, no secrets
POST /api/v1/control/preflight      authorize one exact approved step
```

## Why the old verification shape was insufficient

The pre-v1 marketplace endpoint (`POST /verify/evaluate`) takes booleans such as:

```json
{ "plan_aligned": true, "constraints_pass": true, "replay_match": true, "evidence_complete": true }
```

Those values come from the agent being verified. An exact Z3 proof over them can
prove that the decision policy was applied correctly, but it cannot prove that the
inputs themselves were true.

v1 therefore accepts raw material and computes its own verdicts.

| Verdict | v1 computes it from |
|---|---|
| `plan_aligned` | each observed action matched against approved steps and parameters |
| `constraints_pass` | declared constraints evaluated over facts DSG derives from the execution |
| `execution_succeeded` | recorded action statuses plus coverage of required approved steps |
| `replay_match` | action `output_sha256` values compared with digests DSG computes over submitted artifacts |
| `evidence_complete` | content-verified artifacts covering steps that require evidence |
| `authorized` | plan approval state, plan-hash identity and agent identity |

A request carrying DSG-computed verdict fields is refused with **422
`AGENT_ASSERTED_VERDICT_REJECTED`** before it reaches the verification engine.
`tests/test_api_contract.py` also checks that the published OpenAPI request schemas
do not offer those fields.

## Canonical production flow

```text
POST /api/v1/plans                          register raw plan → DSG-computed plan_hash
POST /api/v1/plans/{id}/approve             approve and lock that exact plan_hash
POST /api/v1/control/preflight              ALLOW / WAITING_PERMISSION / BLOCK
                                            ↓
                                  provision if needed, then execute exact granted step
                                            ↓
POST /api/v1/control/mutations              guarded mutation: ALLOW writes one
                                            tenant-bound evidence row and answers
                                            with the row read back from the database
POST /api/v1/executions                     record observed reality for audit
POST /api/v1/executions/{id}/evidence       submit artifacts; DSG hashes content itself
POST /api/v1/executions/{id}/verify         recompute everything + exact Z3 proof
GET  /api/v1/proofs/{id}                    read receipt and recomputed receipt hash
```

`POST /api/v1/verify/plan-alignment` and
`POST /api/v1/verify/constraints` remain available as explicit diagnostic /
verification legs. They do not replace the pre-execution Decision Core.

### Authorization is not audit storage

`POST /api/v1/control/preflight` is the gate that decides whether the executor may
perform a proposed action.

`POST /api/v1/executions` is deliberately different: it records what actually
happened. If an executor ever violates a prior `BLOCK`, the raw trace is preserved
so the audit trail can prove the violation. Discarding that record would destroy
evidence; storing it does **not** retroactively authorize the action.

### Guarded mutation execution

`POST /api/v1/control/mutations` is the state-changing counterpart to preflight. It
re-runs the same Decision Core check and, only on `ALLOW`, writes one row of
`dsg_guarded_evidence` and reads it back **inside the same transaction**. The
response body is that read-back, plus the `evidence_hash` recomputed from it — not
an echo of the request and not a value the process kept in memory.

- Every row carries `tenant_id`, the authenticated revenue account. There is no
  anonymous path: a request without a usable `X-DSG-API-Key` is `401 UNKNOWN_KEY`.
- `(tenant_id, idempotency_key)` is unique **in the database**. A retry of the same
  action returns the stored row with `created: false` (HTTP 200); a first write is
  HTTP 201.
- The same key presented for a *different* action is `409 IDEMPOTENCY_KEY_CONFLICT`.
  Serving the stored row there would answer a retry that is not a retry.
- `WAITING_PERMISSION` and `BLOCK` write nothing and return HTTP 200 with
  `executed: false`, so an unauthorized mutation never leaves a record that looks
  like an authorized one.
- `GET /api/v1/control/mutations/{evidence_id}` reads a row back. A row belonging to
  another tenant is indistinguishable from a row that does not exist.
- `parameters` and `outputs` are stored as canonical JSON **text**, not JSONB. JSONB
  normalises numbers on the way back out, and a row whose payload reads back
  differently than it was written could not reproduce its own `evidence_hash`.

Storage is PostgreSQL/Supabase when `DSG_REVENUE_DATABASE_URL` is set — the same
variable that selects the PostgreSQL revenue stores, so `tenant_id` carries a real
foreign key to `dsg_revenue_accounts`. Without it the store is process memory, which
forgets idempotency across a restart; `GET /api/v1/status` reports which is live
under `guarded_mutation_storage`, and a deployment that requests paid enforcement on
a memory-backed store is refused with `503 GUARDED_STORAGE_NOT_READY`.

### Approval names exactly what was read

`POST /plans` returns the `plan_hash` DSG computed over the canonical plan. Approval
must echo that hash. A mismatch is `PLAN_HASH_MISMATCH`. An approved plan is locked;
changed work requires a changed plan.

### Evidence is hashed, or explicitly not verified

- `content` / `content_base64` — DSG hashes the bytes. A `declared_sha256` that
  disagrees is **422 `EVIDENCE_HASH_MISMATCH`**.
- `declared_sha256` alone — recorded as hash-only evidence. It does not satisfy a
  content-required step and does not prove replay by itself.

### Replay is a comparison, not a claim

An action may record the digest of the output it produced. Replay matches only when
content-verified evidence hashes to that same digest. No matching submitted bytes
means no replay proof.

### Facts DSG derives override caller-reported facts

`observed_facts` is merged under facts DSG derives itself, including environment,
channel, agent identity, action counts, failed/skipped actions, targets and evidence
count. A caller cannot override those derived values to make a constraint pass.

## Verification decision and exact proof

The post-execution verification vocabulary remains:

```text
BLOCK   not authorized / out of plan / block-severity constraint violation
REVIEW  review finding, incomplete execution, replay mismatch or incomplete evidence
ALLOW   none of the above
```

This is distinct from the pre-execution `WAITING_PERMISSION` state. A missing
credential is an orchestration/provisioning state, not a final proof verdict.

The verification decision is encoded as a bounded 3-variable QUBO and the Z3
backend must prove the global optimum and return the witness matching the decision
DSG derived. If the verifier is unreachable, verification returns **502** and no
verified receipt exists. There is no fabricated/degraded PASS.

## Receipt integrity

The receipt commits to the hashes of the material used to derive its verdict,
including the approved plan, observed action trace, alignment, constraints, facts,
evidence and replay. `receipt_hash` covers the receipt, and `GET /proofs/{id}`
recomputes it when read.

## Universal MCP Connect

`POST /api/v1/mcp` uses JSON-RPC 2.0. `GET` returns 405 with the transport hint.

Methods: `initialize`, `ping`, `tools/list`, `tools/call`, `resources/list`,
`prompts/list`.

Tools include:

- `dsg_status`
- `dsg_create_plan`
- `dsg_read_plan`
- `dsg_approve_plan`
- **`dsg_preflight_action`** — the same Decision Core as REST
- `dsg_verify_plan_alignment`
- `dsg_verify_constraints`
- `dsg_record_execution` — audit recording, including violation traces
- `dsg_submit_evidence`
- `dsg_verify_execution`
- `dsg_get_proof`

MCP therefore has no alternate approval logic or shortcut around the core.

## Audited Android adapter

The supplied `base.apk` is pinned in `mobile/base-apk.identity.json` and the mobile
adapter exposes:

```text
GET  /api/v1/mobile/client-contract
POST /api/v1/mobile/control/preflight
```

The adapter validates the audited package/version/APK/signing identity, authenticates
the trusted bridge, then delegates plan authorization and capability resolution to
the same Decision Core. Mobile does not get a second policy implementation.

The signed APK itself remains a release/workflow artifact rather than source code.

## Auth, metering and storage

- `X-DSG-API-Key` remains the DSG account/metering credential where enforcement is
  enabled. Transport/account authentication is separate from plan authorization.
- The Android bridge can use the trusted server-side Cinema bearer credential or a
  DSG API key; credentials remain server-side and are never returned to the APK.
- `DSG_REVENUE_DATABASE_URL` selects PostgreSQL/Supabase for the revenue stores and
  for guarded mutation evidence (`dsg_guarded_evidence`). TLS is enforced by the
  connection rather than by the written URI: a connection string that omits
  `sslmode` is opened with `require`, and one that explicitly asks for `disable`,
  `allow` or `prefer` is refused. Existing databases that
  already carry the earlier evidence skeleton run
  `scripts/sql/0002_extend_dsg_guarded_evidence.sql` once; a fresh database is
  created in the final shape by the application's own bootstrap.
- `DSG_V1_STORE_PATH` selects the v1 record store. Without durable multi-replica
  storage, `GET /api/v1/status` exposes the storage mode so callers do not have to
  guess durability.

## Console behavior

`web/dsg-one-3d/index.html` is served at `GET /app`. It renders API-returned state;
it does not invent PASS/MATCH/COMPLETE values. `tests/test_console_prototype.py`
enforces that behavior.

## Key error / state vocabulary

| Code / state | Meaning |
|---|---|
| `PLAN_AUTHORIZED_ACTION` | exact approved action, execution-ready |
| `PLAN_AUTHORIZED_CAPABILITY_PENDING` | exact approved action, capability provisioning required; not policy-blocked |
| `AGENT_ASSERTED_VERDICT_REJECTED` | request attempted to supply a DSG-computed verdict |
| `PLAN_NOT_FOUND` | no stored plan with that id |
| `PLAN_NOT_APPROVED` | plan has not been approved/locked; preflight returns `BLOCK` |
| `PLAN_HASH_MISMATCH` | approval does not name the stored plan exactly |
| `AGENT_IDENTITY_MISMATCH` | executor differs from the approved agent |
| `OUT_OF_PLAN_ACTION` | action or target differs from approved scope |
| `PARAMETER_MISMATCH` / `UNDECLARED_PARAMETER` | proposed parameters differ from approved scope |
| `EVIDENCE_HASH_MISMATCH` / `EVIDENCE_DECODE_FAILED` | evidence misdescribes its bytes |
| `IDEMPOTENCY_KEY_CONFLICT` | the key is already bound to a different action_hash |
| `MUTATION_NOT_FOUND` | no guarded evidence row with that id for this tenant |
| `GUARDED_STORAGE_NOT_READY` | paid enforcement requested while guarded evidence has no durable store |
| `GUARDED_EVIDENCE_UNREADABLE` | the row could not be read back; retry with the same key is safe |
| `BACKEND_UNAVAILABLE` / `VERIFICATION_NOT_PROVED` | fail-closed proof path; no verified receipt |

The essential invariant is simple: **DSG opens the path for work already approved,
provisions what that work needs, blocks only boundary violations, and keeps evidence
of what actually happened.**
