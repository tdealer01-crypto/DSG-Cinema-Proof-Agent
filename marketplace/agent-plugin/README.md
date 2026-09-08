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

## Authentication — client credential binding is required

The portable package deliberately contains no API key or Authorization header. Agent Plugins 1.0 treats configured remote HTTP headers as visible package data, does not expand secret placeholders in them, and defines no portable OAuth or credential-reference field. DSG Spacetime production currently requires `Authorization: Bearer <DSG_SPACETIME_API_KEY>`.

Therefore **plugin installation and authenticated MCP use are separate gates**. Installation may succeed while the plugin-declared remote server remains unauthorized until the client binds a credential.

Use the client application's own protected MCP credential mechanism. For GitHub Copilot CLI, the native MCP configuration supports a remote HTTP server plus an `Authorization` header. Prefer the interactive `/mcp` dashboard so the secret is not copied into repository files. If a client cannot attach a protected credential to the plugin-declared entry, configure the same Spacetime endpoint as a client-native authenticated MCP entry and keep that credential outside the plugin package.

A non-interactive Copilot CLI form also exists, but using it can place a token in shell history, so use it only in a trusted environment:

```bash
copilot mcp add --transport http \
  --header "Authorization: Bearer <DSG_SPACETIME_API_KEY>" \
  dsg-spacetime-auth \
  https://dsg-spacetime-prod.greenglacier-493f3f71.westus3.azurecontainerapps.io/mcp
```

Do not commit a real key, paste it into issue/PR comments, store it in evidence, or print it in shared logs. Until an exact v1.1.0 authenticated client tool call is stored, authentication compatibility remains `NOT VERIFIED` even when package installation passes.

## Compatibility evidence

| Target | Current evidence | Status |
|---|---|---|
| Agent Plugins 1.0 package structure | Repository conformance checks validate manifest, MCP config, Skill frontmatter, HTTPS endpoint and absence of embedded credentials | CI-GATED |
| DSG marketplace catalog | `.github/plugin/marketplace.json` points to the portable package and keeps catalog/plugin versions aligned | CI-GATED |
| DSG Spacetime runtime contract | Canonical production repository records `/health`, `/mcp`, MCP `2025-06-18`, the four canonical tools, plan/Route fail-closed behavior, and bounded Azure production E2E | VERIFIED FOR RUNTIME SCOPE |
| Copilot CLI — plugin v1.0.0 package install | Historical GitHub Actions run `32482954936` installed `dsg-governance` v1.0.0 from this marketplace | PASS — HISTORICAL v1.0.0 |
| Copilot CLI — plugin v1.0.0 authenticated Cinema MCP status | Historical run `32497793523` | PASS — HISTORICAL v1.0.0 |
| Copilot CLI — plugin v1.0.0 full governed Cinema proof flow | Historical run `32499134400` | PASS — HISTORICAL v1.0.0 |
| Copilot CLI — plugin v1.1.0 exact package install | PR workflow must install the checked-out marketplace/package rather than default-branch cache | CI-GATED |
| Copilot CLI — plugin v1.1.0 authenticated Spacetime MCP tool call | Requires client-managed Bearer credential; no exact stored v1.1.0 tool-call proof yet | NOT VERIFIED |
| VS Code / Copilot app — plugin v1.1.0 | No exact v1.1.0 client run is stored yet | NOT VERIFIED |
| Other Agent Plugins clients | Must be tested client by client | NOT VERIFIED |

Package conformance, runtime proof, package-install compatibility, and authenticated tool compatibility are separate claims. Historical v1.0.0 client runs do not prove v1.1.0 client compatibility.

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

Version `1.1.0` is the repository marketplace package for the latest recorded DSG Spacetime production contract. A successful package/catalog check does not by itself prove authenticated Spacetime execution. The authenticated v1.1.0 client row remains `NOT VERIFIED` until a real client binds a protected credential and successfully calls the Spacetime MCP surface with stored evidence.
