---
name: dsg-governed-execution
description: Govern an AI agent action through DSG Spacetime by discovering approved capabilities, binding the proposed plan, executing only a licensed plan-bound Route, and verifying the resulting evidence. Use when an agent action needs an auditable ALLOW or BLOCK result without bypassing the user-approved plan.
compatibility: Requires an Agent Plugins 1.0 client with MCP Streamable HTTP support, network access to the configured DSG Spacetime MCP endpoint, and client-managed DSG_SPACETIME_API_KEY credentials when the runtime requires authentication.
metadata:
  author: DSG ONE
  version: "1.1.0"
---

# DSG Governed Execution

Use DSG Spacetime as the execution boundary around an agent's real work. DSG must verify alignment with the approved plan, enforce Route and entitlement constraints, and retain evidence. It must not invent the result and a connection failure is never approval.

## Canonical Spacetime workflow

1. Call `spacetime_discover` with the capability the task actually needs. Use only Nodes returned as customer-approved for that capability.
2. Build the proposed N2N plan from the user's authorized intent and call `spacetime_compose`.
3. Continue only when compose returns a bound plan. Preserve the exact returned `plan_id`, `plan_hash`, and Route identifiers. Treat `BLOCK` or an unbound result as a refusal requiring remediation.
4. Call `spacetime_execute` for exactly one Route from the bound plan. Supply the exact `plan_id`, `plan_hash`, Route, agent identity, and payload representing the intended action.
5. Do not perform the governed external side effect separately around DSG. The Spacetime execution path is responsible for checking deployment, entitlement, plan, Route, approval/policy, then invoking the configured customer-owned adapter when authorized.
6. Read the returned decision, adapter result, and evidence as separate fields. A claimed agent result is not evidence by itself.
7. Call `spacetime_verify_evidence` after execution and require the evidence chain to verify before describing the run as verified.

## Decision handling

- `ALLOW`: the bounded Route passed the checks represented by the returned Spacetime execution and the configured adapter was allowed to run.
- `BLOCK`: execution was refused. Surface the exact reason/code and the required remediation; do not bypass it with a direct external call.
- unavailable / malformed response / verifier failure: treat as not verified and do not convert it to ALLOW.

A plan-authorized action should not be blocked merely because governance is present. DSG should deny only when the action is unsupported by the bound plan, Route, entitlement, approval/policy, identity, or other verified execution prerequisite.

## Evidence states

Keep these concepts separate:

- `CLAIMED`: supplied by an agent or caller and not independently demonstrated.
- `OBSERVED`: backed by the execution result or stored evidence produced by the governed path.
- `VERIFIED`: the Spacetime evidence chain verifies for the bounded execution.

Never upgrade CLAIMED information to OBSERVED or VERIFIED without the corresponding runtime evidence.

## Authentication and secrets

The plugin package contains no API key. Store `DSG_SPACETIME_API_KEY` using the client/application credential mechanism and send it only through the supported authenticated MCP transport. Never place credentials in `plugin.json`, `mcp.json`, `SKILL.md`, source control, evidence artifacts, logs, or ordinary chat text.

## Billing and entitlement

The Spacetime MCP plugin does not create purchases or grant entitlement. Marketplace/provider activation and payment are separate user/provider flows. If `spacetime_execute` refuses because deployment, entitlement, Route, or approval/policy is missing, surface the returned reason and next required action. Do not retry through an ungoverned path and do not treat a checkout redirect or client assertion as entitlement.

See `references/revenue.md` for this boundary.

## Fail-closed rules

- Never invent approval, plan hashes, Route IDs, evidence, execution outcomes, or verification results.
- Never substitute a different `plan_hash` or Route after `spacetime_compose` binds the plan.
- Never call the external provider directly as a fallback after `spacetime_execute` blocks or fails.
- Never interpret an unavailable MCP server, invalid response, missing entitlement, missing adapter, or failed evidence verification as ALLOW.
- Never expose DSG credentials in plugin files, logs, evidence, or chat.
- Never claim compatibility with a client solely because the package validates. Client compatibility requires a real client run for that exact plugin version and endpoint.

## What the user should see

For each governed action, present:

1. the requested capability and selected approved Node/Route;
2. whether the plan was `BOUND` or `BLOCK`;
3. the execution decision (`ALLOW` or `BLOCK`) and exact reason;
4. the actual adapter result separately from the decision;
5. whether evidence verification passed;
6. the next action when anything is blocked or not verified.

Do not make the user inspect raw logs to know whether the action ran, why it was blocked, or whether evidence verified.
