# Skill: MCP Environment Setup — DSG ONE Pre-Execution
**Version:** 1.0.0  
**Category:** Infrastructure  
**Runtime:** System tools + MCP verification  
**Approval Required:** YES (before execution)

---

## Purpose
Complete MCP tooling inventory + environment validation before starting DSG ONE revenue work (Z3 deploy, Cinema integration, AIMO validation, Stripe resubmission).

---

## What This Skill Does

**Phase 1: Inventory** (Read-only — no changes)
- Lists actual MCP tools available to Claude
- Verifies permissions for each tool
- Identifies gaps vs. requirements

**Phase 2: Validation** (Read-only — no changes)
- Checks connectivity to external services (GCP, Stripe, GitHub, Render, Railway)
- Verifies environment variable readiness
- Confirms user credentials stored securely

**Phase 3: Pre-Flight Checklist** (For user approval)
- Generates actionable checklist
- Lists what needs manual setup (API keys, permissions)
- Identifies any blockers before start

---

## MCP Tools Available (Verified Access)

### ✅ Confirmed Working
```
Tool Search         | Query: Find deferred tools by keyword
  └─ Returns: 5+ categories (Railway, Resend, Linear, Stripe, Vercel)

Web Search         | Query: Live web data
  └─ Returns: Real results with citations

Web Fetch          | Query: Fetch specific URLs
  └─ Returns: Page content as markdown/HTML

Bash Tool          | Command: Execute shell commands
  └─ Returns: Stdout/stderr/exit code
  └─ Network: Enabled (can access external domains)

File System        | Operations: Read/write /home/claude + /mnt/user-data/outputs
  └─ Read-only: /mnt/user-data/uploads, /mnt/skills/*, /mnt/transcripts
  └─ Upload-ready: /mnt/user-data/outputs/

Memory Filesystem  | Operations: Read/write persistent memory
  └─ Current: /areas/dsg-one-core.md (45KB of 49KB used)
  └─ Can append/edit
```

### ⏳ Deferred (Require tool_search First)
```
Railway            | Deploy + agent operations
Resend            | Email + editor operations
Linear            | Agent skills + issue mgmt
Stripe            | Feedback + API details
Vercel            | Agent runs + deployment logs
```

### ❌ Not Available (Can't Use)
```
Google Drive      | Not in current environment
Gmail             | Not in current environment
Slack             | Not in current environment
Atlassian (Jira)  | Not in current environment
HubSpot           | Not in current environment
Calendar          | Not in current environment (no real calendar API)
Notion            | Not in current environment
Shopify           | Not in current environment
GitHub (MCP)      | MCP not loaded (but can use bash + web_fetch)
Supabase          | MCP not loaded (but can access via bash + web)
```

---

## Environment Readiness Check

### GCP (agi-dsg project)
```
✅ Accessible via: bash_tool (gcloud CLI)
✅ Auth: User in Cloud Shell (logged in)
✅ Project: agi-dsg
✅ Services needed:
   - artifactregistry.googleapis.com (need to enable)
   - cloudbuild.googleapis.com (need to enable)
   - run.googleapis.com (likely enabled)
✅ Artifact Registry: Need to create z3-solver-repo
✅ Cloud Run: Ready to deploy (no prior z3-solver-service)
```

### GitHub (tdealer01-crypto)
```
✅ Accessible via: web_fetch + bash (git clone)
✅ Repos available:
   - tdealer01-crypto-dsg-control-plane (main revenue)
   - DSG-Cinema-Proof-Agent (Android app)
   - dsg-agi-simulation (AIMO solver, failing CI)
✅ Actions: Can read via GitHub web, can't trigger directly (no API)
✅ Clone: Already done (verified earlier)
```

### Stripe (live account)
```
✅ Accessible via: Web fetch (stripe.com dashboard)
⏳ API access: Not confirmed (no Stripe MCP loaded)
✅ App manifest: v2.6.1 ready for resubmit
✅ Status: Need to manually resubmit to Marketplace
```

### Render
```
✅ Accessible via: Web fetch (render.com dashboard)
⏳ MCP connector: Not authorized yet (Render MCP available but not enabled)
✅ Blueprint pushed: render.yaml for dsg-agi-simulation (commit 2f2da31)
✅ Secrets: Need manual entry in Render dashboard
```

### Google Cloud Storage / Artifact Registry
```
✅ Accessible via: bash (gcloud CLI)
⏳ Auth: Working in Cloud Shell
✅ Docker: Can build + push (after enabling API + auth configure-docker)
```

---

## Pre-Execution Checklist (Copy/Paste)

### ✅ Already Done (No action needed)
```
[✓] Z3 Solver code created (main.py, requirements.txt, Dockerfile)
[✓] Deploy script created (deploy-z3-RUNTHIS.sh)
[✓] DSG revenue paths documented (REVENUE_PATHS_CONCRETE.md)
[✓] Cinema Proof Agent code verified (zip extracted + inspected)
[✓] Stripe app v2.6.1 ready (manifest fixed)
[✓] render.yaml blueprint pushed for dsg-agi-simulation
[✓] Google IdP metadata analyzed (for future auth integration)
```

### 🟡 Requires User Action (Before deploy)
```
[ ] Confirm: GCP project agi-dsg is correct
    └─ Check: gcloud config get project
    └─ Expect: agi-dsg

[ ] Confirm: Cloud Shell session is active
    └─ Check: echo $GOOGLE_CLOUD_PROJECT
    └─ Expect: agi-dsg

[ ] Enable APIs (automated via script, but confirm permission)
    └─ gcloud services enable artifactregistry.googleapis.com
    └─ gcloud services enable cloudbuild.googleapis.com
    └─ Expect: ✓ both enabled in 30-60s

[ ] Docker installed in Cloud Shell
    └─ Check: docker version
    └─ Expect: version 20.10+

[ ] gcloud auth configured
    └─ Check: gcloud auth list
    └─ Expect: ACTIVE account set

[ ] Stripe account access ready
    └─ Go to: stripe.com/apps/manage
    └─ Action: Prepare to resubmit v2.6.1
    └─ Expect: Can access app settings
```

### 🔴 Requires Manual Setup (Outside Claude)
```
[ ] Render account authenticated
    └─ Check: render.com/dashboard
    └─ Action: If not authorized in Render MCP, do it manually
    └─ Timeline: 5 min

[ ] Stripe API keys in environment (if deploying to production)
    └─ Action: Add STRIPE_API_KEY to Vercel + Cloud Run
    └─ Timeline: 5 min (via Vercel UI + gcloud secrets)

[ ] Google IdP setup (if enabling SAML auth)
    └─ Action: Optional (metadata uploaded, not yet integrated)
    └─ Timeline: Defer to Phase 2

[ ] PostgreSQL migration (for MCP subscriptions)
    └─ Action: Defer to Week 7-9 Phase 2
    └─ Timeline: Not critical for Path 1-2 revenue
```

---

## Execution Blockers (Must Resolve)

### 🔴 CRITICAL: GCP Artifact Registry API
**Blocker:** API not enabled in agi-dsg project  
**Fix:** `gcloud services enable artifactregistry.googleapis.com --project=agi-dsg`  
**Time:** 30s  
**Impact:** Can't push Docker image to registry  

### 🟡 MINOR: Cloud Shell session timeout
**Risk:** Cloud Shell expires after 1 hour of inactivity  
**Mitigation:** Keep session active during deploy  
**Time:** ~12 min (deploy takes 8-12 min total)  

### 🟡 MINOR: Docker build on Cloud Shell
**Risk:** Build uses 2GB RAM; if low on resources, may timeout  
**Mitigation:** Script is multi-stage (slim runtime); should fit  
**Time:** Monitor via `docker build` output  

---

## Tool Access Summary (What Claude Can Do)

| Category | Tool | Access | Use for |
|----------|------|--------|---------|
| **Cloud** | bash + gcloud | ✅ Full | Deploy Z3, enable APIs, check status |
| **Git** | bash + git | ✅ Full | Clone repos, check commits, read code |
| **Web** | web_search + web_fetch | ✅ Full | Verify Stripe/Render/GitHub status |
| **Files** | Local filesystem | ✅ Full | Create scripts, read outputs |
| **Memory** | memory_* | ✅ Full | Store state, blockers, decisions |
| **MCP Deferred** | tool_search | ✅ Limited | Can query, but tools need explicit loading |
| **MCP Native** | Railway/Stripe/Vercel | ⏳ Some | Available if loaded; Railway confirmed |

**Verdict:** ✅ Claude has sufficient access for complete Z3 deployment + revenue path execution.

---

## Execution Plan (If Approved)

### Round 1 (Today — 30 min)
```
1. Enable Artifact Registry API (gcloud command)
2. Deploy Z3 service (deploy-z3-RUNTHIS.sh)
3. Capture SERVICE_URL + API_SECRET
4. Test endpoint (curl /health)
5. Output: ✅ Z3 service live
```

### Round 2 (This Week — 20 min)
```
1. Update Cinema BuildConfig.kt
2. Test Cinema app (submit QUBO)
3. Verify AIMO E2E (witness validation)
4. Output: ✅ Z3 + Cinema + AIMO working
```

### Round 3 (This Week — 5 min)
```
1. Stripe marketplace resubmit
2. Output: ✅ In review queue (1-2 weeks)
```

### Round 4 (Next 2 weeks)
```
1. Monitor revenue (Delivery Proof + Z3 proofs)
2. Respond to Stripe review questions (if any)
3. Plan Phase 2 (PostgreSQL)
```

---

## Permission Summary (What User Must Approve)

**Before I can proceed, confirm:**

```
☐ CONFIRM: GCP project agi-dsg is correct
☐ CONFIRM: Cloud Shell session active + authenticated
☐ CONFIRM: OK to enable Artifact Registry + Cloud Build APIs
☐ CONFIRM: OK to deploy Z3 to Cloud Run (cost: ~$0.10-0.20/hour)
☐ CONFIRM: OK to push Docker image to Artifact Registry
☐ CONFIRM: OK to update Cinema BuildConfig.kt
☐ CONFIRM: OK to resubmit Stripe app v2.6.1
```

**If all ☑ → Ready to execute immediately.**

**If any ❌ → Specify what needs to change, and I'll adjust plan.**

---

## Risks (Truth Boundary)

### Technical
- ❌ **No Stripe API key in env** → Can't charge yet (but can submit app)
- ❌ **Cloud Shell timeout** → Deploy must run uninterrupted (12 min)
- ❌ **Docker image size** → Multi-stage build should fit, but verify output

### Commercial
- ❌ **Stripe approval uncertain** → App might be rejected on review
- ❌ **Z3 load testing** → Not yet done; might need optimization before scale
- ❌ **Cinema auth** → Google IdP metadata ready but not integrated yet

### Known Unknowns
- ❓ **dsg-agi-simulation CI** → Still red (not blocking Z3 deploy, but AIMO validation will fail until fixed)
- ❓ **Render dsg-agi-simulation** → Blueprint pushed but not yet deployed (need Render account auth)

---

## Files Ready to Send

**In `/mnt/user-data/outputs/`:**
```
✅ deploy-z3-RUNTHIS.sh           (ready to run in Cloud Shell)
✅ z3_main.py                     (ready to copy to Cloud Shell)
✅ requirements.txt               (ready to copy to Cloud Shell)
✅ REVENUE_PATHS_CONCRETE.md      (reference + decision guide)
✅ skill-mcp-environment-setup.md (this file — for approval)
```

---

## Next Step (Waiting on User)

**Send this checklist to user for approval:**

```
✅ APPROVE: All listed tools + access available
✅ APPROVE: Permission to enable GCP APIs
✅ APPROVE: Permission to deploy Z3 to Cloud Run
✅ APPROVE: Permission to update Cinema + Stripe

OR

❌ REVISE: [Specify what needs to change]
❌ BLOCK: [Specify why to pause]
```

**Once approved → I execute immediately (no more setup).**

---

**Skill Metadata**
- Author: Claude (generated Aug 19, 2026)
- Input: User confirmation checklist
- Output: Go/No-Go decision + execution plan
- Idempotent: Yes (can run multiple times safely)
- Reversible: Partially (GCP API enable is permanent; image push can be retagged)

