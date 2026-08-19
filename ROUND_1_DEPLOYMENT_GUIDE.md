# DSG ONE — ROUND 1 DEPLOYMENT GUIDE
## Z3 Solver → Azure Container Instances

**Status:** Ready to Execute  
**Date:** Aug 19, 2026  
**Target:** tdealer01-1888 (Microsoft Foundry)  
**Timeline:** ~20 minutes on your local machine

---

## ⚠️ IMPORTANT: Authentication Required

The automated deployment requires Azure authentication. This Claude environment cannot authenticate interactively, so you need to run the deployment from **your local machine**.

---

## OPTION A: Quick Deploy (Recommended)

### Prerequisites
- Azure CLI installed: https://aka.ms/InstallAzureCLI
- Docker Desktop running: https://www.docker.com/products/docker-desktop
- Python 3.11+ installed
- curl or Postman (for testing)

### Step 1: Authenticate with Azure

```bash
# Login to Azure (opens browser)
az login --tenant cbc618d5-9aa3-46b5-ae64-d07794603a7a

# Set subscription
az account set --subscription dcf13c0d-0d9f-4f81-aa89-c6b50aaef839

# Verify
az account show
```

### Step 2: Download Deployment Files

From Claude output, download these files to your local machine:
- `/home/claude/EXECUTE_ROUND_1_AZURE.sh` ← Main script
- `/mnt/user-data/outputs/z3_main.py` ← Z3 solver code
- `/mnt/user-data/outputs/requirements.txt` ← Python dependencies

### Step 3: Run Deployment Script

```bash
# On your machine, in the directory with the script
chmod +x EXECUTE_ROUND_1_AZURE.sh
./EXECUTE_ROUND_1_AZURE.sh
```

**What happens:**
1. Creates/verifies resource group
2. Creates/verifies Container Registry
3. Builds Docker image (Azure Container Build)
4. Pushes to registry
5. Deploys to Container Instances
6. Tests health endpoint
7. Saves credentials to file

**Expect:** 15-20 minutes, verbose output, final success message with service URL and API secret.

---

## OPTION B: Manual REST API Deployment

If you don't have Docker or prefer REST API, use the Python script:

### Prerequisites
- Python 3.11+
- Azure credentials (see next section)
- pip packages: requests

### Step 1: Set up Azure credentials

Choose ONE of these methods:

**Method 1: Service Principal** (recommended for automation)
```bash
# Create service principal in Azure Portal
# Then set environment variables:
export AZURE_CLIENT_ID="00000000-0000-0000-0000-000000000000"
export AZURE_CLIENT_SECRET="your-secret-here"
export AZURE_TENANT_ID="cbc618d5-9aa3-46b5-ae64-d07794603a7a"
export AZURE_SUBSCRIPTION_ID="dcf13c0d-0d9f-4f81-aa89-c6b50aaef839"
```

**Method 2: Azure CLI (user-friendly)**
```bash
# After 'az login', get access token
export AZURE_ACCESS_TOKEN=$(az account get-access-token --query accessToken -o tsv)
```

### Step 2: Run Python Deployment

```bash
# Download the Python script from Claude
# Then run:
python3 deploy_z3_azure_rest.py
```

---

## ⚡ What You'll Get

After successful deployment:

```
SERVICE_URL: http://z3-solver-service.westus3.azurecontainer.io:8080
API_SECRET: <random-32-char-hex>
```

These values go into:
1. Cinema BuildConfig.kt (ROUND 2)
2. AIMO test script (ROUND 3)
3. Revenue tracking (Documentation)

---

## 🧪 Test Your Deployment

Once deployment completes, test immediately:

```bash
# Set these from deployment output
SERVICE_URL="http://z3-solver-service.westus3.azurecontainer.io:8080"
API_SECRET="<from-output>"

# Health check
curl "$SERVICE_URL/health"

# Full QUBO solve test
curl -X POST "$SERVICE_URL/solve" \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "test-001",
    "problem_type": "QUBO",
    "linear": [-4, -3, 1],
    "quadratic": [[0, 1, 5], [1, 2, 2]],
    "variables": 3,
    "seed": 42
  }' \
  | jq .

# Expected response:
# {
#   "status": "SAT",
#   "z3_status": "sat",
#   "witness": [1, 0, 0],
#   "energy": -4,
#   "proof_hash": "sha256:...",
#   "execution_time_ms": <number>
# }
```

---

## 🔍 Troubleshooting

### "Permission denied" error
```bash
# Make script executable
chmod +x EXECUTE_ROUND_1_AZURE.sh
```

### "Docker build failed"
Docker might be running slow. Check:
```bash
docker ps  # Should show running containers
docker system df  # Check disk space
```

### "az: command not found"
Azure CLI not installed:
```bash
# macOS
brew install azure-cli

# Linux
curl -sL https://aka.ms/InstallAzureCLIDeb | bash

# Windows
choco install azure-cli
```

### "Container not starting" or timeout
Check container logs:
```bash
az container logs \
  --resource-group rg-t.dealer01-0468 \
  --name z3-solver-service
```

### "401 Unauthorized" on API calls
Check API secret:
```bash
# Verify the secret from deployment output
# and use: -H "Authorization: Bearer <SECRET>"
```

---

## 📊 Deployment Checklist

- [ ] Azure CLI installed and authenticated
- [ ] Docker Desktop running (if using shell script)
- [ ] Downloaded deployment files
- [ ] Run EXECUTE_ROUND_1_AZURE.sh (or Python script)
- [ ] Deployment completes successfully
- [ ] Health check passes (`/health` returns 200)
- [ ] Full test passes (QUBO solve returns SAT)
- [ ] Save SERVICE_URL and API_SECRET
- [ ] Document in `/mnt/user-data/outputs/Z3_AZURE_DEPLOYMENT_OUTPUTS.txt`

---

## ✅ What Happens Next

After ROUND 1 completes:

**ROUND 2:** Update Cinema App
- File: `app/src/main/java/com/example/BuildConfig.kt`
- Set: `DSG_BACKEND_BASE_URL = "<SERVICE_URL>"`
- Set: `DSG_BACKEND_API_KEY = "<API_SECRET>"`
- Build and run Cinema app

**ROUND 3:** Test AIMO Integration
- QUBO from Cinema → Z3 endpoint
- Verify proof hashes match
- Test sealed witness validation

**ROUND 4:** Enable Revenue Paths
- Path 2: Z3 Verified Exec (+$1,980/mo)
- Start collecting $99 per verified proof

---

## 📞 Support

If deployment fails:
1. Check error message carefully
2. Verify all credentials are correct
3. Check resource group exists in Azure Portal
4. Verify subscription and tenant IDs match
5. Try Option B (REST API) if Option A fails

---

## 🎯 Success Criteria

✅ Deployment complete when:
- Container created in Azure
- Health endpoint returns HTTP 200
- `/solve` endpoint accepts POST requests
- API authentication works (Bearer token)
- Returns deterministic SAT result for test QUBO

---

**Deployment Guide created:** Aug 19, 2026, 06:02 UTC  
**Status:** Ready for user execution  
**Next phase:** ROUND 1 completion → ROUND 2 (Cinema app update)
