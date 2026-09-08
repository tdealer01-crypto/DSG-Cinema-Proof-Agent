# DSG Spacetime Revenue and Entitlement Boundary

The Agent Plugin governs execution through DSG Spacetime. It does not embed billing credentials, create purchases, or grant marketplace entitlement.

## Separation of concerns

```text
Agent Plugin / MCP
        ↓
spacetime_discover
        ↓
spacetime_compose
        ↓
spacetime_execute
        ↓
plan + Route + deployment + entitlement + approval/policy checks
        ↓
customer-owned adapter
        ↓
result + evidence
```

Marketplace/provider purchase, subscription, billing, and entitlement activation occur outside this plugin through the provider's supported user flow.

## What the plugin must do

When Spacetime refuses execution because deployment, entitlement, Route, approval/policy, or identity is missing:

- show the exact refusal reason/code;
- show the returned remediation or next required action when present;
- do not call the external provider directly as a fallback;
- do not create a purchase automatically;
- do not treat a checkout URL, browser redirect, client assertion, or pending provider state as entitlement;
- retry only after the required provider/runtime state is actually available.

## Credentials

Store `DSG_SPACETIME_API_KEY` only in the client/application credential mechanism. Never place it in `plugin.json`, `mcp.json`, `SKILL.md`, source control, evidence, logs, or ordinary chat output.

## Evidence boundary

A successful payment or marketplace activation is not evidence that an agent action executed. Conversely, an execution receipt is not evidence of marketplace billing or payout. Keep provider-commercial evidence and execution evidence as separate proof domains.
