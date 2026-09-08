# DSG Spacetime Governance — Agent Plugins 1.0 package

**Plugin release:** `1.1.0`  
**Agent Plugins specification:** `1.0.0`

Portable Agent Plugins package for governing agent execution through DSG Spacetime. The package discovers approved capabilities, binds the user-authorized plan, executes only a licensed plan-bound Route through the configured customer-owned adapter, and verifies the resulting evidence.

## Install from the DSG Agent Plugin marketplace

This repository exposes the GitHub Copilot plugin marketplace `dsg-agent-plugins` from `.github/plugin/marketplace.json`.

```bash
copilot plugin marketplace add tdealer01-crypto/DSG-Cinema-Proof-Agent
copilot plugin marketplace browse dsg-agent-plugins
copilot plugin install dsg-governance@dsg-agent-plugins
```

Existing users can refresh and update with:

```bash
copilot plugin marketplace update dsg-agent-plugins
copilot plugin update dsg-governance
```

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

`plugin.json` targets Agent Plugins specification `1.0.0`. The plugin release is `1.1.0`. `mcp.json` declares the production DSG Spacetime MCP endpoint as Streamable HTTP. No credential is stored in the package; Agent Plugins 1.0 authorization is client-managed.

## Spacetime target

```text
https://dsg-spacetime-prod.greenglacier-493f3f71.westus3.azurecontainerapps.io
```

Portable MCP surface:

```text
POST /mcp
MCP protocol 2025-06-18
Bearer authentication via client-managed DSG_SPACETIME_API_KEY
```

Canonical tools:

```text
spacetime_discover
spacetime_compose
spacetime_execute
spacetime_verify_evidence
```

Governed path:

```text
Agent / application
        ↓
spacetime_discover
        ↓
spacetime_compose → BOUND + plan_hash
        ↓
spacetime_execute
        ↓
deployment + entitlement + plan + Route + approval/policy
        ↓
customer-owned adapter
        ↓
decision + result + evidence
        ↓
spacetime_verify_evidence
```

The plugin must not replace a Spacetime `BLOCK` with a direct provider call. DSG governance verifies plan alignment and execution prerequisites; it should not block an action merely because governance exists when the action is actually supported by the approved plan and available capability.

## Version 1.1.0 change

Version `1.1.0` moves the portable plugin from the legacy Cinema MCP integration to the current DSG Spacetime production contract:

- MCP server: `dsg-spacetime`
- endpoint path: `/mcp`
- canonical four Spacetime tools
- Spacetime plan binding and Route execution semantics
- marketplace/payment state kept separate from execution evidence

This is a plugin release change. The Agent Plugins specification remains `1.0.0`.

## Compatibility evidence

| Target | Current evidence | Status |
|---|---|---|
| Agent Plugins 1.0 package structure | Repository conformance checks validate manifest, MCP config, Skill frontmatter, HTTPS endpoint and absence of embedded credentials | CI-GATED |
| DSG marketplace catalog | `.github/plugin/marketplace.json` points to the portable package and keeps catalog/plugin versions aligned | CI-GATED |
| DSG Spacetime runtime contract | Canonical production repository records `/health`, `/mcp`, MCP `2025-06-18`, the four canonical tools, plan/Route fail-closed behavior, and bounded Azure production E2E | VERIFIED FOR RUNTIME SCOPE |
| Copilot CLI v1.0.0 package install | Historical GitHub Actions run `32482954936` installed `dsg-governance` v1.0.0 from this marketplace | PASS — HISTORICAL v1.0.0 |
| Copilot CLI v1.0.0 authenticated Cinema MCP status | Historical run `32497793523` | PASS — HISTORICAL v1.0.0 |
| Copilot CLI v1.0.0 full governed Cinema proof flow | Historical run `32499134400` | PASS — HISTORICAL v1.0.0 |
| Copilot CLI v1.1.0 install + Spacetime MCP | No exact v1.1.0 client run is stored yet | NOT VERIFIED |
| VS Code / Copilot app v1.1.0 | No exact v1.1.0 client run is stored yet | NOT VERIFIED |
| Other Agent Plugins clients | Must be tested client by client | NOT VERIFIED |

Package conformance, runtime proof, and client compatibility are separate claims. Historical v1.0.0 client runs do not prove v1.1.0 client compatibility.

## Authentication

The portable package deliberately contains no API key or Authorization header. Agent Plugins 1.0 does not define a portable secret-reference field for remote HTTP credentials. Store `DSG_SPACETIME_API_KEY` in the client/application credential mechanism and do not place it in plugin files, source control, evidence, logs, issue comments, or ordinary chat output.

## Revenue and entitlement boundary

The Spacetime plugin does not create purchases or grant entitlement. Marketplace/provider purchase and activation are separate flows. `spacetime_execute` checks the relevant deployment, entitlement, plan, Route and approval/policy state before the configured adapter can execute. A checkout redirect or caller assertion is not entitlement, and an execution result is not billing/payout evidence.

See `skills/dsg-governed-execution/references/revenue.md`.

## User-visible result

A useful integration must show, without requiring raw log inspection:

1. requested capability and selected approved Node/Route;
2. `BOUND` or `BLOCK` plan state;
3. execution `ALLOW` or `BLOCK` and exact reason;
4. actual adapter result separately from governance decision;
5. evidence verification state;
6. remediation/next action when blocked or not verified.

## Truth boundary

Version `1.1.0` is the repository marketplace package for the latest recorded DSG Spacetime production contract. The package and catalog update do not by themselves prove a real Copilot/VS Code client successfully authenticated to Spacetime or executed a Route. Those rows remain `NOT VERIFIED` until an exact v1.1.0 client run produces stored evidence.
