# DSG ONE / Cinema Proof Agent

<!-- DSG.PICS-IP-WATERMARK:v1; token=DSG.PICS-IP-2026-V1; attribution=dsg.pics; third-party-licenses=preserved -->

> **© 2026 DSG.PICS · `DSG.PICS-IP-2026-V1` · Intellectual Property Attribution**  
> Original DSG-specific material is attributed to DSG.PICS. Third-party and open-source components remain under their respective licenses. See [`docs/INTELLECTUAL_PROPERTY_NOTICE.md`](docs/INTELLECTUAL_PROPERTY_NOTICE.md).

Deterministic governance and evidence runtime for AI-agent and automation execution.

DSG ONE / Cinema sits between an agent and real execution. Authentication establishes who is calling; approved plans, permissions, deterministic verification, and evidence determine what the caller is authorized to do. A valid credential does **not** grant authority outside the approved plan.

## Open the product

**Customer dashboard — primary production URL**

https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/dashboard

The normal customer workflow is intentionally centered on this single surface:

```text
/dashboard
   │
   ├─ Agent Chat
   ├─ Connect Agent
   ├─ Remote ON / OFF
   ├─ Shared Browser — one screen, User + Agent
   ├─ Inline plan approval
   │
   └─ LIVE MONITOR
        ├─ 1 ACTION
        ├─ 2 PLAN ALIGNMENT
        ├─ 3 PERMISSION
        ├─ 4 EVIDENCE
        └─ 5 EXECUTION / AUDIT
```

The customer should not need to move between `/app`, `/remote-browser/connect-agent`, Termux, raw MCP calls, plan IDs, or step IDs during the normal product flow. Those surfaces can remain available for compatibility, diagnostics, and advanced integration.

## Current production truth — verified 3 September 2026

| Item | Verified state |
|---|---|
| Production source commit | `d63b3bc72fb5ff37bef891cb0034a36934a9d5ae` — unified customer chat, shared browser, approval, and live monitor |
| Production deploy | GitHub Actions run `33726981587` / run #118 — **PASS** |
| Production evidence artifact | `9882548685` — `cinema-production-evidence-d63b3bc72fb5ff37bef891cb0034a36934a9d5ae` |
| Evidence artifact digest | `sha256:8512427cf6d118978aa21111bf3031930b08a7a8385f0ee898781bc5ad3351c5` |
| Cinema production | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| Customer dashboard | `https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/dashboard` |
| Verification MCP | `POST /api/v1/mcp` |
| Paired-agent Remote MCP | `POST /mcp` |
| Native Z3 backend | `https://dsg-z3-verifier-production.nicetree-a005fe99.westus3.azurecontainerapps.io` |
| Live contract | `/live/api/contract` |

The production workflow for this exact source commit completed successfully. It passed pre-deploy contract verification, Azure identity and runtime checks, immutable image build, native Z3 deployment and direct proof, Cinema deployment, Cinema → Z3 E2E plus deterministic replay, readiness/enforcement checks, marketplace/browser boundary checks, revenue-state verification, and non-secret evidence upload.

### What the current dashboard source includes

- **Agent Chat** — the browser sends user messages to a real paired MCP agent. Cinema does not fabricate agent replies.
- **Connect Agent in the dashboard** — normal pairing stays on `/dashboard`; users do not need the old helper page.
- **Shared Browser** — one browser session is presented as `One screen · User + Agent`.
- **Remote ON/OFF** — account-scoped remote authority remains explicit and revocable.
- **Inline approval** — approval uses the exact stored plan hash rather than a caller-invented verdict.
- **Five live monitor views** — ACTION, PLAN ALIGNMENT, PERMISSION, EVIDENCE, EXECUTION / AUDIT.
- **Advanced connection details** — MCP endpoint and short-lived pairing token remain available when a client must be configured manually, but are not the normal user journey.

## Customer flow

The intended product experience is:

```text
1. Open /dashboard
2. Connect or activate the DSG account
3. Connect the Agent from the same page
4. Talk to the Agent in Agent Chat
5. If approval is required, approve the exact plan in the conversation
6. User and Agent operate the same Shared Browser session
7. Watch the five live governance views update from runtime state
8. Review evidence and the execution/audit result
```

The UI must not manufacture green states. Before real runtime data arrives, monitor states remain pending, waiting, or not connected.

## Shared Browser: one screen, two actors

The design goal is a shared browser state with separate input actors:

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

User and Agent actions are distinguishable in the audit path. Agent actions remain plan-bound. The browser/login context can remain available to the user even when Remote authority for the Agent is disabled.

The system must not infer that possession of a browser session or credential equals authorization to execute an out-of-plan action.

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

Expected meanings:

| Result | Meaning |
|---|---|
| `ALLOW` | Action is aligned with the approved plan and required execution authority is present. |
| `WAITING_PERMISSION` | Plan alignment may be valid, but a required permission, capability, credential, or browser authority is not available yet. |
| `BLOCK` | Action is outside the approved plan, binding does not align, or another deterministic gate rejects it. |

`WAITING_PERMISSION` is not the same as plan rejection.

## Observe and Enforce

DSG separates the governance classification from its execution effect.

### OBSERVE — default evaluation mode

DSG records the decision, reason, evidence, and audit state without silently converting a policy `BLOCK` into `ALLOW`. Observe mode is intended for evaluation and integration where DSG should not automatically stop the customer's runtime.

### ENFORCE — explicit opt-in

When enforcement is enabled, the governance decision can affect execution. Approved actions can continue; out-of-plan or unauthorized actions can be stopped or held for permission.

Changing the mode changes execution effect, not the underlying governance classification.

## Authentication and remote authority

Customer protected surfaces use an account credential such as:

```http
X-DSG-API-Key: <customer DSG API key>
```

API-key authentication establishes account identity and entitlement; it does not bypass the approved plan.

Dashboard pairing uses short-lived credentials. The current dashboard connects through:

```text
POST /remote-browser/enable
POST /remote-browser/agent-pair
GET  /remote-browser/status
POST /remote-browser/disable
```

The master customer credential is not intended to be handed to the Agent as its long-lived remote credential. Pairing produces bounded session authority for the Agent path.

## MCP surfaces

See [`docs/API_V1_CONTRACT.md`](docs/API_V1_CONTRACT.md) for the DSG ONE v1 REST/MCP contract.

Cinema currently exposes two different MCP purposes. They should not be conflated.

### Verification / governance MCP

```text
POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/api/v1/mcp
```

This is the DSG ONE v1 governance/verification MCP surface and includes deterministic governance tools such as the exact selector.

### Paired-agent Remote MCP

```text
POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/mcp
```

This is the Remote Browser / paired-agent MCP surface. A plain `GET /mcp` is not the agent protocol test; Remote MCP uses JSON-RPC over `POST`.

The Remote MCP exposes the managed remote contract, status, agent connection, governed remote action, disconnect, and dashboard chat tools. Short-lived pairing authority is used for the Agent path instead of exposing the customer's master key.

## Dashboard chat contract

The dashboard chat is transport to a real paired Agent, not a fake local chatbot.

The browser-side customer flow uses dashboard APIs for:

```text
/dashboard/api/chat/messages
/dashboard/api/chat/approval
/dashboard/api/monitor
```

The Remote MCP Agent receives customer messages and can reply using MCP dashboard-chat tools. If no real Agent is connected, the UI waits; it does not synthesize an Agent response merely to make the demo look complete.

## Live Monitor

The five customer-facing views are:

1. **ACTION** — who acted (`USER` or `AGENT`), what action is occurring, target, and runtime state.
2. **PLAN ALIGNMENT** — whether the action matches the approved plan.
3. **PERMISSION** — whether required execution authority/capability is available.
4. **EVIDENCE** — observed proof inputs such as execution records, API responses, screenshots, hashes, and verification state.
5. **EXECUTION / AUDIT** — execution effect plus durable audit state.

Static HTML must not ship fabricated `PASS`, `SUCCESS`, or `VERIFIED` states before a real response exists.

## Replay boundary

Replay is **verification only**. It re-checks recorded inputs, evidence, hashes, and deterministic postconditions. Replay must not silently re-send the production action.

Historical replay evidence proves the recorded execution it refers to; it does not create a new production execution.

## Agent Plugin

The repository publishes the `dsg-governance` Agent Plugin through the `dsg-agent-plugins` marketplace.

Verified GitHub Copilot CLI install path:

```bash
copilot plugin marketplace add tdealer01-crypto/DSG-Cinema-Proof-Agent
copilot plugin marketplace browse dsg-agent-plugins
copilot plugin install dsg-governance@dsg-agent-plugins
```

Credentials remain client-managed and are not embedded in plugin source or README examples.

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

`/app` and `/remote-browser/connect-agent` can remain as advanced/compatibility surfaces, but they are not the normal customer entry point.

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
Plan alignment + permission + execution gates
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

## Deployment and CI

Canonical production workflow:

```text
.github/workflows/deploy-cinema-production.yml
```

The production run for source `d63b3bc72fb5ff37bef891cb0034a36934a9d5ae` completed **PASS** as run `33726981587` / #118.

The unified dashboard change was also covered by repository CI that exercises the customer one-page flow, paired-agent chat round-trip, exact-plan approval, five monitor states, Remote Browser transport, DSG ONE API contract, Python coverage gate, Z3 contract, production probe, plugin conformance, revenue checkout, and related integration checks.

Passing repository CI proves the tested contracts in that source revision. Production workflow success proves the deployment and production checks executed by that workflow. Neither should be restated as an external certification or independent audit.

## Truth boundary

DSG evidence supports only the scope actually tested.

A successful adapter, workflow, proof, deployment, or internal marketplace check does **not** mean an external marketplace, certification body, or independent auditor has approved DSG unless separate evidence says so.

Likewise, possession of a credential is not proof that an action is authorized. Execution remains subject to approved-plan binding, permission/capability state, deterministic gates, and evidence requirements.

## Repository

https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent
