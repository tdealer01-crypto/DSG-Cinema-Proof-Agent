# DSG ONE / Cinema Proof Agent

<!-- DSG.PICS-IP-WATERMARK:v1; token=DSG.PICS-IP-2026-V1; attribution=dsg.pics; third-party-licenses=preserved -->

> **© 2026 DSG.PICS · `DSG.PICS-IP-2026-V1` · Intellectual Property Attribution**  
> Original DSG-specific material is attributed to DSG.PICS. Third-party and open-source components remain under their respective licenses. See [`docs/INTELLECTUAL_PROPERTY_NOTICE.md`](docs/INTELLECTUAL_PROPERTY_NOTICE.md).

Deterministic verification and governance runtime for AI-agent and automation execution.

DSG ONE / Cinema sits between an agent and real execution. Authentication establishes who is calling. Approved plans, permissions, deterministic verification, and evidence decide what the caller is allowed to do. A valid credential does **not** grant authority to execute outside the approved plan.

> **Source of truth:** production is the Azure Cinema + native Z3 deployment described below. GitHub Actions execution evidence is authoritative for deployment/proof claims. Historical proof remains useful evidence, but it does not override a newer verified production deployment.

## Current production truth — verified 1 September 2026 UTC / 2 September 2026 Asia/Bangkok

| Item | Verified state |
|---|---|
| Production source commit | `46d4db76cb57a00df7ee536a35d666d2e4b90bd8` — `feat: secure agent pairing and API key controls (#195)` |
| Production deploy | GitHub Actions run `33537989165` / run #103 — **PASS** |
| Production evidence artifact | `9812708964` — `cinema-production-evidence-46d4db76cb57a00df7ee536a35d666d2e4b90bd8` |
| Evidence artifact digest | `sha256:97dd13281e020cd7469791507e54de0a0ffcad50be75f6f536fbb5d6a9f21c1a` |
| Cinema production | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| Production MCP | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp` |
| Native Z3 backend | `https://dsg-z3-verifier-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| MCP protocol | `2025-06-18`, HTTP JSON-RPC 2.0 |
| GitBook | `https://dsg-cinema.gitbook.io/cinema-proof-agent` |

The current production deployment completed the production workflow successfully from the exact source SHA above. The workflow passed contract verification, resolved production identity/secrets, built immutable images, deployed native Z3, verified a direct Z3 proof, deployed Cinema, verified Cinema → Z3 E2E plus replay, checked marketplace/browser boundaries and revenue state, and uploaded non-secret production evidence.

### Production capabilities included in the current source

The current production SHA includes the work merged immediately before and through PR #195:

- **Azure shared browser** — account-scoped browser continuity for the user while agent authority remains separately controlled.
- **Browser Memory / long logical context** — the Browser Memory work merged before the current production SHA; its dedicated shared-browser continuity production E2E workflow completed successfully before PR #195.
- **Secure agent pairing** — Remote ON/OFF is account-scoped and requires a valid DSG account credential.
- **Short-lived agent credentials** — remote action sessions use short-lived session authority instead of exposing a long-lived customer credential to every remote action.
- **Plan-bound remote execution** — enabling Remote does not itself authorize arbitrary actions; the agent must still connect through the approved-plan execution path.
- **Native Z3 verification** — Cinema performs authenticated server-to-server verification against the native Z3 production service and verifies postconditions/replay.

## What DSG verifies

The runtime separates caller intent from verifier judgment. Callers submit plans, actions, execution facts, and evidence; DSG computes the result.

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

`WAITING_PERMISSION` is not the same as plan rejection. An action can be aligned with the approved plan but still lack the credential, capability, browser authority, or other execution permission required at that moment.

## Authentication and execution authority

Cinema intentionally separates **authentication** from **authorization**.

### 1. Customer / agent account authentication

Customer-facing protected surfaces use:

```http
X-DSG-API-Key: <customer DSG API key>
```

The revenue/account layer authenticates the key and resolves the DSG account/entitlement. API-key authentication answers **who is calling**; it does not bypass the approved plan.

### 2. Remote Browser authority

The account owner controls remote authority through the Remote Browser surface:

```text
POST /remote-browser/enable
GET  /remote-browser/status
POST /remote-browser/agent-connect
POST /remote-browser/disable
```

These routes require `X-DSG-API-Key` and resolve the authenticated account before reading or changing pairing state.

Remote ON means the account permits an agent to attempt a plan-bound connection. It does **not** mean unrestricted browser control.

```text
customer enables Remote
        ↓
authenticated DSG account
        ↓
shared browser is provisioned/resumed
        ↓
agent-connect request
        ↓
approved plan + exact agent/step/action checks
        ↓
short-lived remote session authority
        ↓
remote action
        ↓
evidence / audit
```

Disabling Remote revokes active remote agent sessions while leaving the user's shared browser/login context available to the user.

### 3. Short-lived remote session credentials

Remote sessions use an opaque session token with a bounded TTL. Current request validation allows a TTL from **60 to 3600 seconds**, with a **900-second default**. Session tokens are sealed/opened by the remote-browser authority layer and are separate from the customer's long-lived DSG API key.

The design goal is capability scoping: a remote session credential represents a specific authorized session, not permanent account authority.

### 4. Server-to-server credentials

Cinema keeps trusted backend credentials separate from customer credentials. Native Z3 verification uses a server-side backend credential over the authenticated Cinema → Z3 boundary. Production secrets are supplied through deployment/runtime configuration and are not placed in README examples.

### 5. Plan authorization remains the execution boundary

A valid API key or remote session token does not convert an out-of-plan action into an allowed action.

Expected decision model:

| Result | Meaning |
|---|---|
| `ALLOW` | Action is aligned with the approved plan and required execution authority is present. |
| `WAITING_PERMISSION` | Plan alignment is valid, but a required permission/capability/credential is not available yet. |
| `BLOCK` | Action is outside the approved plan, identity/step/target does not align, or another deterministic gate rejects it. |

## Customer flow

A normal governed execution is:

```text
1. Connect with a DSG API key
2. Create a plan
3. Approve the exact plan hash
4. Run preflight
5. Receive ALLOW / WAITING_PERMISSION / BLOCK
6. If browser work is needed, turn Remote ON
7. Agent connects to the approved plan/step
8. Execute only the authorized action
9. Record evidence
10. Verify / receive proof
```

The user should not need to inspect raw logs to understand the control result. Product surfaces should expose the decision, reason, evidence, and next required action directly.

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
- `useZ3:true` — native Z3 exact-real optimization plus independent optimality obligations. The result is accepted only when the solver/proof/postconditions satisfy the tool's deterministic verification contract.

Backend failure, proof mismatch, result mismatch, invalid hash/audit data, insufficient exact-k population, or invalid input is fail-closed.

Example:

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

The exact selector is advertised as read-only, non-destructive, closed-world, and idempotent.

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
| Remote enable | `/remote-browser/enable` |
| Remote status | `/remote-browser/status` |
| Agent connect | `/remote-browser/agent-connect` |
| Remote disable | `/remote-browser/disable` |

Protected mutation, execution, pairing, verification, and billing surfaces may require a DSG API key or server-side credential according to their route contract. Secrets are not accepted as proof and do not replace plan authorization.

## Shared Browser and Browser Memory

The shared browser is **account-scoped**. Agent remote authority is **plan/session-scoped**.

This separation is deliberate:

```text
USER BROWSER / LOGIN CONTEXT
        │
        ├── persists for the account
        │
        └── does not imply agent authority

AGENT REMOTE AUTHORITY
        │
        ├── user enables/disables Remote
        ├── agent connects through approved plan
        ├── session authority is short-lived
        └── disabling Remote revokes agent sessions
```

The Browser Memory/continuity work was merged before the current production SHA and had a dedicated production continuity workflow complete successfully. The current production deployment includes that code together with the later secure pairing changes.

## Production architecture

```text
MCP / REST / Remote client
          │
          ▼
Account authentication / entitlement
          │
          ▼
Plan + permission + execution gates
          │
      ┌───┴─────────────┐
      │                 │
      ▼                 ▼
Remote Browser       Native Z3
pairing/session      verifier
      │                 │
      └──────┬──────────┘
             ▼
     execution evidence
             │
             ▼
 deterministic postconditions
 + hash/replay verification
             │
             ▼
   verified receipt / failure
```

Production images are built from the exact source commit selected by the canonical deployment workflow.

## Deployment and CI

Canonical production workflow:

```text
.github/workflows/deploy-cinema-production.yml
```

The production workflow is scoped to runtime/deployment-sensitive paths rather than README-only changes. It coordinates Cinema + Z3 deployment and verification, including:

- pre-deploy contract checks
- Azure identity/runtime configuration
- immutable image builds
- native Z3 deployment and direct proof
- Cinema deployment
- Cinema → Z3 E2E and deterministic replay
- marketplace/browser boundary checks
- revenue-state verification
- non-secret evidence generation and upload

Current verified deployment: **run `33537989165` — PASS** for source `46d4db76cb57a00df7ee536a35d666d2e4b90bd8`.

## Evidence boundary

### Current production claims supported by run `33537989165`

The current deployment workflow provides execution evidence that the deployment from SHA `46d4db76...` completed successfully and passed the workflow's production verification stages, including direct native-Z3 proof and Cinema → Z3 E2E/replay verification.

It also verifies the deployment/runtime checks represented by the successful workflow steps. The evidence artifact is recorded in the current production table above.

### Shared Browser / Browser Memory continuity evidence

Before PR #195, the production sequence included:

- PR #193 / source `8b9b5f2f...` — Azure-native shared browser deployment; production deploy run `33495673913` — **PASS**.
- PR #194 / source `e4eaea7a...` — Browser Memory / long logical context; production deploy run `33536014400` — **PASS**.
- shared-browser continuity production E2E run `33537273434` — **PASS** before the secure pairing deployment.

The later production SHA `46d4db76...` is a descendant of those changes and was itself deployed successfully.

### Historical external MCP proof — 28 August 2026

The separately recorded external public MCP exact-select proof remains useful historical evidence:

- production deploy run `33189890939` — **PASS** for source `90949d7c3acec52258413a5d0e79f0e4e4f51020`
- external production MCP proof run `33198810484` — **PASS**
- external selected IDs: `b`, `c`
- duplicate candidate IDs rejected fail-closed
- evidence hash: `f7b464892eb60556cff2605948ad2a76b9532724e34f4a0cd9b7383afcb3d42c`
- Z3 proof hash: `a5c7b2ee5f1bbd3010cb48f7463ca46d18c61d2672b902e06b6697a41ca45855`
- Z3 request hash: `b0e2a1abc52bac0e85ab69b0adbf6cf450ce2bfc0cbaa939398a686fc38b5d23`

See [`docs/PRODUCTION_PROOF_2026_08_28.md`](docs/PRODUCTION_PROOF_2026_08_28.md) for that historical compact evidence record.

That external run proves the public MCP boundary for the deployment it tested. It is intentionally **not** presented as a new external-run proof of the later 1 September production SHA unless a newer external proof run exists.

## Truth boundary

DSG evidence supports only the scope actually tested.

A successful DSG adapter, workflow, proof, or internal marketplace check does **not** mean an external marketplace or certification body has approved DSG. Product documentation must not convert internal verification into external certification, marketplace approval, or independent audit claims.

Likewise, possession of a credential is not proof that an action is authorized. Execution remains subject to the approved plan, permission/capability state, deterministic gates, and evidence requirements.

## AppDeploy reference surface

`https://dsg-exact-mcp-runtime-wniyu0.v2.appdeploy.ai/` may remain as a reference/demo for the bounded exact-selection contract. It is not the authoritative production Z3 runtime.

The authoritative production boundary is Azure Cinema + native Z3 together with the GitHub Actions evidence associated with the deployed source SHA.

## Local development

```bash
git clone https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent.git
cd DSG-Cinema-Proof-Agent
python -m pip install -r requirements-cinema.txt pytest
python -m pytest -q
```

For the native Z3 service, install the dependencies from `requirements.txt` and use the Z3 wrapper defined by the production Dockerfile.

Do not place production secrets in source files, documentation, screenshots, or example commands.

## Documentation

- [`docs/`](docs/) — operational and technical documentation
- [`docs/API_V1_CONTRACT.md`](docs/API_V1_CONTRACT.md) — canonical DSG ONE v1 authorization and verification contract
- [`docs/PRODUCTION_PROOF_2026_08_28.md`](docs/PRODUCTION_PROOF_2026_08_28.md) — historical 28 August production proof record
- [`docs/INTELLECTUAL_PROPERTY_NOTICE.md`](docs/INTELLECTUAL_PROPERTY_NOTICE.md) — DSG.PICS attribution/watermark notice
- [GitBook — Cinema Proof Agent](https://dsg-cinema.gitbook.io/cinema-proof-agent) — published documentation
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — additional deployment notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contribution workflow

Historical experiments and alternate-host deployment notes may remain in the repository for reproducibility. They are not authoritative when they conflict with the **Current production truth** section of this README.

## Intellectual property and support

Canonical watermark: `DSG.PICS-IP-2026-V1`.

© 2026 DSG.PICS. Original DSG-specific material is attributed to DSG.PICS, while third-party/open-source material remains governed by its respective licenses and notices. This attribution notice does not itself assert patent registration, trademark registration, external certification, or marketplace approval.

- Project identity: `https://dsg.pics`
- Issues: `https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues`
- Support: `support@dsg.pics`

---

`DSG.PICS-IP-WATERMARK:v1 · DSG.PICS-IP-2026-V1 · https://dsg.pics`

**Last updated:** 2 September 2026 (Asia/Bangkok)  
**Current production source:** `46d4db76cb57a00df7ee536a35d666d2e4b90bd8`  
**Verification status:** Azure Cinema + native Z3 production deployment **PASS** in GitHub Actions run `33537989165`, with production evidence artifact `9812708964`. Historical external MCP proof is retained separately and is not overstated as a fresh proof of the later production SHA.
