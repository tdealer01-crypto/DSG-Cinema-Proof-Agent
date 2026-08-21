# DSG Governance — Agent Plugins 1.0 package

Portable Agent Plugins v1 package for using DSG ONE as an independent evidence and conformance plane around agent executions.

## Install from the DSG Agent Plugin marketplace

The repository exposes a GitHub Copilot plugin marketplace named `dsg-agent-plugins` from `.github/plugin/marketplace.json`.

```bash
copilot plugin marketplace add tdealer01-crypto/DSG-Cinema-Proof-Agent
copilot plugin marketplace browse dsg-agent-plugins
copilot plugin install dsg-governance@dsg-agent-plugins
```

These commands are covered by a real GitHub Copilot CLI client-install E2E on a GitHub-hosted runner. Authenticated agent-driven `dsg_status` is covered by a separate gated E2E and permanent evidence below.

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
| Copilot CLI agent authentication in CI | GitHub Actions run `32497793523` authenticated GitHub Copilot CLI `1.0.80` with the configured user-owned `COPILOT_CLI_TOKEN` before any DSG key was issued. Permanent evidence: `evidence/client/copilot-cli-mcp-auth-e2e-2026-08-21.json` | PASS |
| Copilot CLI authenticated DSG MCP `dsg_status` tool call | Run `32497793523` activated an ephemeral free DSG key only after Copilot auth, registered `dsg-one-auth`, independently verified authenticated `dsg_status = READY`, and then had the Copilot agent invoke `dsg_status` successfully. Credentials were not retained. Permanent evidence: `evidence/client/copilot-cli-mcp-auth-e2e-2026-08-21.json` | PASS |
| Copilot CLI full governed execution + proof receipt | A real Copilot CLI client has not yet completed create-plan → approval → alignment → constraints → execution → evidence → verify → proof readback as one stored client-conformance run | NOT VERIFIED |
| Other Agent Plugins clients | Must be tested client by client | NOT VERIFIED |

Package conformance is not client compatibility. A client row changes to PASS only when a real client run produces stored evidence for that exact surface.

## Authentication

The portable package deliberately contains no `X-DSG-API-Key` header. Store DSG credentials using the client/application's credential mechanism. Agent Plugins 1.0 does not define a portable secret-reference field for remote HTTP headers, so this package does not fake one.

For automated Copilot CLI agent/tool-call testing, the repository workflow expects a secret named `COPILOT_CLI_TOKEN`. It must be a user-owned fine-grained GitHub token with the **Copilot Requests** account permission. Do not put this token in the plugin package, repository files, issue comments, or workflow logs.

The workflow performs Copilot authentication before calling `/billing/activate`, so an unavailable Copilot credential does not create additional DSG free accounts. If authentication passes, the DSG API key is generated for that CI attempt, masked immediately, used only in the ephemeral runner, and not retained in artifacts.

## User-visible result

A useful integration must show, without requiring log inspection:

1. whether DSG returned ALLOW, REVIEW, BLOCK, or unavailable;
2. the specific reason;
3. receipt/proof identity when verified;
4. the remediation and next action when not verified;
5. billing/quota state without implying that Checkout creation itself granted access.

## Truth boundary

This directory is a portable package and CI target. The marketplace catalog is proven discoverable/installable by GitHub Copilot CLI `1.0.80`, and run `32497793523` proves authenticated agent-driven `dsg_status` against the Azure DSG MCP endpoint. A full governed execution through plan creation, approval, alignment, constraints, evidence, replay, exact Z3 verification, and proof-receipt readback from Copilot CLI is still not verified and must not be claimed PASS until that client E2E is stored as evidence.
