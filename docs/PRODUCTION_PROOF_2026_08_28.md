<!-- DSG.PICS-IP-WATERMARK:v1; token=DSG.PICS-IP-2026-V1; attribution=dsg.pics; third-party-licenses=preserved -->

# Production Proof — 2026-08-28

> **© 2026 DSG.PICS · `DSG.PICS-IP-2026-V1` · Intellectual Property Attribution**  
> This watermark preserves provenance for original DSG-specific material and does not alter third-party/open-source licenses or the cryptographic meaning of the evidence below.

This record captures the execution evidence used by the README and GitBook for the current DSG Cinema / native Z3 production truth.

## Scope

Verified scope:

- Azure Cinema production deployment
- native Python `z3-solver` production backend
- Cinema → Z3 authenticated E2E
- deterministic replay and proof/request hash equality
- public production MCP transport and tool discovery
- external `dsg_exact_select` call with `useZ3:true`
- deterministic exact top-k result and hashes across two external calls
- fail-closed duplicate candidate validation

Not claimed by this record:

- OpenAI Marketplace approval
- external certification or independent audit
- marketplace approval by any third party

## Source

- repository: `tdealer01-crypto/DSG-Cinema-Proof-Agent`
- production source commit: `90949d7c3acec52258413a5d0e79f0e4e4f51020`
- merge: PR `#163`, `feat(mcp): add native Z3 exact top-k selector`
- attribution watermark: `DSG.PICS-IP-2026-V1`
- project identity: `https://dsg.pics`

## Authoritative endpoints

- Cinema: `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io`
- MCP: `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp`
- native Z3: `https://dsg-z3-verifier-production.nicetree-a005fe99.westus3.azurecontainerapps.io`

The AppDeploy exact-selector app is a reference/demo surface and is not the production Z3 authority.

## Production deployment proof

GitHub Actions:

- workflow: `Deploy Cinema + Z3 Production`
- run: `33189890939`
- job: `98912381919`
- conclusion: `success`
- pre-deploy tests: `164 passed`

Immutable image evidence:

- Z3 image tag: `prod-90949d7c3acec52258413a5d0e79f0e4e4f51020`
- Z3 image digest: `sha256:84bd41effb5e27e99d8f337e1f9ed2bdcb213c95136ab3e79d7b0c70b8b562d4`
- Cinema image tag: `prod-90949d7c3acec52258413a5d0e79f0e4e4f51020`
- Cinema image digest: `sha256:2134f545266e6ad55e523273dd1a3156b8c8919d91441eb643d308b749f87c82`

Direct / Cinema proof:

```json
{
  "direct_verification": "VERIFIED_GLOBAL_OPTIMUM",
  "cinema_status": "VERIFIED",
  "verification": "VERIFIED_GLOBAL_OPTIMUM",
  "witness": [1, 0, 0],
  "energy_exact": "-4",
  "replay_match": true,
  "direct_proof_match": true,
  "proof_hash": "9d096c91291b1cc91543e9191a5f1ab0df89fda284a86a807b79114866b97b8e",
  "request_hash": "ff293f56b354a7815c52dc6f1c9f28a4d001d4bab81b6a1cb323c86b3a714241"
}
```

Evidence artifact:

- artifact ID: `9693455960`
- name: `cinema-production-evidence-90949d7c3acec52258413a5d0e79f0e4e4f51020`
- artifact ZIP SHA-256: `d6ee2109053a5b5283f2011128de29f159c40271345c7e42598cf474adc0ca59`

The deployment workflow also verified billing enforcement behavior, durable ledger survival across a restart, invalid API-key rejection, CORS for configured browser origins, and marketplace adapter execution. Those checks are deployment/runtime readiness evidence; they are not third-party marketplace approval.

## External production MCP proof

GitHub Actions:

- workflow: `MCP Z3 Production Proof`
- run: `33198810484`
- job: `98942758740`
- external runner: GitHub-hosted Ubuntu 24.04
- conclusion: `success`

Verified public-boundary sequence:

1. `GET /api/v1/status` → `READY`, native verification backend ready, MCP endpoint present.
2. MCP `initialize` → protocol `2025-06-18`, server `dsg-one`.
3. MCP `tools/list` → exactly one `dsg_exact_select` definition with expected annotations.
4. MCP `tools/call` with `useZ3:true` → `PASSED`, `verified-exact`, `sat`, selected `b,c`.
5. Repeat the same external call → identical evidence, request and proof hashes.
6. Send duplicate candidate IDs → `isError:true`, `INVALID_ARGUMENTS`.

Test vector:

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

Observed verified result:

```json
{
  "status": "PASS",
  "external_runner": true,
  "useZ3": true,
  "solverResult": "sat",
  "selected": ["b", "c"],
  "deterministicReplay": true,
  "failClosedInvalidInput": true,
  "evidenceHash": "f7b464892eb60556cff2605948ad2a76b9532724e34f4a0cd9b7383afcb3d42c",
  "z3ProofHash": "a5c7b2ee5f1bbd3010cb48f7463ca46d18c61d2672b902e06b6697a41ca45855",
  "z3RequestHash": "b0e2a1abc52bac0e85ab69b0adbf6cf450ce2bfc0cbaa939398a686fc38b5d23"
}
```

Evidence artifact:

- artifact ID: `9696882174`
- name: `mcp-z3-production-proof-19062e36dbb4e2a77d4ea63d65a6cd926e0f1246`
- artifact ZIP SHA-256: `957663623be4b0b6a86edf1a3213fd121d43c1501e1c6d00a24164fdf1132b27`

## Exact-select acceptance conditions

`dsg_exact_select` accepts a native-Z3 result only when all postconditions hold:

- backend response HTTP 200
- `verified == true`
- `verification == VERIFIED_EXACT_TOP_K`
- `z3_status == SAT`
- selected candidates exactly match the independent Python `Decimal` oracle
- request hash is 64 hex characters and recomputes exactly
- proof hash is 64 hex characters and recomputes exactly
- audit contains an integer seed
- `score_optimality == UNSAT_BETTER_SCORE`
- `tie_break_optimality == UNSAT_BETTER_TIE`

Failure of any required condition returns a fail-closed `BLOCKED` result. Input-validation failures are returned by MCP with `isError:true`.

## Documentation consistency rule

If a historical README, GitBook page, Render note, AppDeploy screen, or experiment conflicts with this record, use the production commit, GitHub Actions runs, public Azure endpoints, and hashes in this record as the current source of truth.

For intellectual-property attribution and watermark semantics, see [`INTELLECTUAL_PROPERTY_NOTICE.md`](INTELLECTUAL_PROPERTY_NOTICE.md).

---

`DSG.PICS-IP-WATERMARK:v1 · DSG.PICS-IP-2026-V1 · https://dsg.pics`
