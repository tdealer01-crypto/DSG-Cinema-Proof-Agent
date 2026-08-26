# Shared Browser + Plan-Bound User Controller Delegation

## Product contract

One Cinema job uses one live browser session shared by three simultaneously connected actors:

1. **User** — interactive provider live view; may click/type at any time.
2. **Agent executor** — plan-bound mutations (`agent_executor`).
3. **Agent verifier** — read-only extract/screenshot controller (`agent_verifier`).

There is no browser ownership handoff and no takeover state. The remote browser provider/executor must serialize only colliding low-level input while keeping the same tabs, cookies, login state, URL and DOM visible to all actors.

## Optional user-controller delegation

An agent does not receive identity-input authority by default. The authority can exist only when it is encoded in the human-approved `PlanStep.parameters`, and therefore covered by the approved plan hash.

Example approved step parameters:

```json
{
  "user_controller_shared": true,
  "user_controller_operations": "identity.secret.inject,identity.otp.submit,identity.confirmation.click",
  "user_controller_origins": "https://dashboard.stripe.com"
}
```

The runtime derives the delegation from the approved plan during remote-session creation. A client cannot widen the delegation at connect/action time.

Delegated identity operations use `controller: "user_delegated"`.

### Secret injection

```json
{
  "kind": "identity.secret.inject",
  "controller": "user_delegated",
  "parameters": {
    "origin": "https://dashboard.stripe.com",
    "target": "input[name=password]",
    "secret_ref": "vault://stripe/account-password"
  }
}
```

### OTP submission

```json
{
  "kind": "identity.otp.submit",
  "controller": "user_delegated",
  "parameters": {
    "origin": "https://dashboard.stripe.com",
    "target": "input[autocomplete=one-time-code]",
    "otp_ref": "otp://stripe/current-login"
  }
}
```

The opaque reference is resolved by the trusted browser executor or credential broker. The model, MCP request, Cinema durable evidence and ordinary application logs must never contain the plaintext secret/OTP value.

## Hard invariants

- No delegation unless it is present in the approved plan step.
- Delegation is restricted to the exact approved operation set and HTTPS origins.
- `agent_verifier` is read-only (`browser.extract`, `browser.screenshot`).
- `agent_executor` cannot perform delegated identity operations.
- Plaintext password/passcode/OTP/API-key/private-key/security-key/MFA values remain rejected in remote action payloads.
- CAPTCHA and passkey remain direct-user-only.
- Explicit authorization/security/audit bypass requests remain hard blocked.
- `Remote OFF` revokes ordinary agent authority and delegated user-controller authority without terminating the user's browser session.

## Evidence

Every dispatched action records:

- `plan_id`
- `plan_hash`
- `step_id`
- `agent_identity`
- `controller`
- normalized `actor` (`AGENT_EXECUTOR`, `AGENT_VERIFIER`, `AGENT_VIA_USER_CONTROLLER`)
- action kind/parameters
- remote response hash
- canonical evidence hash

`secret_ref` and `otp_ref` are SHA-256 transformed before durable evidence is written. Plaintext identity values are never accepted, so there is nothing sensitive to redact after dispatch.

## Provider/executor responsibilities

Cinema remains the governance/control plane. The Browserbase/remote-browser executor is responsible for:

- maintaining one shared browser session for user + both agent controllers;
- exposing the interactive user live view for that same session;
- resolving opaque secret/OTP references inside a trusted boundary;
- injecting resolved values directly into the intended element without returning them;
- preventing secret values from appearing in logs, screenshots metadata or action responses;
- serializing only colliding pointer/keyboard actions while allowing read-only verification in parallel;
- returning deterministic action results/evidence references to Cinema.

## User-visible UX

Normal users should see only:

`Goal -> Plan -> Approve -> Running -> Success -> Evidence`

Secret binding, environment provisioning, browser provider/session creation, MCP transport and retries remain internal runtime details. Missing credentials or unavailable browser infrastructure fail closed and surface as a concise blocked prerequisite, never a mock success.
