---
name: dsg-governed-execution
description: Verify whether an agent execution stayed inside an approved plan, satisfied deterministic constraints, produced complete evidence, and replayed consistently through DSG ONE. Use when an agent action needs an auditable ALLOW, REVIEW, or BLOCK result backed by a proof receipt.
compatibility: Requires an Agent Plugins v1 client with MCP Streamable HTTP support and network access to the configured DSG ONE MCP endpoint. Metered verification can require client-managed DSG credentials.
metadata:
  author: DSG ONE
  version: "1.0.0"
---

# DSG Governed Execution

Use DSG as an independent evidence and conformance plane around an agent's work. Do not ask DSG to invent the agent's result and do not treat a connection failure as approval.

## Workflow

1. Call `dsg_status`. Continue only when the verification backend is ready.
2. Call `dsg_create_plan` with the raw plan that the user or operator intends to authorize. Preserve the returned `plan_id` and DSG-computed `plan_hash`.
3. Obtain the required approval outside this skill, then call `dsg_approve_plan` using the exact `plan_hash` that DSG returned. Never substitute a different hash.
4. Before execution, call `dsg_verify_plan_alignment` with the approved plan and proposed actions. DSG computes alignment; do not supply a verdict field.
5. Call `dsg_verify_constraints` with the policy constraints and observed facts. Treat verifier unavailability as a refusal, not as ALLOW.
6. The executing agent or application performs only actions that are authorized by the approved plan. This skill governs and records work; it does not create permission for an out-of-plan action.
7. Call `dsg_record_execution` with what actually happened, including stable step identifiers, targets, parameters, output digests when available, environment, and cost.
8. Call `dsg_submit_evidence` with the real evidence artifacts. Never fabricate artifact content or a digest.
9. Call `dsg_verify_execution`. DSG recomputes plan alignment, deterministic constraints, evidence completeness, and replay match, and requires exact Z3 verification before issuing a proof receipt.
10. Call `dsg_get_proof` to read the stored receipt and DSG's recomputation of its receipt hash.

## Result language

Report the result in operational terms:

- `ALLOW`: the bounded execution passed the checks represented by the receipt.
- `BLOCK`: the action was unsupported by the approved plan or violated deterministic constraints.
- `REVIEW`: execution, evidence, or replay information is incomplete or inconsistent and needs review.

Keep the evidence boundary explicit. A DSG receipt proves the deterministic verification recorded for that bounded execution. It is not by itself a SOC 2, ISO, legal, regulatory, or third-party certification.

## Evidence states

Keep these concepts separate when explaining results:

- `CLAIMED`: supplied by an agent or caller and not yet independently demonstrated.
- `OBSERVED`: backed by submitted execution records or evidence artifacts.
- `PROVED`: recomputed by DSG and bound to a verified proof receipt.

Do not upgrade a CLAIMED fact to OBSERVED or PROVED without the corresponding evidence.

## Billing and conversion

The plugin package never embeds API keys or payment credentials. Agent Plugins v1 leaves authorization and credential storage to the client.

If a metered verification is refused for quota or payment state, surface the server's `remediation.problem`, `remediation.cause`, and `remediation.next_step` to the user. A payment flow must be explicitly initiated by the user through DSG's self-serve checkout; completing a browser redirect is not proof of entitlement. DSG changes paid entitlement only after its signed, catalog-scoped Stripe webhook accepts the subscription event.

Free activation and checkout details are in `references/revenue.md`.

## Fail-closed rules

- Never invent an approval, evidence artifact, hash, execution outcome, or proof receipt.
- Never send `plan_aligned`, `constraints_pass`, `verified`, `decision`, or similar verdict fields as caller assertions when the tool schema does not accept them.
- Never interpret an unavailable MCP server, unavailable verifier, invalid response, or missing receipt as ALLOW.
- Never expose a DSG API key in plugin package files, logs, evidence, or chat output.
- Never bypass an explicit user or operator approval step.
- Never claim compatibility with a client solely because the package validates. Compatibility must be backed by a real client conformance run.

## What the user should see

Always make the next action obvious:

1. What DSG decided: ALLOW, REVIEW, BLOCK, or unavailable.
2. Why: the specific alignment, constraint, evidence, replay, or configuration finding.
3. Evidence: proof id/hash and receipt verification state when a receipt exists.
4. What to fix: the concrete remediation returned by DSG when the flow did not pass.
