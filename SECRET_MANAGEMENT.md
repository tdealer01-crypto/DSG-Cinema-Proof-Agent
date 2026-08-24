# Secret Management

Not every secret in this system wants the same treatment. Two are regenerated
on every deployment and never persist; the Stripe and operator credentials are
long-lived and externally issued. Mixing those up makes the system weaker, not
stronger, so they are handled differently on purpose.

## The inventory

| Secret | Lifetime | Stored where | Rotation |
|---|---|---|---|
| `DSG_SOLVER_SHARED_SECRET` (Z3 ↔ Cinema) | one deployment | Container App secret only | automatic, every deploy |
| `CINEMA_API_SECRET` (Cinema `/solve`) | one deployment | Container App secret only | automatic, every deploy |
| `DSG_REVENUE_ADMIN_SECRET` | long-lived | GitHub repository secret | manual |
| `STRIPE_SECRET_KEY` | long-lived, issued by Stripe | **Key Vault** (or repo secret) | manual, via Stripe |
| `STRIPE_WEBHOOK_SECRET` | long-lived, issued by Stripe | **Key Vault** (or repo secret) | manual, via Stripe |
| `STRIPE_APP_SIGNING_SECRET` | long-lived, issued after Apps upload | **Key Vault** (or repo secret) | manual, via Stripe Apps |
| `STRIPE_APP_OAUTH_{TEST,SANDBOX}_SECRET_KEY` | long-lived, mode-specific | **Key Vault** (or repo secret) | manual, via Stripe |
| `STRIPE_APP_OAUTH_{TEST,SANDBOX}_AUTHORIZE_URL` | external-test invite capability | **Key Vault** (or repo secret) | replace with each test link |
| Customer API keys | long-lived | SHA-256 hash only, never the value | reissue |

The first two are the strongest case in the system: `openssl rand -hex 32` on
every deployment, injected as a Container App secret, masked in logs, and never
written anywhere durable. Vaulting them would convert a value that lives for one
deployment into one that lives until someone rotates it — strictly worse.

## Why Stripe keys are different

| | Per-deployment secrets | Stripe keys |
|---|---|---|
| Who issues them | this deployment | Stripe |
| Can be regenerated per deploy | yes | no |
| Blast radius if leaked | next deploy replaces it | money moves |
| Needs "who read this, when" | no | yes |

That difference is the whole reason Key Vault is in this repository, and the
reason nothing else is kept there.

## Enabling Key Vault

```bash
export STRIPE_SECRET_KEY='sk_live_…'      # optional; seeds the vault
export STRIPE_WEBHOOK_SECRET='whsec_…'    # optional; seeds the vault
./AZURE_BOOTSTRAP_KEY_VAULT.sh
```

The script creates an RBAC-authorized vault with soft delete and purge
protection, grants the Container App's existing pull identity **Key Vault
Secrets User** (read-only on secret values, nothing else), and seeds the two
secrets without printing them.

Then set one repository variable:

```
DSG_KEY_VAULT_NAME = dsg-cinema-kv
```

The deployment then wires the app with Key Vault references:

```
--secrets "stripe-secret-key=keyvaultref:https://<vault>/secrets/stripe-secret-key,identityref:<identity>"
--env-vars STRIPE_SECRET_KEY=secretref:stripe-secret-key
```

Container Apps resolves the reference through the managed identity at runtime,
so **the live key never passes through GitHub Actions at all**. No application
code changes: `revenue/stripe_sync.py` still just reads the environment.

After the variable is set, delete the `STRIPE_SECRET_KEY` and
`STRIPE_WEBHOOK_SECRET` repository secrets. Leaving copies behind keeps a second
place the key can leak from.

The bootstrap script seeds only the billing key and webhook secret. Add Stripe
App signing, mode-specific OAuth keys, and external-test authorize URLs to Key
Vault separately, then point the corresponding
`DSG_KEY_VAULT_STRIPE_APP_*_NAME` variables at those secret names. Public app
IDs, OAuth client IDs, and the live public authorize URL remain repository
variables; External Test URLs do not.

## Resolution order

1. `DSG_KEY_VAULT_NAME` set → Key Vault references (preferred)
2. Otherwise repository secrets, if present → passed as Container App secrets
3. Neither → **Stripe stays unlinked.** `/billing/status` keeps reporting
   `NOT_VERIFIED_NOT_LINKED`, and unsigned webhooks are refused with 503 rather
   than trusted.

Possessing a secret is never treated as proof that charging works:
`charges_enabled` and `webhooks_enabled` stay false until live Stripe
verification passes. A configured credential only moves `configured` and
`webhooks_configured`.

## Zero-downtime credential rotation

Z3 and Cinema share `DSG_SOLVER_SHARED_SECRET` but deploy in separate steps.
Without care, requests in flight between those steps fail authorization against
a credential that is correct but one revision old.

The deployment therefore opens a rotation window:

1. Read the credential the running Z3 currently uses.
2. Deploy Z3 with the new value as `DSG_SOLVER_SHARED_SECRET` **and** the old
   one as `DSG_SOLVER_PREVIOUS_SECRET`, so both are accepted.
3. Deploy Cinema on the new value.
4. Verify the E2E, then revoke the previous credential and confirm
   `rotation_in_progress` is back to `false`.

`z3_main.accepted_secrets()` compares every candidate even after a match, so
response time cannot reveal which credential matched or how many are configured.
A blank previous value is normalized away and can never widen authorization.

The window lasts one deployment. Step 4 runs only after the E2E proves the new
credential works, and it fails the deployment if the revocation does not take
effect — so a second valid credential is never left live.

## Truth boundary

**Supported and tested:**

- Per-deployment credentials never persist outside the running app.
- Customer API keys are stored only as SHA-256 hashes.
- The rotation window accepts exactly two credentials, closes within one
  deployment, and is verified closed.
- Missing Stripe configuration fails closed rather than half-configuring.

**Not claimed:**

- **Key Vault is not enabled by default.** Until `DSG_KEY_VAULT_NAME` is set and
  `AZURE_BOOTSTRAP_KEY_VAULT.sh` has run against the subscription, Stripe
  credentials come from repository secrets or are absent.
- No HSM-backed keys (the vault is standard tier), no customer-managed keys, and
  no automatic Stripe key rotation — Stripe issues those, so rotation is manual.
- No independent audit of the secret handling described here.
