# Cinema + Z3 Integration - Complete Implementation Guide

**Status:** Ready to implement
**Timeline:** 20 minutes
**Tools:** Bash script OR Python script (cross-platform)

---

## 🎯 What This Does

Connects the **Cinema Proof Agent** (already deployed on Azure) to the **Z3 Solver Service** (just deployed) so that:

```
User Request
    ↓
Cinema generates proof
    ↓
Cinema calls Z3 /solve endpoint  ← [NEW]
    ↓
Z3 returns verified QUBO solution + proof hash  ← [NEW]
    ↓
Cinema includes Z3 verification in proof
    ↓
$99 "Z3 Verified Execution" proof delivered
```

**Revenue Impact:** +$1,980/month (20 proofs @ $99)

---

## 📋 Prerequisites Checklist

Before starting, verify you have:

```
☐ Z3 Solver deployed and running
☐ Z3 SERVICE_URL (e.g., http://z3-solver-service.westus3.azurecontainer.io:8080)
☐ Z3 API_SECRET (32-character bearer token)
☐ Cinema deployed at https://dsg-cinema-proof-agent.azurewebsites.net
☐ Local clone: git clone https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent
☐ Either: bash + git OR python3 installed
```

### Verify Z3 is Running

```bash
curl http://<YOUR_Z3_SERVICE_URL>/health
# Expected: {"status": "ok", "version": "4.13.0", ...}
```

**⛔ Stop if this fails. Deploy Z3 first.**

---

## 🚀 Quick Start (Choose One)

### Option A: Bash Script (Recommended for Mac/Linux/WSL)

```bash
# 1. Make executable
chmod +x CINEMA_Z3_AUTO_INTEGRATION.sh

# 2. Run it
./CINEMA_Z3_AUTO_INTEGRATION.sh \
  "http://z3-solver-service.westus3.azurecontainer.io:8080" \
  "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"

# Replace above with your actual SERVICE_URL and API_SECRET
```

**What it does (9 steps, ~20 minutes):**
1. ✅ Verifies Z3 health
2. ✅ Finds Cinema BuildConfig.kt
3. ✅ Backs up original
4. ✅ Updates with Z3 credentials
5. ✅ Verifies changes
6. ✅ Commits to GitHub
7. ✅ Triggers Azure redeploy
8. ✅ Tests Cinema health
9. ✅ Tests Z3 /solve endpoint

---

### Option B: Python Script (Cross-Platform, Windows)

```bash
# 1. Run it
python3 cinema_z3_integration.py \
  "http://z3-solver-service.westus3.azurecontainer.io:8080" \
  "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" \
  "app/src/main/java/com/example/BuildConfig.kt"

# Last parameter optional - script will search if omitted
```

**Same 9 steps, but:**
- ✅ No bash/git required
- ✅ Works on Windows, Mac, Linux
- ✅ Better error messages on Windows

---

## 📊 Timeline & What Happens

```
Time    Event                          Notes
────────────────────────────────────────────────────
0 min   Script runs                    Updates BuildConfig with Z3 credentials
        Changes pushed to GitHub       Azure detects new commit

1 min   Azure triggered redeploy       App Service pulls latest code

2-10    Cinema redeploys               App service rebuilds and restarts
        (might see 503 during this)    Normal - don't worry

10+ min Cinema live with Z3            Both endpoints responding
        ✅ Ready for production         Billing model activated
```

---

## ✅ Verification Steps (After 10 Minutes)

### Step 1: Check Z3 is Still Running
```bash
curl http://<Z3_SERVICE_URL>/health
# Expected: HTTP 200 + {"status": "ok", ...}
```

### Step 2: Check Cinema is Back Online
```bash
curl https://dsg-cinema-proof-agent.azurewebsites.net/health
# Expected: HTTP 200 + {"status": "ok", ...}
```

### Step 3: Test Z3 /solve Endpoint
```bash
curl -X POST http://<Z3_SERVICE_URL>/solve \
  -H "Authorization: Bearer <API_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "test-001",
    "problem_type": "QUBO",
    "linear": [-4, -3, 1],
    "quadratic": [[0, 1, 5], [1, 2, 2]],
    "variables": 3
  }'

# Expected: HTTP 200 + {"sat": true, "witness": [...], "proof_hash": "..."}
```

### Step 4: Test Cinema /solve Endpoint (After Redeploy)
```bash
curl -X POST https://dsg-cinema-proof-agent.azurewebsites.net/solve \
  -H "Authorization: Bearer <API_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "cinema-test",
    "problem_type": "QUBO",
    "linear": [-4, -3, 1],
    "quadratic": [[0, 1, 5], [1, 2, 2]],
    "variables": 3
  }'

# Expected: HTTP 200 + Cinema-formatted proof with Z3 verification
```

### Step 5: Verify GitHub Commit
```bash
git log -1 --oneline
# Expected: feat: Connect Cinema to Z3 Solver (...)
```

### Step 6: Check Azure Redeploy Status
```bash
az deployment group list \
  --resource-group rg-t.dealer01-0468 \
  --query '[0].[name, properties.provisioningState]' \
  -o table

# Expected status: "Succeeded"
```

---

## 🛠️ Troubleshooting

### Problem: "BuildConfig.kt not found"
```bash
# Find it manually
find . -name "BuildConfig.kt" -type f

# Then run script with full path
./CINEMA_Z3_AUTO_INTEGRATION.sh "<URL>" "<SECRET>" "/path/to/BuildConfig.kt"
```

### Problem: "Z3 health check FAILED"
```bash
# Z3 not deployed or wrong URL
# Verify Z3 deployment:
az container show \
  --resource-group <your-rg> \
  --name z3-solver-service

# Test connectivity:
curl -v http://<Z3_URL>/health
```

### Problem: "Not in a git repository"
```bash
# Navigate to Cinema repo root first
cd DSG-Cinema-Proof-Agent
../CINEMA_Z3_AUTO_INTEGRATION.sh "<URL>" "<SECRET>"
```

### Problem: Cinema returns "503 Service Unavailable"
```bash
# Normal during redeploy (5-10 minutes)
# Check deployment status:
az webapp log tail \
  --name DSG-Cinema-Proof-Agent \
  --resource-group rg-t.dealer01-0468

# Wait for it to say "Application started successfully"
```

### Problem: Z3 returns "401 Unauthorized"
```bash
# API_SECRET is wrong
# Verify your Z3 API_SECRET from deployment output
echo "API_SECRET should be: $API_SECRET"

# Re-run with correct secret:
./CINEMA_Z3_AUTO_INTEGRATION.sh "<URL>" "<CORRECT_SECRET>"
```

---

## 🔄 Rollback (If Needed)

Simple 3-step rollback:

```bash
# 1. Restore backup (script created one)
cp BuildConfig.kt.backup.1724181000 BuildConfig.kt

# 2. Commit rollback
git add BuildConfig.kt
git commit -m "Rollback Z3 integration"
git push origin main

# 3. Done - Cinema redeploys without Z3
```

---

## 🎊 Success Criteria

When integration is complete, all of these should work:

| Test | Command | Expected |
|------|---------|----------|
| Z3 health | `curl http://<Z3>/health` | HTTP 200 |
| Z3 /solve | `curl -X POST http://<Z3>/solve ...` | SAT result + proof |
| Cinema health | `curl https://dsg-cinema.azurewebsites.net/health` | HTTP 200 |
| Cinema /solve | `curl -X POST https://dsg-cinema.azurewebsites.net/solve ...` | Proof response |
| GitHub commit | `git log -1` | feat: Connect Cinema... |
| Azure redeploy | `az deployment group list ...` | Status: Succeeded |

---

## 💰 Revenue Activation

Once verified:

**Cinema can now invoice for:**
- ✅ $99/proof - "Z3 Verified Execution"
- ✅ Each proof includes Z3 verification + proof hash
- ✅ Stripe marketplace resubmission ready (add Z3 capability)
- ✅ Expected: +$1,980/month (20 proofs @ $99)

---

## 📝 Configuration Details

### What Gets Updated

The script updates Cinema's `BuildConfig.kt`:

```kotlin
// Before:
const val DSG_BACKEND_BASE_URL = ""  // Empty
const val DSG_BACKEND_API_KEY = ""   // Empty

// After:
const val DSG_BACKEND_BASE_URL = "http://z3-solver-service.westus3.azurecontainer.io:8080"
const val DSG_BACKEND_API_KEY = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

### How Cinema Uses It

```java
// In Cinema code (simplified):
String z3Url = BuildConfig.DSG_BACKEND_BASE_URL;
String z3Secret = BuildConfig.DSG_BACKEND_API_KEY;

// When Cinema needs verification:
POST {z3Url}/solve
  Authorization: Bearer {z3Secret}
  Content-Type: application/json
  Body: { problem_type: "QUBO", linear: [...], quadratic: [...] }

// Response includes:
{
  "sat": true/false,
  "witness": [...],
  "energy": number,
  "proof_hash": "sha256:...",
  "audit_event_id": "evt_..."
}
```

---

## 🚀 Next Steps After Integration

1. **Monitor Z3 Usage**
   ```bash
   curl http://<Z3_URL>/metrics  # Prometheus metrics
   ```

2. **Setup Monitoring/Alerting**
   - Z3 health checks every 60s
   - Alert if downtime > 5 minutes

3. **Plan Phase 2: PostgreSQL Persistence**
   - Currently using in-memory state
   - Phase 2: Add PostgreSQL for persistent proofs

4. **Resubmit Stripe Marketplace**
   - Update app listing with Z3 capability
   - Include in product description
   - Expect higher approval odds

5. **Track Revenue**
   - Monitor /solve endpoint usage
   - Track Z3 verification rate
   - Measure MRR impact

---

## 📞 Support & Debugging

### Check Everything is Working

```bash
#!/bin/bash
# Quick health check script

echo "Checking Z3..."
curl -s http://$Z3_URL/health | jq .

echo "Checking Cinema..."
curl -s https://dsg-cinema-proof-agent.azurewebsites.net/health | jq .

echo "Checking GitHub..."
cd DSG-Cinema-Proof-Agent && git log -1 --oneline

echo "Checking Azure deployment..."
az deployment group list --resource-group rg-t.dealer01-0468 -o table
```

### Read Full Guides

If you hit issues:
1. Read `CINEMA_Z3_INTEGRATION_GUIDE.md` (comprehensive)
2. Read `CINEMA_Z3_QUICK_START.txt` (reference)
3. Check script inline comments

---

## 🎯 Ready to Proceed?

You now have:
- ✅ Z3 Solver deployed and tested
- ✅ Cinema deployed and live
- ✅ Integration scripts (Bash + Python)
- ✅ Complete documentation
- ✅ Verification steps
- ✅ Troubleshooting guide

**Next action:** Run either script and follow the prompts.

**Expected outcome:** Cinema + Z3 fully integrated in ~20 minutes.

🚀 Let's activate that revenue stream!
