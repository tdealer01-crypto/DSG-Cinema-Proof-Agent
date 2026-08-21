# DSG Governance — Agent Plugins 1.0 package

Portable Agent Plugins v1 package for using DSG ONE as an independent evidence and conformance plane around agent executions.

## Install from the DSG Agent Plugin marketplace

The repository exposes a GitHub Copilot plugin marketplace named `dsg-agent-plugins` from `.github/plugin/marketplace.json`.

```bash
copilot plugin marketplace add tdealer01-crypto/DSG-Cinema-Proof-Agent
copilot plugin marketplace browse dsg-agent-plugins
copilot plugin install dsg-governance@dsg-agent-plugins
```

These commands are now covered by a real GitHub Copilot CLI client-install E2E on a GitHub-hosted runner. That client-install proof does not by itself prove authenticated DSG MCP tool calls; MCP authorization remains tracked separately below.

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
| DSG Copilot marketplace catalog | Repository conformance test validates `.github/plugin/marketplace.json`, the `dsg-governance` source path, version alignment, and strict loading | CI-GATED |
| DSG MCP protocol contract | Existing API tests exercise `initialize`, `tools/list`, tool calls, refusal handling, and no caller-supplied verdicts | CI-GATED |
| DSG execution semantics | Existing API tests cover approved execution, out-of-plan BLOCK, replay REVIEW, deterministic constraints, and fail-closed verifier behavior | CI-GATED |
| VS Code / GitHub Copilot client install | No real client run is stored in this repository yet | NOT VERIFIED |
| Copilot CLI client install | GitHub Actions run `32482954936` used GitHub Copilot CLI `1.0.80` to add `dsg-agent-plugins`, browse it, install `dsg-governance@dsg-agent-plugins`, and confirm plugin `v1.0.0` in the installed-plugin list. Permanent evidence: `evidence/client/copilot-cli-plugin-e2e-2026-08-21.json` | PASS |
| Copilot CLI authenticated DSG MCP tool call | The install run deliberately did not supply a DSG API key or claim an authenticated remote MCP call | NOT VERIFIED |
| Other Agent Plugins clients | Must be tested client by client | NOT VERIFIED |

Package conformance is not client compatibility. A client row changes to PASS only when a real client run produces stored evidence for that exact surface.

## Authentication

The portable package deliberately contains no `X-DSG-API-Key` header. Store DSG credentials using the client/application's credential mechanism. Agent Plugins 1.0 does not define a portable secret-reference field for remote HTTP headers, so this package does not fake one.

If a client cannot attach the required authorization to the remote MCP connection, metered tool calls are not proven compatible with that client.

## User-visible result

A useful integration must show, without requiring log inspection:

1. whether DSG returned ALLOW, REVIEW, BLOCK, or unavailable;
2. the specific reason;
3. receipt/proof identity when verified;
4. the remediation and next action when not verified;
5. billing/quota state without implying that Checkout creation itself granted access.

## Truth boundary

This directory is a portable package and CI target. The marketplace catalog is now proven discoverable/installable by GitHub Copilot CLI `1.0.80`, but that does not prove every client can authenticate to DSG or complete metered governed execution. Authenticated MCP/tool-call compatibility remains a separate end-to-end test surface.
