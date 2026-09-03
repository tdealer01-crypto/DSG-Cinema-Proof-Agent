# DSG ONE / Cinema Proof Agent

<!-- DSG.PICS-IP-WATERMARK:v1; token=DSG.PICS-IP-2026-V1; attribution=dsg.pics; third-party-licenses=preserved -->

> **© 2026 DSG.PICS · `DSG.PICS-IP-2026-V1` · Intellectual Property Attribution**  
> Original DSG-specific material is attributed to DSG.PICS. Third-party and open-source components remain under their respective licenses. See [`docs/INTELLECTUAL_PROPERTY_NOTICE.md`](docs/INTELLECTUAL_PROPERTY_NOTICE.md).

DSG ONE / Cinema is a deterministic governance, execution, and evidence runtime for AI agents and automation.

It sits between an Agent and real execution. Authentication establishes **who** is calling; an approved plan, exact plan hash, permissions, runtime capabilities, deterministic verification, and evidence determine **what** that caller is authorized to do. A valid credential never grants out-of-plan authority.

## Open the product

**Primary production customer surface**

https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/dashboard

The normal customer journey is intentionally one page:

```text
/dashboard
   │
   ├─ Agent Chat
   ├─ Connect Agent
   ├─ Remote ON / OFF
   ├─ Shared Browser — one screen, User + Agent
   ├─ Inline exact-plan approval
   │
   └─ LIVE MONITOR
        ├─ 1 ACTION
        ├─ 2 PLAN ALIGNMENT
        ├─ 3 PERMISSION
        ├─ 4 EVIDENCE
        └─ 5 EXECUTION / AUDIT
```

Advanced routes remain available for diagnostics and integrations, but the customer should not need to manually move between `/app`, `/remote-browser/connect-agent`, raw MCP calls, plan IDs, step IDs, or executor endpoints during the normal flow.

---

## Current production truth — verified 3 September 2026

DSG keeps **source state**, **image deployment**, and **runtime proof** separate so a successful proof is not overstated as a full redeploy of every component.

| Item | Verified state |
|---|---|
| Current `main` | `ae75df6f894ea9c0488e3c28da05add42ae2f212` |
| Last verified Cinema image deploy | `dc26871c95b28ebddbfc3d334e4932e0871d7f85` — `Deploy Cinema + Z3 Production #132` — **PASS** |
| Current production revision after rolling pairing proof | `dsg-cinema-production--0000061` |
| Production Cinema | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| Customer dashboard | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/dashboard` |
| Verification MCP | `POST /api/v1/mcp` |
| Paired-agent Remote MCP | `POST /mcp` |
| Native Z3 backend | `https://dsg-z3-verifier-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| Stable pairing proof workflow | `Provision Stable Production Pairing Key` run `33767947131` — **PASS** |
| Stable pairing proof artifact | `9898406622` — `production-pairing-rolling-evidence-ae75df6f894ea9c0488e3c28da05add42ae2f212` |
| Stable pairing proof digest | `sha256:bca25f6c9da82687a38083db43242dd5df546bc727e6a6c62da08883afb2e190` |

The latest rolling-revision proof issued a real production pairing token on one revision, created a genuinely new Container Apps revision, confirmed the dedicated pairing key remained unchanged, then used the **pre-roll token** successfully against `/mcp` on the new revision. The durable claim marker was persisted and the proof token was revoked afterward.

Verdict:

```text
PAIRING_SURVIVED_REAL_PRODUCTION_ROLLING_REVISION_WITH_STABLE_DEDICATED_KEY
```

This is separate from the earlier real process/replica restart proof, which also passed.

---

## Product model

```text
USER
  │
  ▼
Agent Chat
  │
  ▼
Agent / Model
  │
  ▼
Plan proposal
  │
  ▼
Exact plan hash
  │
  ▼
USER APPROVAL when required
  │
  ▼
DSG Gate / Tool Router
  │
  ├─ Shared Browser
  ├─ Universal Runtime
  ├─ Native Z3 verification
  └─ Optional external MCP/API adapters
  │
  ▼
Evidence + deterministic audit
```

The Agent reasons and selects tools. DSG controls the execution boundary and records what actually happened.

## Customer flow

```text
1. Open /dashboard
2. Activate or authenticate the DSG account
3. Connect the Agent from the same page
4. Talk to the Agent
5. Agent proposes a plan when execution authority is required
6. User approves the exact stored plan hash
7. Agent executes only approved steps
8. User and Agent can operate the same Shared Browser session
9. Live Monitor shows governance/evidence state
10. Final result is backed by evidence and audit records
```

The UI must not manufacture green states. Before real runtime data exists, states remain pending, waiting, disconnected, blocked, or unverified.

---

## Shared Browser — one browser, two actors

The current architecture uses one account-scoped browser state shared by the user and approved Agent execution.

```text
                 SHARED BROWSER SESSION
                         │
             ┌───────────┴───────────┐
             │                       │
          USER INPUT              AGENT INPUT
       mouse / keyboard         mouse / keyboard
             │                       │
             └───────────┬───────────┘
                         ▼
                   SAME PAGE STATE
```

Important boundaries:

- Agent actions remain plan-bound.
- Remote OFF revokes Agent remote authority; it does not have to destroy the user's browser/login context.
- Plaintext passwords, OTP values, CAPTCHA answers, and passkeys are not intended to travel through the normal MCP action payload.
- Possession of a browser session or credential does not equal authorization.
- Read-only verifier actions are distinct from mutating Agent actions.

The Azure-native path uses the same account-owned Playwright page for direct user interaction and Agent execution. Low-level Agent mutations are serialized. A fully global USER+AGENT arbitration/sequencing layer should not be assumed unless the specific runtime path proves it.

---

## Durable Agent pairing

The browser keeps the customer's DSG API key. The Agent receives a short-lived `dsg_pair_...` credential instead of the master key.

### Storage model

```text
pairing token
    │
    ├─ plaintext returned once to the caller
    │
    └─ SHA-256(token) persisted
             │
             └─ durable pairing record
                    ├─ account / agent / expiry metadata
                    ├─ claimed_at
                    └─ AES-GCM encrypted DSG API key
```

Security properties implemented in `api_v1/agent_pairing.py`:

- plaintext pairing token is **not persisted**;
- only the token SHA-256 digest identifies the durable record;
- the master DSG API key is AES-GCM encrypted before persistence;
- durable state lives on the shared Remote Action store so another replica can resolve the same token;
- cross-process record locking and atomic replace protect durable mutation;
- expiry and revocation fail closed;
- `claimed_at` is durable;
- the Agent never needs the master DSG API key in its MCP payload.

### Stable production encryption key

Production now binds pairing encryption through:

```text
DSG_AGENT_PAIRING_KEY
        ↓
secretref: agent-pairing-key
```

This is independent from the per-deployment `CINEMA_API_SECRET`.

The one-time migration seeded the dedicated pairing key from the then-current Cinema secret so already-issued unexpired pairing ciphertext remained decryptable. After migration, a normal Cinema secret rotation does not need to invalidate pairing tokens merely because the application revision changes.

### What production has proved

```text
issue token on old runtime
        ↓
persist token hash + encrypted API key
        ↓
new process / replica                ✅ proved
        ↓
real replica restart                 ✅ proved
        ↓
real new Container Apps revision     ✅ proved
        ↓
old token → POST /mcp                ✅ PASS
        ↓
claimed_at durable                   ✅
        ↓
proof token revoked                  ✅
```

---

## Universal Runtime

Cinema also exposes a plan-bound general execution surface for work that is better handled outside browser UI automation.

Current Remote MCP tools include:

```text
universal_runtime_status
universal_execute_step
universal_evidence_verify
```

`universal_execute_step` executes only the step stored in an **already-approved Cinema plan**. The Agent supplies `plan_id + step_id`; it does not get to replace the approved command, code, path, or file content at execution time.

Supported action families include:

```text
fs.list
fs.read
fs.write
python.run
shell.exec
```

Browser work still goes through `remote_action` on the Shared Browser.

### E2E contract

Repository E2E verifies the flow:

```text
Agent creates plan
    ↓
execute before approval → BLOCK
    ↓
USER approves exact plan hash
    ↓
fs.write
    ↓
python.run
    ↓
shell.exec
    ↓
universal evidence verification
```

### Production execution boundary

The in-process local executor is intentionally fail-closed by default.

```text
DSG_UNIVERSAL_LOCAL_EXECUTOR=1
```

is for isolated test/sandbox environments, not the public Cinema web process.

Production is designed to use an isolated executor configured through:

```text
DSG_UNIVERSAL_EXECUTOR_URL
DSG_UNIVERSAL_EXECUTOR_SECRET
```

and the repository contains the production sandbox deployment workflow at:

```text
.github/workflows/deploy-universal-sandbox-production.yml
```

Do not interpret the presence of Universal Runtime tools as permission for arbitrary shell execution. Every executable step remains plan-bound and evidence-bearing.

---

## Governance decision model

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
native Z3 proof where required
  ↓
verified receipt / fail-closed error
```

| Result | Meaning |
|---|---|
| `ALLOW` | Action is aligned with the approved plan and required execution authority is present. |
| `WAITING_PERMISSION` | Plan alignment may be valid, but a required permission, capability, credential, or browser authority is not available yet. |
| `BLOCK` | Action is outside the approved plan, binding does not align, or another deterministic gate rejects it. |

`WAITING_PERMISSION` is not the same as plan rejection.

## Observe and Enforce

### OBSERVE

DSG records the decision, reason, evidence, and audit state without silently converting a policy `BLOCK` into `ALLOW`. Observe mode is useful for evaluation and integration where DSG should not automatically stop the customer's runtime.

### ENFORCE

When enforcement is explicitly enabled, governance decisions can affect execution. Approved actions continue; out-of-plan or unauthorized actions can be stopped or held.

Changing mode changes execution effect, not the underlying governance classification.

---

## Authentication and remote authority

Protected customer API surfaces use an account credential such as:

```http
X-DSG-API-Key: <customer DSG API key>
```

Authentication establishes account identity and entitlement. It does not bypass the approved plan.

Dashboard pairing uses:

```text
POST /remote-browser/enable
POST /remote-browser/agent-pair
GET  /remote-browser/status
POST /remote-browser/disable
```

The short-lived pairing token is the Agent-facing credential. The master customer DSG API key remains server/browser-side and is not intended to become the Agent's long-lived remote credential.

---

## MCP surfaces

See [`docs/API_V1_CONTRACT.md`](docs/API_V1_CONTRACT.md) for the DSG ONE v1 REST/MCP contract.

Cinema exposes two MCP purposes.

### Verification / governance MCP

```text
POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp
```

This is the DSG ONE v1 deterministic governance/verification MCP surface.

### Paired-agent Remote MCP

```text
POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/mcp
```

This is the paired-Agent execution surface. It uses JSON-RPC over `POST`; a plain `GET /mcp` is not the protocol test.

Core tool families include:

```text
remote_contract
remote_status
remote_agent_connect
remote_action
remote_disconnect

dashboard_chat_receive
dashboard_chat_reply
dashboard_chat_create_plan
dashboard_chat_request_approval

universal_runtime_status
universal_execute_step
universal_evidence_verify
```

The Remote contract allows one approved plan to cover its complete declared scope, including declared fallback steps. New approval remains required for out-of-plan scope and other higher-risk boundaries defined by the contract.

---

## Dashboard chat contract

Dashboard chat is transport to a real paired Agent, not a fake local chatbot.

Browser APIs:

```text
GET  /dashboard/api/chat/messages
POST /dashboard/api/chat/messages
POST /dashboard/api/chat/approval
GET  /dashboard/api/monitor
```

If no real paired Agent contacts `/mcp`, the UI waits. Cinema does not fabricate an Agent reply merely to make the demo appear connected.

The Agent can create a plan proposal, but it cannot self-approve the user approval gate.

---

## Live Monitor

The customer-facing monitor has five views:

1. **ACTION** — actor, action, target, and runtime state.
2. **PLAN ALIGNMENT** — whether execution matches the approved plan.
3. **PERMISSION** — whether required execution authority/capability exists.
4. **EVIDENCE** — execution records, hashes, screenshots/API responses when available, and verification state.
5. **EXECUTION / AUDIT** — execution effect plus durable audit state.

Static UI must not ship fabricated `PASS`, `SUCCESS`, or `VERIFIED` states before real evidence exists.

---

## Replay boundary

Replay is **verification only**.

It re-checks recorded inputs, evidence, hashes, and deterministic postconditions. Replay must not silently re-send the original production action.

Historical replay evidence proves the recorded execution it refers to; it does not create a new execution.

---

## Operational surfaces

| Surface | Path |
|---|---|
| Customer dashboard | `/dashboard` |
| Health | `/health` |
| DSG ONE status | `/api/v1/status` |
| Verification MCP | `/api/v1/mcp` |
| Paired-agent Remote MCP | `/mcp` |
| OpenAPI / interactive docs | `/docs` |
| Plans | `/api/v1/plans` |
| Preflight | `/api/v1/control/preflight` |
| Constraint verification | `/api/v1/verify/constraints` |
| Executions | `/api/v1/executions` |
| Proof receipts | `/api/v1/proofs/{proof_id}` |
| Billing status | `/billing/status` |
| Remote enable | `/remote-browser/enable` |
| Agent pairing | `/remote-browser/agent-pair` |
| Remote status | `/remote-browser/status` |
| Remote disable | `/remote-browser/disable` |
| Live contract | `/live/api/contract` |

`/app` and `/remote-browser/connect-agent` remain advanced/compatibility surfaces rather than the normal customer entry point.

---

## Production architecture

```text
Customer / paired Agent
          │
          ▼
       /dashboard
 chat · approval · shared browser · 5 monitors
          │
          ▼
Account authentication / entitlement
          │
          ▼
Exact Plan + Permission + Runtime Gate
          │
     ┌────┼───────────────────┐
     │    │                   │
     ▼    ▼                   ▼
 Shared  Universal          Native Z3
 Browser Runtime            verifier
     │    │                   │
     │    └─ isolated executor│
     │                        │
     └──────────┬─────────────┘
                ▼
       execution evidence
                │
                ▼
 deterministic postconditions
 + hash / replay verification
                │
                ▼
     verified result / failure
```

---

## Deployment and CI

Key workflows:

```text
.github/workflows/deploy-cinema-production.yml
.github/workflows/deploy-universal-sandbox-production.yml
.github/workflows/remote-browser-verify.yml
.github/workflows/production-pairing-restart-proof.yml
.github/workflows/production-agent-pairing-stable-key.yml
```

The stable-key production proof run `33767947131` passed every step, including:

- Azure OIDC login;
- creation/reuse and binding of `agent-pairing-key`;
- confirmation that the secret value stayed unchanged;
- real production token issuance;
- durable record inspection with no plaintext token/API key;
- a real new Container Apps revision;
- successful `/mcp` claim of the token issued before the revision changed;
- durable `claimed_at` verification;
- proof-token revocation;
- non-secret evidence artifact upload.

Passing repository CI proves only the tested contract for that source revision. Passing a production workflow proves only the production actions/checks executed by that workflow. Neither is an external certification or independent audit.

---

## Agent Plugin

The repository publishes the `dsg-governance` Agent Plugin through the `dsg-agent-plugins` marketplace.

Verified GitHub Copilot CLI install path:

```bash
copilot plugin marketplace add tdealer01-crypto/DSG-Cinema-Proof-Agent
copilot plugin marketplace browse dsg-agent-plugins
copilot plugin install dsg-governance@dsg-agent-plugins
```

Credentials remain client-managed and are not embedded in plugin source or README examples.

---

## Truth boundary

DSG evidence supports only the scope actually tested.

A successful internal adapter check, workflow, deterministic proof, deployment, restart proof, rolling-revision proof, or marketplace adapter test does **not** mean an external marketplace, certification body, or independent auditor has approved DSG unless separate evidence explicitly says so.

Likewise, possession of a credential is not proof that an action is authorized. Execution remains subject to exact approved-plan binding, permission/capability state, deterministic gates, runtime availability, and evidence requirements.

## Repository

https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent
