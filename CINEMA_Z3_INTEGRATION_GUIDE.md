# DSG ONE — Cinema + Z3 Integration Guide

**Purpose:** Connect Cinema Proof Agent to Z3 Solver automatically

**Timeline:** ~20 minutes total

**Requirements Before Starting:**
- ✅ Z3 Solver deployed and running
- ✅ Z3 SERVICE_URL (e.g., `http://z3-solver-service.westus3.azurecontainer.io:8080`)
- ✅ Z3 API_SECRET (32-character bearer token)
- ✅ Cinema already deployed at `https://dsg-cinema-proof-agent.azurewebsites.net`
- ✅ Local clone of `https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent`

---

## ⚠️ CRITICAL: Verify Z3 Is Running FIRST

Before running any script, confirm Z3 is responding:

```bash
curl -s http://<YOUR_Z3_SERVICE_URL>/health
```

**Expected response:**
```json
{
  "status": "ok",
  "version": "4.13.0",
  "timestamp": "2026-08-19T..."
}
```

**If you get:**
- `Connection refused` → Z3 not deployed yet
- `404 Not Found` → Wrong SERVICE_URL
- `401 Unauthorized` → Wrong API_SECRET (will test later)

✋ **Stop here and deploy Z3 first** using `DSG-Z3-COMPLETE-DEPLOYMENT-PACKAGE.zip`

---

## 🎯 Option A: Bash Script (Recommended)

**For:** macOS, Linux, WSL (Windows Subsystem for Linux)

**Prerequisites:**
```bash
which bash           # Should output: /bin/bash or similar
which git           # Should output a path
which curl          # Should output a path
```

### Step 1: Download Script

```bash
# Make it executable
chmod +x CINEMA_Z3_AUTO_INTEGRATION.sh
```

### Step 2: Run Integration

```bash
./CINEMA_Z3_AUTO_INTEGRATION.sh \
  "http://z3-solver-service.westus3.azurecontainer.io:8080" \
  "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

**Replace:**
- `http://z3-solver-service.westus3.azurecontainer.io:8080` → Your actual Z3 SERVICE_URL
- `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6` → Your actual API_SECRET

### Step 3: What the Script Does

```
✓ STEP 1: Verify Z3 is running
   - Tests /health endpoint
   - Confirms SERVICE_URL is correct

✓ STEP 2: Locate Cinema BuildConfig
   - Finds BuildConfig.kt in standard locations
   - Or prompts you to provide path

✓ STEP 3: Backup BuildConfig
   - Creates BuildConfig.kt.backup.1724181000
   - Safe to rollback if needed

✓ STEP 4: Update BuildConfig with Z3 credentials
   - Sets DSG_BACKEND_BASE_URL = <SERVICE_URL>
   - Sets DSG_BACKEND_API_KEY = <API_SECRET>

✓ STEP 5: Verify changes in BuildConfig
   - Shows updated lines
   - Confirms changes are correct

✓ STEP 6: Commit and push changes
   - git add BuildConfig.kt
   - git commit -m "feat: Connect Cinema to Z3 Solver"
   - git push origin main

✓ STEP 7: Azure App Service will auto-redeploy
   - Azure detects pushed changes
   - Automatically triggers redeployment

✓ STEP 8: Test Cinema + Z3 integration
   - Waits 30 seconds for redeploy to start
   - Tests Cinema health endpoint

✓ STEP 9: Test Z3 solve endpoint
   - Sends test QUBO problem to Z3
   - Verifies Z3 responds correctly
```

### Step 4: Verify Success

Script will print:
```
✅ INTEGRATION COMPLETE

Summary:
  ✅ Z3 health verified
  ✅ BuildConfig updated with Z3 credentials
  ✅ Changes committed to GitHub
  ✅ Redeployment triggered
  ✅ Z3 /solve endpoint tested
```

---

## 🎯 Option B: Python Script (No Dependencies)

**For:** Windows, macOS, Linux (any OS with Python 3.6+)

**Prerequisites:**
```bash
python3 --version    # Should output: Python 3.6+
```

### Step 1: Run Integration

```bash
python3 cinema_z3_integration.py \
  "http://z3-solver-service.westus3.azurecontainer.io:8080" \
  "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" \
  "app/src/main/java/com/example/BuildConfig.kt"
```

**If you omit the path, script will search:**
- `app/src/main/java/com/example/BuildConfig.kt`
- `src/main/java/com/example/BuildConfig.kt`
- `BuildConfig.kt`
- `app/BuildConfig.kt`

### Step 2: What Happens

Same as bash script (see above), but:
- Written in Python
- No git required (but will try to use git if available)
- Cross-platform compatible
- Better error messages on Windows

---

## ⏱️ What Happens Next (After Script Runs)

### Timeline:

**0 min:** Script completes
- BuildConfig updated ✅
- Changes pushed to GitHub ✅
- Z3 tested ✅

**0-2 min:** Azure detects new commit
- Redeploy triggered automatically

**2-10 min:** Cinema redeploys
- App Service pulls latest code
- BuildConfig with Z3 credentials loaded
- App restarts

**After 10 min:** Test integration manually

```bash
# Test Cinema health
curl https://dsg-cinema-proof-agent.azurewebsites.net/health

# Test Cinema /solve endpoint (after redeploy)
curl -X POST https://dsg-cinema-proof-agent.azurewebsites.net/solve \
  -H "Authorization: Bearer <API_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "manual-test",
    "problem_type": "QUBO",
    "linear": [-4, -3, 1],
    "quadratic": [[0, 1, 5], [1, 2, 2]],
    "variables": 3
  }'
```

---

## 🔧 Troubleshooting

### Problem: "BuildConfig.kt not found"

**Solution:**
```bash
# Find it manually
find . -name "BuildConfig.kt" -type f

# Then run script with full path
./CINEMA_Z3_AUTO_INTEGRATION.sh \
  "http://..." \
  "api_secret" \
  "/path/to/BuildConfig.kt"
```

### Problem: "Z3 health check FAILED"

**Verify Z3 is running:**
```bash
curl -s http://<Z3_SERVICE_URL>/health | jq .
```

**Check Z3 is accessible from your location:**
```bash
# If Z3 is in Azure
az container show --resource-group rg-t.dealer01-0468 --name z3-solver-service
```

### Problem: "Not in a git repository"

**Solution:**
```bash
# Navigate to Cinema repo root
cd DSG-Cinema-Proof-Agent

# Then run script
../CINEMA_Z3_AUTO_INTEGRATION.sh "http://..." "secret"
```

### Problem: Cinema still shows "503 Service Unavailable"

**This is normal during redeploy:**
- Wait 5-10 minutes
- Check Azure App Service deployment status:

```bash
az deployment group list \
  --resource-group rg-t.dealer01-0468 \
  --query '[0].[name, properties.provisioningState]' \
  -o table
```

**Status meanings:**
- `Accepted` → Redeploy started
- `Running` → In progress (5-10 min)
- `Succeeded` → Complete, app should be live

### Problem: Z3 /solve returns 401 Unauthorized

**Your API_SECRET is wrong:**
```bash
# Verify API_SECRET from Z3 deployment output
echo "Your Z3 API_SECRET should be: $API_SECRET"

# Test with curl
curl -X POST http://<Z3_URL>/solve \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

### Problem: "Cinema still redeploying (HTTP 503)"

**This is expected.** Redeploy can take 5-10 minutes:

```bash
# Check progress every minute
watch -n 60 'curl -s https://dsg-cinema-proof-agent.azurewebsites.net/health || echo "Still redeploying..."'
```

---

## ✅ Verification Checklist

After integration, verify each step:

| Step | What to Test | Expected Result | Command |
|------|-------------|-----------------|---------|
| 1 | Z3 health | HTTP 200 + JSON response | `curl http://<Z3>/health` |
| 2 | Cinema health | HTTP 200 + JSON response | `curl https://dsg-cinema-proof-agent.azurewebsites.net/health` |
| 3 | Z3 /solve test | HTTP 200 + `"sat": true` | `curl -X POST http://<Z3>/solve ... ` |
| 4 | Cinema /solve test | HTTP 200 + proof response | `curl -X POST https://dsg-cinema-proof-agent.azurewebsites.net/solve ...` |
| 5 | GitHub commit | See commit in repo | `git log -1 --oneline` |
| 6 | Azure redeploy | Deployment Succeeded | `az deployment group list ... ` |

---

## 🔄 Rollback (If Needed)

If something breaks, rollback is simple:

```bash
# 1. Restore backup
cp BuildConfig.kt.backup.1724181000 BuildConfig.kt

# 2. Commit & push rollback
git add BuildConfig.kt
git commit -m "Rollback Z3 integration"
git push origin main

# 3. Azure will redeploy with old config
```

**Done.** Cinema will redeploy without Z3 integration.

---

## 📊 Revenue Impact

Once integration is complete:

**Before:** Cinema only offers $99/proof (Delivery Proof)
**After:** Cinema offers $99/proof (Z3 Verified Exec)

**Expected MRR increase:** +$1,980/month (20 proofs/month @ $99)

---

## 💡 What's Actually Happening

### Cinema's Job:
1. ✅ Proof generation
2. ✅ Proof formatting
3. ✅ User API

### Z3's Job:
1. ✅ QUBO solving
2. ✅ Formal verification
3. ✅ Proof hashing

### Integration:
- Cinema calls Z3 `/solve` endpoint (via SERVICE_URL)
- Authenticates with API_SECRET (Bearer token)
- Z3 returns SAT result + proof hash
- Cinema includes proof hash in delivery proof
- Proof is now "Z3 Verified" ✅

---

## 📞 Need Help?

Check Azure status:
```bash
az app service show --name DSG-Cinema-Proof-Agent --resource-group rg-t.dealer01-0468 --query 'state'

az deployment group list --resource-group rg-t.dealer01-0468 --query '[0].[name, properties.provisioningState]' -o table
```

Check Cinema logs:
```bash
az webapp log tail --name DSG-Cinema-Proof-Agent --resource-group rg-t.dealer01-0468
```

Check Z3 is responding:
```bash
curl -v http://<Z3_SERVICE_URL>/health
curl -X POST http://<Z3_SERVICE_URL>/solve -H "Authorization: Bearer <SECRET>" ...
```

---

## 🎉 You're Done!

After integration:
- ✅ Cinema connects to Z3 automatically
- ✅ All proofs are Z3 verified
- ✅ Revenue path enabled
- ✅ Ready for production
