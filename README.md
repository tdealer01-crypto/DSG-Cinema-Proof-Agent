# DSG ONE / Cinema Proof Agent

Deterministic verification and governance runtime for AI-agent and automation execution.

> **Source of truth:** production is the Azure Cinema + native Z3 deployment described below. GitHub Actions execution evidence is authoritative for deployment/proof claims. The AppDeploy exact-selector app is a reference/demo surface, not the production Z3 runtime.

## Current production truth — 28 August 2026

| Item | Verified state |
|---|---|
| Production source commit | `90949d7c3acec52258413a5d0e79f0e4e4f51020` (`feat(mcp): add native Z3 exact top-k selector (#163)`) |
| Production deploy | GitHub Actions run `33189890939` — **PASS** |
| External production MCP proof | GitHub Actions run `33198810484` — **PASS** |
| Cinema production | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| Production MCP | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp` |
| Native Z3 backend | `https://dsg-z3-verifier-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| MCP protocol | `2025-06-18`, HTTP JSON-RPC 2.0 |
| AppDeploy | Reference/demo only: `https://dsg-exact-mcp-runtime-wniyu0.v2.appdeploy.ai/` |
| GitBook | `https://dsg-cinema.gitbook.io/cinema-proof-agent` |

The production deployment ran the pre-deploy regression gate (**164 passed**), built immutable Cinema/Z3 images, deployed both services, verified direct native-Z3 proof, verified Cinema → Z3 E2E replay, exercised marketplace adapters and billing/enforcement gates, and uploaded production evidence.

### Production proof snapshot

**Native Z3 / Cinema proof** — run `33189890939`

- `verification`: `VERIFIED_GLOBAL_OPTIMUM`
- witness: `[1,0,0]`
- exact energy: `-4`
- replay match: `true`
- direct Z3 proof == Cinema proof: `true`
- proof hash: `9d096c91291b1cc91543e9191a5f1ab0df89fda284a86a807b79114866b97b8e`
- request hash: `ff293f56b354a7815c52dc6f1c9f28a4d001d4bab81b6a1cb323c86b3a714241`
- production artifact ID: `9693455960`
- production artifact ZIP SHA-256: `d6ee2109053a5b5283f2011128de29f159c40271345c7e42598cf474adc0ca59`

**External production MCP exact-select proof** — run `33198810484`

A GitHub-hosted Ubuntu runner called the public production MCP endpoint twice with `useZ3:true` using:

```json
{
  "candidates": [
    {"id": "a", "composite": "0.50003"},
    {"id": "b", "composite": "0.50004"},
    {"id": "c", "composite": "0.50004"}
  ],
  "k": 2,
  "minComposite": "0",
  "useZ3": true
}
```

Both calls returned:

- `status`: `PASSED`
- `mode`: `verified-exact`
- `solverResult`: `sat`
- selected IDs: `b`, `c`
- identical evidence/request/proof hashes across replay
- duplicate candidate IDs rejected with `isError:true` / `INVALID_ARGUMENTS`

External proof hashes:

- evidence: `f7b464892eb60556cff2605948ad2a76b9532724e34f4a0cd9b7383afcb3d42c`
- Z3 proof: `a5c7b2ee5f1bbd3010cb48f7463ca46d18c61d2672b902e06b6697a41ca45855`
- Z3 request: `b0e2a1abc52bac0e85ab69b0adbf6cf450ce2bfc0cbaa939398a686fc38b5d23`
- artifact ID: `9696882174`
- artifact ZIP SHA-256: `957663623be4b0b6a86edf1a3213fd121d43c1501e1c6d00a24164fdf1132b27`

See [`docs/PRODUCTION_PROOF_2026_08_28.md`](docs/PRODUCTION_PROOF_2026_08_28.md) for the compact evidence record.

## What DSG verifies

The runtime separates caller intent from verifier judgment. Callers submit plans, actions, execution facts, and evidence; DSG computes the result.

Core control flow:

```text
raw plan
  ↓
plan hash + approval lock
  ↓
preflight decision
  ├─ ALLOW
  ├─ WAITING_PERMISSION
  └─ BLOCK
  ↓
execution trace + evidence
  ↓
deterministic checks
  ↓
native Z3 proof
  ↓
verified receipt / fail-closed error
```

No caller-supplied verdict is accepted as proof. Proof failure is not silently downgraded to an unverified success path.

## MCP surface

Production endpoint:

```text
POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp
```

Transport is stateless HTTP JSON-RPC 2.0. Supported protocol version: `2025-06-18`.

Basic discovery:

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  'https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp' \
  --header 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":"tools-1","method":"tools/list","params":{}}'
```

The MCP registry includes governance tools plus the exact selector `dsg_exact_select`.

### `dsg_exact_select`

Bounded deterministic exact-decimal top-k selection:

| Constraint | Limit |
|---|---:|
| candidates | 1–24 |
| `k` | 1–12 |
| decimal string | max 240 chars |
| decimal exponent | absolute value ≤ 1000 |
| candidate IDs | unique |

Modes:

- `useZ3:false` — Python `Decimal` exact sorting, score descending then candidate ID ascending.
- `useZ3:true` — native Z3 exact-real optimization plus independent optimality obligations. The result is accepted only if Z3 reports `VERIFIED_EXACT_TOP_K`, SAT, selected IDs match the independent Decimal oracle, request/proof hashes recompute exactly, and both `UNSAT_BETTER_SCORE` and `UNSAT_BETTER_TIE` obligations are present.

Any backend failure, proof mismatch, result mismatch, invalid hash, invalid audit record, insufficient exact-k population, or invalid input is fail-closed.

Example production call:

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  'https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp' \
  --header 'Content-Type: application/json' \
  --data '{
    "jsonrpc":"2.0",
    "id":"exact-1",
    "method":"tools/call",
    "params":{
      "name":"dsg_exact_select",
      "arguments":{
        "candidates":[
          {"id":"a","composite":"0.50003"},
          {"id":"b","composite":"0.50004"},
          {"id":"c","composite":"0.50004"}
        ],
        "k":2,
        "minComposite":"0",
        "useZ3":true
      }
    }
  }'
```

The tool is advertised with:

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

## REST and operational surfaces

| Surface | Path |
|---|---|
| Health | `/health` |
| DSG ONE status | `/api/v1/status` |
| MCP | `/api/v1/mcp` |
| OpenAPI / interactive docs | `/docs` |
| Plans | `/api/v1/plans` |
| Preflight | `/api/v1/control/preflight` |
| Constraint verification | `/api/v1/verify/constraints` |
| Executions | `/api/v1/executions` |
| Proof receipts | `/api/v1/proofs/{proof_id}` |
| Billing status | `/billing/status` |

Some mutation, verification, and billing operations require an API key or server-side credential. Secrets are not accepted through the public exact-selector tool.

## Production architecture

```text
MCP / REST client
      │
      ▼
Azure Container Apps
DSG Cinema Proof Agent
      │
      │ authenticated server-to-server request
      ▼
Azure Container Apps
Native Z3 Verifier
      │
      ├─ exact Real / Bool constraints
      ├─ deterministic seed
      ├─ optimizer / solver proof obligations
      └─ request + proof hashes
      │
      ▼
Cinema postconditions
      │
      ├─ independent deterministic oracle
      ├─ hash recomputation
      ├─ replay checks
      └─ fail-closed decision
```

Production images are built in Azure Container Registry from the exact source commit used by the deployment workflow.

For commit `90949d7c3acec52258413a5d0e79f0e4e4f51020`:

- Z3 image digest: `sha256:84bd41effb5e27e99d8f337e1f9ed2bdcb213c95136ab3e79d7b0c70b8b562d4`
- Cinema image digest: `sha256:2134f545266e6ad55e523273dd1a3156b8c8919d91441eb643d308b749f87c82`

## Deployment and CI

Canonical production workflow:

```text
.github/workflows/deploy-cinema-production.yml
```

The workflow is fail-closed and coordinates Z3 + Cinema deployment. It verifies contracts before deployment, builds immutable images, deploys native Z3, proves Z3 directly, deploys Cinema, verifies Cinema → Z3 and deterministic replay, validates runtime/billing safety gates, and uploads non-secret evidence.

The external MCP proof is intentionally executed from a GitHub-hosted runner rather than from inside the Azure service, so it verifies the public production boundary a client actually reaches.

## Evidence boundary

The following claims are execution-verified as of 28 August 2026:

- native Z3 production solve
- Cinema → Z3 authenticated E2E
- deterministic replay of the production proof
- public production MCP initialize and tool discovery
- `dsg_exact_select useZ3:true` from an external runner
- exact selected result and deterministic hashes across replay
- fail-closed duplicate-ID validation

These statements do **not** mean that any external marketplace has approved or certified DSG. In particular, a DSG adapter result named `openai_plugin` verifies that DSG's adapter path passed its own production contract; it is **not** OpenAI Marketplace approval or submission status.

## AppDeploy reference surface

`https://dsg-exact-mcp-runtime-wniyu0.v2.appdeploy.ai/` is retained as a reference/demo for the bounded exact-selection contract. It is not the production Z3 authority.

The authoritative native Z3 execution proof and public MCP proof are the Azure + GitHub Actions records above. Documentation and UI on the AppDeploy reference surface should point back to this production boundary instead of claiming AppDeploy itself is the production solver.

## Local development

```bash
git clone https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent.git
cd DSG-Cinema-Proof-Agent
python -m pip install -r requirements-cinema.txt pytest
python -m pytest -q
```

For the native Z3 service, install the dependencies from `requirements.txt` and use the Z3 wrapper defined by the production Dockerfile.

Do not place production secrets in source files or example commands.

## Documentation

- [`docs/`](docs/) — operational and technical documentation
- [`docs/PRODUCTION_PROOF_2026_08_28.md`](docs/PRODUCTION_PROOF_2026_08_28.md) — current proof record
- [GitBook — Cinema Proof Agent](https://dsg-cinema.gitbook.io/cinema-proof-agent) — published documentation
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — additional deployment notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contribution workflow

Historical experiments and alternate-host deployment notes may remain in the repository for reproducibility. They are not authoritative when they conflict with the **Current production truth** section of this README.

## Contributing

1. Branch from `main`.
2. Add or update tests for behavior changes.
3. Run the relevant local verification suite.
4. Open a pull request.
5. Merge only after required CI/proof gates pass.

## License and support

See [`LICENSE`](LICENSE).

- Issues: https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues
- Support: `support@dsg.pics`

---

**Last updated:** 28 August 2026  
**Verification status:** Production Azure Cinema + native Z3 + external MCP `useZ3:true` execution proof **VERIFIED** within the runtime/MCP/Z3/deterministic/fail-closed scope described above.
