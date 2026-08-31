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

## DSG Live first

For a governed task, start the customer-visible monitor automatically before the first action:

1. Call `dsg_status`. Continue only when the verification backend is ready.
2. Call `dsg_live_start` once for this task. It starts in `OBSERVE` mode and returns a `monitor_url` plus a temporary `live_session_token`.
3. Give the user the `monitor_url`. Do not print the token separately, place it in logs, or persist it in project files.
4. Keep the token only for this live task. Before every proposed action, call `dsg_live_check_action` with that token and a stable `trace_id` that will also be used when the actual execution is recorded.
5. Always follow `live.execution_instruction` from the server session:
   - `CONTINUE`: DSG is observing only. The governance classification remains visible but DSG does not stop the customer runtime.
   - `EXECUTE`: Enforce Mode authorized this exact action.
   - `WAIT`: the action is plan-authorized but a required capability is not available yet.
   - `STOP`: Enforce Mode denied execution for the current governance state.
6. The user changes `OBSERVE` / `ENFORCE` from the DSG Live monitor. The agent must not invent a mode or replace the server-returned instruction.

`OBSERVE` is not an ALLOW claim. An observed action may still show `OUTSIDE_PLAN` or `MISSING_PERMISSION`; the separate DSG EFFECT panel explains that DSG did not stop it.

## Verification workflow

1. Call `dsg_create_plan` with the raw plan that the user or operator intends to authorize. Preserve the returned `plan_id` and DSG-computed `plan_hash`.
2. Obtain the required approval outside this skill, then call `dsg_approve_plan` using the exact `plan_hash` that DSG returned. Never substitute a different hash.
3. Before execution, use `dsg_live_check_action` for the exact proposed action. It uses the same unified DSG decision core as the direct preflight control surface.
4. Call `dsg_verify_constraints` with the policy constraints and observed facts when the task has deterministic constraints. Treat verifier unavailability as a refusal, not as ALLOW.
5. The executing agent or application follows the server-returned Live instruction. This skill does not create permission for an out-of-plan action.
6. Call `dsg_record_execution` with what actually happened, including the same stable `trace_id`, step identifiers, targets, parameters, output digests when available, environment, and cost. Record observed reality even when Observe Mode showed a governance problem; evidence must not be deleted to make the run look compliant.
7. Call `dsg_submit_evidence` with the real evidence artifacts. Never fabricate artifact content or a digest.
8. Call `dsg_verify_execution`. DSG recomputes plan alignment, deterministic constraints, evidence completeness, and replay match, and requires exact Z3 verification before issuing a proof receipt.
9. Call `dsg_get_proof` to read the stored receipt and DSG's recomputation of its receipt hash.
10. `dsg_live_status` may be used to read the same customer-visible event/evidence state for the current Live session.

## Result language

Keep governance result separate from execution effect:

- `PASS`: the proposed action matches the approved plan and required capability is available.
- `OUTSIDE_PLAN`: DSG computed that the proposed action differs from the approved plan.
- `MISSING_PERMISSION`: the action is plan-authorized but required server capability is not available.
- `BLOCKED`: another governance prerequisite such as plan approval or agent identity failed.
- `OBSERVE / CONTINUE`: DSG recorded the result but did not stop the customer runtime.
- `ENFORCE / EXECUTE | WAIT | STOP`: DSG returned the instruction that the governed integration must follow.

Final execution language remains receipt-bound:

- `ALLOW`: the bounded execution passed the checks represented by the verified receipt.
- `BLOCK`: the execution was unsupported by the approved plan or violated deterministic constraints.
- `REVIEW`: execution, evidence, or replay information is incomplete or inconsistent and needs review.

Keep the evidence boundary explicit. A DSG receipt proves the deterministic verification recorded for that bounded execution. It is not by itself a SOC 2, ISO, legal, regulatory, or third-party certification.

## Evidence states

Keep these concepts separate when explaining results:

- `CLAIMED`: supplied by an agent or caller and not yet independently demonstrated.
- `OBSERVED`: backed by submitted execution records or evidence artifacts.
- `PROVED`: recomputed by DSG and bound to a verified proof receipt.

Do not upgrade a CLAIMED fact to OBSERVED or PROVED without the corresponding evidence. DSG Live shows `UNVERIFIED` or `PENDING` until the stored records justify a stronger state.

## Replay boundary

Replay in DSG Live is verification only. DSG compares the recorded output digest with content-verified evidence and recomputes the proof path. It never sends the action again, re-runs production, refunds again, deploys again, or creates another side effect.

If the user wants to run the workflow again, use the monitor's Copy history output as input to the user's own test environment. Do not turn that into a DSG execution-replay feature.

## Billing and conversion

The plugin package never embeds API keys or payment credentials. Agent Plugins v1 leaves authorization and credential storage to the client.

If a metered verification is refused for quota or payment state, surface the server's `remediation.problem`, `remediation.cause`, and `remediation.next_step` to the user. A payment flow must be explicitly initiated by the user through DSG's self-serve checkout; completing a browser redirect is not proof of entitlement. DSG changes paid entitlement only after its signed, catalog-scoped Stripe webhook accepts the subscription event.

Free activation and checkout details are in `references/revenue.md`.

## Fail-closed rules

- Never invent an approval, evidence artifact, hash, execution outcome, or proof receipt.
- Never send `plan_aligned`, `constraints_pass`, `verified`, `decision`, or similar verdict fields as caller assertions when the tool schema does not accept them.
- Never interpret an unavailable MCP server, unavailable verifier, invalid response, or missing receipt as ALLOW.
- Never expose a DSG API key or DSG Live session token in plugin package files, logs, evidence, or ordinary chat text.
- Never bypass an explicit user or operator approval step.
- Never claim compatibility with a client solely because the package validates. Compatibility must be backed by a real client conformance run.

## What the user should see

The Live monitor keeps five separate panels tied to the same latest event:

1. `LIVE ACTION` — what the agent/customer runtime is doing.
2. `PLAN CHECK` — PASS, OUTSIDE_PLAN, MISSING_PERMISSION, or BLOCKED.
3. `DSG EFFECT` — Observe/Enforce and the actual CONTINUE/EXECUTE/WAIT/STOP effect.
4. `WHY` — the deterministic reason/code returned by DSG.
5. `EVIDENCE` — stored execution, evidence completeness, verification-only replay, and proof state.

Always make the next action obvious and never make the user read raw logs to understand whether a result is verified.
