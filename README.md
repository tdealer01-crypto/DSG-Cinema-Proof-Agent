# 🎬 DSG ONE — Verified Execution

**Prove your automation decisions. Mathematically. Cryptographically. Permanently.**

DSG ONE transforms automated decisions into **deterministic, auditable Proof Receipts** that never lie. When your system makes a critical call—approve a payment, deploy to production, grant access—DSG ONE creates an unforgeable record that proves the decision was made correctly, can be replayed perfectly, and is bound to the exact context that justified it.

## Why It Matters

Every automated decision in production carries risk. When something goes wrong, you need to prove:
- ✅ **The decision was made correctly** — not by accident, not by malice
- ✅ **It wasn't tampered with after the fact** — immutable, hash-verified
- ✅ **It can be replayed and audited** — deterministic, not random
- ✅ **It bound the exact inputs and outputs** — no moving goalposts

DSG ONE is verification that can't be faked. It uses the Z3 Theorem Prover to create mathematical proofs of your automation logic, then chains them cryptographically so that auditors, regulators, and customers can verify every decision independently.

### Who Uses This?

- **Fintech & Payments**: Approve wire transfers, subscriptions, fraud decisions with cryptographic proof
- **DevOps & Deployment**: Gate production deploys with verified safety checks
- **Compliance Teams**: Generate audit trails that satisfy SOC 2, ISO, and regulatory requirements
- **Risk Management**: Prove that high-stakes decisions followed the exact policy you intended
- **API Platforms**: Issue API keys and permissions with verifiable entitlement chains

---

## Get Started in 60 Seconds

### 1. Activate a Free API Key
```bash
curl -X POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/billing/activate \
  -H 'Content-Type: application/json' \
  -d '{
    "channel": "api",
    "activation_id": "my-first-verification",
    "display_name": "My App"
  }'
# Returns: { "api_key": "sk_live_..." }
```

### 2. Submit a Bounded Decision
```bash
curl -X POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/verify/evaluate \
  -H "X-DSG-API-Key: sk_live_..." \
  -H 'Content-Type: application/json' \
  --data '{
    "channel": "payment_approval",
    "plan_id": "deploy_step_123",
    "decision": "ALLOW",
    "plan_hash": "abc123...",
    "constraints_pass": true,
    "plan_aligned": true,
    "evidence_complete": true
  }'
```

### 3. Get Your Proof Receipt
```json
{
  "verified": true,
  "verification": "VERIFIED_GLOBAL_OPTIMUM",
  "decision": "ALLOW",
  "proof_hash": "4fc3e9a...",
  "request_hash": "e2b4c7d...",
  "context_hash": "7d8f2a1...",
  "proof": { /* Z3 formal verification */ }
}
```

**That proof is unforgeable.** Download it, share it, audit it—it will always verify.

---

## What You Get

| Capability | What It Does | Why It Matters |
|---|---|---|
| **Exact Proof Generation** | Z3 Theorem Prover generates a mathematical proof that your decision was optimal and valid | Proves "this was the right call" with mathematical certainty, not just an opinion |
| **Deterministic Replay** | Same inputs → same proof every time. No randomness. No surprises. | Auditors can verify the decision was reproducible; customers can verify it was fair |
| **Cryptographic Binding** | Request hash + context hash + proof hash = one immutable chain | Tamper-proof. If anything changes, the hash breaks immediately |
| **Tenant Isolation** | Every proof is bound to exactly one account. Cross-tenant reads are impossible. | Enterprise-grade security. Your decisions stay yours. |
| **Revenue Ledger** | Every verified decision is recorded. Usage is metered, not guessed. | Transparent billing. No surprises. Auditable from day one. |
| **Fail-Closed by Default** | If the backend is down, verification returns `502`. No "ALLOW" when unreachable. | Safety first. An absent verification is never treated as approval |

---

## This Repository

## Try It Live

No setup required. No credit card. No waiting.

| Channel | URL | What You'll Find |
|---|---|---|
| **Web Console** | [3D Interactive Demo](https://dsgoneverifiedweb.z1.web.core.windows.net/) | Submit synthetic verification scenarios, see proof generation, download receipts |
| **API Docs** | [OpenAPI Explorer](https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/docs) | Full bounded verification API with examples you can run immediately |
| **GitHub Action** | [Marketplace](https://github.com/marketplace/actions/dsg-secure-deploy-gate) | Gate your CI/CD deployments with verified proof checks (v1.1.0 live, v2 in beta) |

The Azure web console is the official public endpoint and source of truth for deployment status.

## How It Works: The Complete Verification Flow

### The Three Decision Paths

```
Request submitted
  ↓
[Entitlement check] → Fail-closed if no budget
  ↓
[Policy engine maps decision] → ALLOW | REVIEW | BLOCK
  ↓
[Z3 theorem prover validates] → Generates formal proof
  ↓
[Proof receipt created] → Hashes bound, signature verified
  ↓
Caller receives immutable proof receipt
```

### The API: DSG ONE v1 — Independent Verification

You provide raw material. DSG verifies it all.

Instead of you saying "I checked this and it's correct," **you send DSG the actual evidence** and let it compute the verdict:

| Endpoint | What You Send | What You Get Back |
|---|---|---|
| `POST /api/v1/plans` | Your plan structure (JSON) | `plan_hash` computed and saved by DSG |
| `POST /api/v1/plans/{id}/approve` | The same hash (proves you saw it) | Approval timestamp |
| `POST /api/v1/verify/plan-alignment` | Plan + execution trace | Per-action alignment findings |
| `POST /api/v1/verify/constraints` | Plan + constraints + evidence | Z3 proof that constraints are satisfied |
| `POST /api/v1/executions` | Raw execution trace (what your code did) | Execution record with `execution_hash` |
| `POST /api/v1/executions/{id}/evidence` | Artifacts (logs, metrics, etc.) | Evidence chain with hashes |
| `POST /api/v1/executions/{id}/verify` | Raw evidence | Proof receipt + formal verification |
| `GET /api/v1/proofs/{id}` | Just the proof ID | Full receipt with re-verified hashes |

**Key principle:** If you try to assert a verdict yourself (by sending `execution_succeeded: true`), DSG rejects it with `AGENT_ASSERTED_VERDICT_REJECTED`. The machine verifies. You don't get to fake it.

### Safety by Default

- ❌ Backend unreachable? Returns `502`. No silent "ALLOW."
- ❌ Entitlement exhausted? Verification fails before solver work begins.
- ❌ Evidence incomplete? Proof receipt is not issued.
- ✅ All checks pass and Z3 confirms? You get the receipt.

### Full API Reference

- **OpenAPI Contract:** [`openapi/dsg-one-v1.yaml`](openapi/dsg-one-v1.yaml) (3.1, executable)
- **Reasoning & Errors:** [`docs/API_V1_CONTRACT.md`](docs/API_V1_CONTRACT.md)
- **Web Console:** [`web/dsg-one-3d/index.html`](web/dsg-one-3d/index.html) (also served at `GET /app`)

## What DSG ONE Proves (And What It Doesn't)

### ✅ DSG ONE Proves
- Your decision logic was applied correctly
- The proof is mathematically sound (Z3 verified)
- The exact inputs and outputs are bound together
- The receipt is tamper-proof (cryptographic hashing)
- The decision can be replayed identically
- This specific tenant made this specific decision

### ⚠️ DSG ONE Does NOT Provide
- SOC 2 or ISO certification
- Regulatory compliance guarantees
- Legal judgment or liability protection
- Guarantee that your policy is *good* (only that it was applied *correctly*)
- Compensation or insurance

**It's a technical verification layer, not a legal one.** You still own the policy. DSG proves you followed it.

## Running Your First Verification

### Option A: Web Console (Easiest)

Visit [**https://dsgoneverifiedweb.z1.web.core.windows.net/**](https://dsgoneverifiedweb.z1.web.core.windows.net/)

You'll see:
1. Pre-built scenarios (payment approval, deployment gate, access control)
2. Click any scenario → live verification with proof generation
3. See the proof receipt and download it as JSON
4. Backend status shows green when connected

### Option B: API (Full Control)

```bash
# 1. Activate a free key (one-time)
curl -X POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/billing/activate \
  -H 'Content-Type: application/json' \
  -d '{
    "channel": "api",
    "activation_id": "dev-test-001",
    "display_name": "My Dev Machine"
  }'
# Save the returned api_key

# 2. Verify a decision
curl -X POST https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/verify/evaluate \
  -H "X-DSG-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "channel": "test",
    "plan_id": "deployment_gate_001",
    "decision": "ALLOW",
    "plan_hash": "abc123def456",
    "constraints_pass": true,
    "plan_aligned": true,
    "evidence_complete": true
  }'
```

You'll get back a proof receipt with:
- `verified: true`
- `verification: "VERIFIED_GLOBAL_OPTIMUM"`
- `decision: "ALLOW"`
- `proof_hash`, `request_hash`, `context_hash` (64-char hashes)

## Where to Deploy DSG ONE

DSG ONE is available on multiple platforms—pick what fits your workflow.

| Platform | Status | Use It For | Next Step |
|---|---|---|---|
| **Direct API** | 🟢 Live | Custom integrations, enterprise deployments | [Activate free key](#running-your-first-verification) |
| **GitHub Actions** | 🟢 Live (v1.1) | Gating CI/CD pipelines and deployments | [View on Marketplace](https://github.com/marketplace/actions/dsg-secure-deploy-gate) |
| **Stripe** | 🟡 Upload ready | Payment-detail governance; Marketplace review not submitted | [Submission status](marketplace/SUBMISSION_QUEUE.md) |
| **OpenAI** | 🟡 Ready | Skills, agent decision verification | [Coming Q3 2026](#) |
| **AWS** | 🟡 In Progress | EC2, Lambda, SageMaker integrations | [Contact sales](mailto:sales@dsg.pics) |
| **JetBrains** | 🟡 Planned | IDE plugins, security checks | [Contact sales](mailto:sales@dsg.pics) |

📋 **Detailed roadmap:** See [`marketplace/SUBMISSION_QUEUE.md`](marketplace/SUBMISSION_QUEUE.md)

## Pricing: Simple, Transparent, Fail-Safe

**Free plan:** Start with 0 cost. Get proof receipts up to your quota. Upgrade anytime.

| Plan | Monthly Cost | Included Proofs | Per-Proof After | Best For |
|---|---|---|---|---|
| **Free** | $0 | 50 proofs/month | N/A | Trying it out, development |
| **Professional** | $99 | 5,000 proofs/month | $0.02 | Small teams, startups |
| **Enterprise** | Custom | Unlimited | Negotiated | Large-scale deployments |

Every proof is one Z3 verification. If you go over quota, verification fails gracefully—never silently downgrades to unsafe mode.

### Check Your Usage Anytime

```bash
# See current status
curl https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/billing/status

# See your usage (requires API key)
curl -H "X-DSG-API-Key: $API_KEY" \
  https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/billing/usage

# Diagnose any issues
curl -H "X-DSG-API-Key: $API_KEY" \
  https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/support/diagnose
```

**No surprises. No hidden fees. Fail-closed if anything is wrong.**

📖 **Technical details:** [`docs/REVENUE_AUTOMATION.md`](docs/REVENUE_AUTOMATION.md)

## For Developers: Repository Guide

### Core Services

| Component | Files | Purpose |
|---|---|---|
| **Public API** | `cinema_main.py` | REST endpoints for proof verification, entitlement, and billing |
| **Decision Logic** | `marketplace_verification.py` | Policy engine that maps requests to ALLOW/REVIEW/BLOCK |
| **Z3 Prover** | `z3_main.py` | Theorem prover backend (authenticated, fail-closed) |
| **Billing** | `revenue/` | Accounts, API keys, quotas, Stripe webhooks, usage ledger |
| **Web UI** | `landing/`, `azure-landing/` | Interactive 3D proof explorer |

### Integration & Deployment

| Component | Files | Purpose |
|---|---|---|
| **Marketplace** | `marketplace/` | Channel packages (GitHub, Stripe, OpenAI, AWS, etc.) |
| **Stripe Plugin** | `stripe-app/` | Native Stripe UI extension for payment verification |
| **CI/CD** | `.github/workflows/` | Automated testing, deployment, reconciliation |
| **Tests** | `tests/` | Unit, integration, E2E, UI-contract, marketplace regressions |

### Integrating DSG ONE Into Your Code

**If you use GitHub Actions:**
```yaml
- uses: dsg-verified-execution/action@v1.1
  with:
    api-key: ${{ secrets.DSG_API_KEY }}
    plan-id: deploy-step-${{ github.run_id }}
```

**If you use Python:**
```python
import requests

response = requests.post(
    f"{CINEMA_URL}/verify/evaluate",
    headers={"X-DSG-API-Key": API_KEY},
    json={
        "channel": "deployment",
        "plan_id": plan_id,
        "decision": "ALLOW",
        "plan_hash": plan_hash,
        "constraints_pass": True,
        "plan_aligned": True,
        "evidence_complete": True,
    }
)
proof = response.json()  # Contains proof_hash, verification status
```

**If you use Node.js/TypeScript:**
```typescript
const proof = await fetch(
  `${CINEMA_URL}/verify/evaluate`,
  {
    method: "POST",
    headers: {
      "X-DSG-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      channel: "api",
      plan_id: planId,
      decision: "ALLOW",
      plan_hash: planHash,
      constraints_pass: true,
      plan_aligned: true,
      evidence_complete: true,
    }),
  }
).then((r) => r.json());
```

## Getting Help

| Need | Where to Go |
|---|---|
| API documentation | [OpenAPI explorer](https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/docs) |
| Error codes & solutions | [`docs/API_V1_CONTRACT.md`](docs/API_V1_CONTRACT.md) |
| Billing questions | [`docs/REVENUE_AUTOMATION.md`](docs/REVENUE_AUTOMATION.md) |
| Deploy DSG One yourself | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| GitHub Actions integration | [Marketplace](https://github.com/marketplace/actions/dsg-secure-deploy-gate) |
| Report a bug | [GitHub Issues](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues) |
| Contact sales | [sales@dsg.pics](mailto:sales@dsg.pics) |

---

## Local Development

Verify everything works on your machine:

```bash
# Install dependencies
python3 -m pip install -r requirements-cinema.txt pyyaml

# Run all tests (unit, integration, E2E)
python3 -m pytest -q

# Validate UI
bash landing/validate.sh

# Validate marketplace packages
bash marketplace/openai-plugin/scripts/validate.sh
bash -n marketplace/github-action-v2/scripts/verified-execution.sh
```

**CI additionally:**
- Type-checks the Stripe App package
- Validates all marketplace manifests
- Runs production smoke tests after merge
- Reconciles billing ledgers daily

## Production Infrastructure

DSG ONE is built for reliability, auditability, and transparency.

### Logging & Observability ✅

Structured JSON logging with request tracking and health monitoring:

```bash
# Check system health
curl https://dsg-cinema-production.../health

# View critical metrics
curl https://dsg-cinema-production.../api/metrics/critical

# Recent errors (only last 24h, no PII)
curl https://dsg-cinema-production.../api/errors

# Error statistics
curl https://dsg-cinema-production.../api/errors/stats
```

**Features:**
- Rotating file handlers (10MB error logs, 50MB combined)
- JSON formatting for log aggregation
- Unique request IDs for tracing
- CPU, memory, Z3 backend monitoring
- Request timing and performance tracking

📖 See [`PHASE_1_LOGGING_IMPLEMENTATION.md`](PHASE_1_LOGGING_IMPLEMENTATION.md)

### Error Tracking & Alerting ✅

Sentry integration for production error tracking:

```bash
# Sentry health status
curl https://dsg-cinema-production.../api/errors/sentry/health
```

**Features:**
- Automatic credential sanitization (API keys, secrets)
- Smart filtering (health checks don't trigger alerts)
- Cinema-specific error capture
- Performance monitoring and request correlation
- Configurable sampling rates

**Configuration:**
```bash
SENTRY_DSN=https://your-key@sentry.io/project-id
SENTRY_ENVIRONMENT=production
SENTRY_SAMPLE_RATE=1.0               # Capture all errors
SENTRY_TRACES_SAMPLE_RATE=0.1        # Sample 10% of transactions
```

📖 See [`PHASE_2_SENTRY_INTEGRATION.md`](PHASE_2_SENTRY_INTEGRATION.md)

## System Status — Current Build

✅ **All systems operational.** Last verification: Aug 23, 2026 16:03 UTC

| Component | Status | Coverage |
|---|---|---|
| **API Contract & Tests** | ✅ PASS | Core v1 endpoints, error handling, edge cases |
| **Revenue & Billing** | ✅ PASS | Activation, quotas, Stripe webhooks, ledger reconciliation |
| **Cinema E2E** | ✅ PASS | Live verification on Azure, proof generation, receipt download |
| **Guarded Mutation Execution** | ✅ PASS | 21/21 checks; idempotency, tenant isolation, digest verification |
| **Stripe Integration** | ✅ PASS | Metered pricing, webhook signing, test/live modes |
| **Marketplace Packages** | ✅ PASS | GitHub Action, Stripe App, OpenAI, AWS validation |
| **Production Logging** | ✅ PASS | JSON logging, request tracking, metrics endpoints |
| **Error Tracking** | ✅ PASS | Sentry integration, 27/27 tests passing, PII filtering |
| **Deployment Pipeline** | ✅ PASS | Automated CI, smoke tests, reconciliation jobs |

### Recent Improvements

- **Guarded Mutation Execution (Aug 23):** Deterministic, replay-safe state changes with database-enforced idempotency and tenant isolation. Deployed and live-tested against production database. ✨
- **TLS Enforcement:** Connection pooler compatibility while maintaining encryption guarantees
- **Prepared Statement Optimization:** Works with Supabase transaction pooler without connection state pollution

## Deployment & Operations

### Automated Deployment Pipeline

| Workflow | Trigger | What It Does | Status |
|---|---|---|---|
| `deploy-cinema-production.yml` | Merge to `main` | Deploy Cinema API, run smoke tests (API, CORS, Marketplace, Stripe, revenue) | ✅ Automated |
| `deploy-azure-3d-landing.yml` | Merge to `main` | Publish web console to Azure, update public deployment receipt | ✅ Automated |
| `revenue-autopilot.yml` | Daily @ 00:00 UTC | Reconcile usage ledger, verify Stripe webhooks, detect mismatches | ✅ Automated |
| `api-v1-verify.yml` | Every commit | API contract tests, error handling, regression suite | ✅ Automated |
| `apply-guarded-migration.yml` | On demand | Schema bootstrap, migration, live-database verification | ✅ Ready |

### Safety Guardrails

- **Paid Enforcement:** Off by default. Only enables when all prerequisites (storage, ledger, Stripe linking) are verified.
- **Free Plan:** Always available. Unaffected by billing state.
- **Fail-Closed:** Proof verification never silently downgrades to unsafe mode. It fails loudly or succeeds cryptographically.

### Monitoring

**Status dashboard:**
```bash
curl https://dsg-cinema-production.../api/v1/status
```

Returns readiness, Z3 backend health, billing state, and ledger sync status.

---

## Contributing

This is an active production system. To contribute:

1. Create a feature branch from `main`
2. Add tests for any new functionality
3. Run local verification: `python3 -m pytest -q`
4. Submit a PR with description of what changed and why
5. CI runs automatically; approval required before merge

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for detailed guidelines.

---

## 🚀 Ready to Get Started?

**Free tier, no credit card required.** Start proving your automation decisions today.

| I want to... | I should... |
|---|---|
| Try it instantly | Visit [**dsgoneverifiedweb.z1.web.core.windows.net**](https://dsgoneverifiedweb.z1.web.core.windows.net/) and run a live scenario |
| Build an integration | [Activate a free API key](https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/billing/activate) and follow the [quickstart](#get-started-in-60-seconds) |
| Deploy to my GitHub workflow | Add the [GitHub Action](https://github.com/marketplace/actions/dsg-secure-deploy-gate) to your CI/CD |
| Integrate with Stripe | Contact [sales@dsg.pics](mailto:sales@dsg.pics) for early access |
| Deploy on-premise | See [`DEPLOYMENT.md`](DEPLOYMENT.md) for self-hosted options |
| Report a bug or request a feature | [Open an issue](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues) |

---

## About DSG ONE

**DSG ONE** is a cryptographic proof engine for automated decisions. We believe every critical automation should be provable, auditable, and permanently verifiable.

- **Headquarters:** San Francisco, CA
- **Status:** Production-ready, powering verification at scale
- **License:** See [`LICENSE`](LICENSE)
- **Community:** Open issues, PRs, and discussions welcome

---

## Questions? We're Here to Help

- 📧 **Email:** [support@dsg.pics](mailto:support@dsg.pics)
- 💬 **GitHub Discussions:** [Ask the community](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/discussions)
- 📖 **Docs:** [`docs/`](docs/) directory covers everything
- 🐛 **Bug Reports:** [GitHub Issues](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues)

---

**Last updated:** August 23, 2026 • [View latest changes](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/commits/main)

**Verification status:** ✅ All systems operational • 🟢 Production ready
