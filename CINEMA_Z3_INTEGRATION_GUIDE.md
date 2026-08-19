# DSG ONE — Cinema + Z3 End-to-End Integration

## Current design

This repository contains the Z3 verifier, Azure deployment workflow, and the
Cinema runtime-integration helper. It does **not** contain the Cinema application
source code itself.

The supported flow is:

```text
candidate / QUBO request
        ↓
Cinema server
        ↓ HTTPS + Bearer token
DSG Z3 verifier
        ↓
Z3 candidate / supplied witness
        ↓
independent lower-energy query
        ↓
UNSAT => VERIFIED_GLOBAL_OPTIMUM
        ↓
deterministic request_hash + proof_hash
        ↓
Cinema response
        ↓
E2E verification gate
```

A proof is not considered verified merely because Z3 returned `SAT`. For QUBO,
`verified=true` is only returned when the independent verifier proves that no
assignment exists with lower energy than the candidate.

## 1. Pull-request verification gate

PRs that change the verifier run `.github/workflows/verify-z3.yml`.

The gate installs the pinned dependencies, compiles the Python files, and runs
`tests/test_z3_main.py`.

Required test outcomes include:

- missing Bearer token is rejected;
- wrong Bearer token is rejected;
- the reference QUBO returns witness `[1,0,0]` with exact energy `-4`;
- the reference QUBO returns `VERIFIED_GLOBAL_OPTIMUM`;
- a deliberately non-optimal witness returns `COUNTEREXAMPLE_FOUND`;
- identical requests replay to the same `request_hash` and `proof_hash`;
- invalid QUBO indices and invalid witnesses are rejected;
- SAT results are deterministic.

**Merge rule:** do not merge while this gate is failing or absent.

## 2. Azure deployment

Canonical deployment is `.github/workflows/deploy-z3-azure.yml`.

It deploys the verifier to Azure Container Apps and exposes the application via
HTTPS. The deployment uses an immutable image tag based on the Git commit SHA.

### Required GitHub Environment secrets

Configure these in the selected GitHub Environment (`staging` or `production`):

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `DSG_SOLVER_SHARED_SECRET` — at least 32 characters

`DSG_SOLVER_SHARED_SECRET` is never generated a second time, written into source,
or placed in the deployment artifact.

### Deployment gate

The workflow fails unless all of these are true:

1. Azure login succeeds.
2. ACR build succeeds.
3. Container App becomes ready at `/ready`.
4. Authenticated `/solve` returns HTTP 200.
5. `verified == true`.
6. `verification == "VERIFIED_GLOBAL_OPTIMUM"`.
7. Witness is `[1,0,0]` and exact energy is `-4` for the reference problem.
8. Two identical requests return the same `proof_hash` and `request_hash`.

The uploaded `deployment_evidence.json` contains no API secret.

## 3. Z3 API contract

### Readiness

```http
GET /ready
```

Expected:

```json
{"status":"ready","service":"dsg-z3-verifier"}
```

### QUBO solve / verify

```http
POST /solve
Authorization: Bearer <DSG_SOLVER_SHARED_SECRET>
Content-Type: application/json
```

Example body:

```json
{
  "request_id": "example-001",
  "preset_name": "cinema",
  "problem_type": "qubo",
  "linear": [-4, -3, 1],
  "quadratic": [[0, 1, 5], [1, 2, 2]],
  "proveOptimality": true,
  "z3TimeoutMs": 30000
}
```

`quadratic` uses `[i, j, coefficient]` terms with `i <= j`.

Expected proof fields for the reference input:

```json
{
  "z3_status": "SAT",
  "verification": "VERIFIED_GLOBAL_OPTIMUM",
  "verified": true,
  "witness": [1, 0, 0],
  "energy": -4.0,
  "energy_exact": "-4",
  "request_hash": "<sha256>",
  "proof_hash": "<sha256>"
}
```

If a caller supplies `witness`, the service verifies that candidate rather than
silently replacing it. A non-optimal supplied witness returns
`COUNTEREXAMPLE_FOUND` with `verified=false`.

## 4. Connect the deployed Cinema App Service

Do **not** put the solver secret in `BuildConfig.kt`, source files, Git commits, or
shell command arguments.

Set the required environment variables locally or in an authorized automation
runtime:

```bash
export Z3_SERVICE_URL='https://<z3-container-app-fqdn>'
export Z3_API_SECRET='<same server-side solver secret used by deployment>'
export AZURE_RESOURCE_GROUP='rg-t.dealer01-0468'
export CINEMA_APP_NAME='dsg-cinema-proof-agent'
export CINEMA_BASE_URL='https://dsg-cinema-proof-agent.azurewebsites.net'
export CINEMA_VERIFY_PATH='/solve'
```

Then run:

```bash
./CINEMA_Z3_AUTO_INTEGRATION.sh
```

or:

```bash
python3 cinema_z3_integration.py
```

The integration helper:

1. requires an HTTPS Z3 URL;
2. verifies Z3 readiness;
3. sends the reference QUBO directly to Z3 and requires an exact proof;
4. stores `DSG_BACKEND_BASE_URL` and `DSG_BACKEND_API_KEY` as Azure App Service
   runtime settings, not source code;
5. confirms both setting names were persisted without printing the secret;
6. restarts the Cinema App Service;
7. waits for Cinema health to recover;
8. sends the same QUBO through Cinema `/solve`;
9. returns PASS only if the Cinema response contains the verified Z3 proof.

Use `--verify-only` to repeat the direct-Z3 and Cinema E2E checks without changing
Azure App Service settings.

## 5. Truth boundary / completion status

Repository-level correctness and production deployment are separate gates.

- **Code gate:** `verify-z3.yml` must pass on the PR head.
- **Deployment gate:** `deploy-z3-azure.yml` must finish successfully and produce
  `deployment_evidence.json`.
- **Cinema E2E gate:** `cinema_z3_integration.py` must return `PASS E2E` against the
  real deployed Cinema application.

Until all three have evidence, do not describe the Cinema + Z3 path as production
ready, fully integrated, or revenue-producing.

Because this repository does not contain Cinema application source code, a failed
Cinema `/solve` E2E check cannot be repaired here by guessing. The actual Cinema
source or deployment must be inspected and fixed at its real source of truth.
