# DSG Governance — Agent Plugins 1.0 package

Portable Agent Plugins v1 package for using DSG ONE as an independent evidence and conformance plane around agent executions.

## Package contents

```text
marketplace/agent-plugin/
├── plugin.json
├── mcp.json
└── skills/
    └── dsg-governed-execution/
        ├── SKILL.md
        └── references/
            └── revenue.md
```

`plugin.json` targets Agent Plugins 1.0.0. `mcp.json` declares the production DSG MCP endpoint as `streamable-http`. No credentials are stored in the package; Agent Plugins v1 authorization is client-managed.

## What it does

The skill drives this evidence path:

```text
Agent/App
  → raw approved plan
  → DSG plan hash + approval binding
  → plan-alignment verification
  → deterministic constraints + exact Z3
  → agent executes the approved action
  → execution record + real evidence
  → replay/evidence verification
  → proof receipt
```

The plugin does **not** turn DSG into another autonomous agent platform. It gives an existing agent a portable path into DSG's independent policy/evidence layer.

## Revenue path

```text
Plugin discovery
  → free activation (25 verified proofs, hard cap)
  → governed executions
  → quota/payment remediation
  → user-initiated Stripe Checkout
  → signed scoped webhook entitlement
  → proof-bound metering
  → usage ledger + Stripe meter sync
```

Checkout creation never grants entitlement. The existing DSG signed Stripe webhook is the paid-entitlement boundary.

## Compatibility evidence

| Target | Current evidence | Status |
|---|---|---|
| Agent Plugins v1 package structure | Repository conformance test validates manifest, MCP config, Skill frontmatter, HTTPS endpoint, and absence of embedded credentials | CI-GATED |
| DSG MCP protocol contract | Existing API tests exercise `initialize`, `tools/list`, tool calls, refusal handling, and no caller-supplied verdicts | CI-GATED |
| DSG execution semantics | Existing API tests cover approved execution, out-of-plan BLOCK, replay REVIEW, deterministic constraints, and fail-closed verifier behavior | CI-GATED |
| VS Code / GitHub Copilot client install | No real client run is stored in this repository yet | NOT VERIFIED |
| Copilot CLI client install | No real client run is stored in this repository yet | NOT VERIFIED |
| Other Agent Plugins clients | Must be tested client by client | NOT VERIFIED |

Package conformance is not client compatibility. Do not change a client row to PASS until an actual install/connect/tool-call run produces stored evidence.

## Authentication

The portable package deliberately contains no `X-DSG-API-Key` header. Store DSG credentials using the client/application's credential mechanism. If a client cannot attach the required authorization to the remote MCP connection, metered tool calls are not proven compatible with that client.

## User-visible result

A useful integration must show, without requiring log inspection:

1. whether DSG returned ALLOW, REVIEW, BLOCK, or unavailable;
2. the specific reason;
3. receipt/proof identity when verified;
4. the remediation and next action when not verified;
5. billing/quota state without implying that Checkout creation itself granted access.

## Truth boundary

This directory is a portable package and CI target. It is not evidence that every Agent Plugins client can install it. Client compatibility remains a separate end-to-end test surface.
