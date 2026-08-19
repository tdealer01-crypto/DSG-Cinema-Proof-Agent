# Deploy Z3 to Azure via GitHub Actions

**ทำได้ 3 วิธี:**

---

## วิธี 1️⃣ : RUN MANUALLY จาก GitHub UI (ง่ายสุด)

### Step 1: สร้าง Service Principal ใน Azure

```bash
# Run on your local machine or in Azure Cloud Shell
az ad sp create-for-rbac \
  --name "github-z3-deployer" \
  --role Contributor \
  --scopes /subscriptions/dcf13c0d-0d9f-4f81-aa89-c6b50aaef839 \
  --json-auth > github_sp.json

cat github_sp.json
```

Output จะดูแบบนี้:
```json
{
  "clientId": "00000000-0000-0000-0000-000000000000",
  "clientSecret": "abc123xyz...",
  "subscriptionId": "dcf13c0d-0d9f-4f81-aa89-c6b50aaef839",
  "tenantId": "cbc618d5-9aa3-46b5-ae64-d07794603a7a"
}
```

### Step 2: เพิ่ม GitHub Secrets

ไปที่ GitHub Repo → Settings → Secrets and variables → Actions

**เพิ่ม 3 secrets:**

| Secret Name | Value |
|------------|-------|
| `AZURE_SUBSCRIPTION_ID` | `dcf13c0d-0d9f-4f81-aa89-c6b50aaef839` |
| `AZURE_TENANT_ID` | `cbc618d5-9aa3-46b5-ae64-d07794603a7a` |
| `AZURE_CLIENT_ID` | (จาก github_sp.json → clientId) |
| `AZURE_CLIENT_SECRET` | (จาก github_sp.json → clientSecret) ⚠️ เก็บเป็นความลับ |

### Step 3: Upload Workflow File

```bash
# Copy ไฟล์ workflow ไปที่ repo
cp .github_workflows_deploy-z3-azure.yml .github/workflows/deploy-z3-azure.yml

git add .github/workflows/deploy-z3-azure.yml
git commit -m "Add Z3 deployment workflow"
git push
```

### Step 4: Upload Z3 Source Files

```bash
# Copy Z3 source + Dockerfile to repo root
cp z3_main.py .
cp requirements.txt .

# ก็ต้องอัพ Dockerfile ด้วย (อันเดียวกับที่อยู่ในไฟล์ script)
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY z3_main.py main.py

ENV Z3_DETERMINISTIC_SEED=42
ENV PORT=8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=2)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
EOF

git add z3_main.py requirements.txt Dockerfile
git commit -m "Add Z3 solver source + Dockerfile"
git push
```

### Step 5: Run Deployment

ไปที่ GitHub Repo → Actions → **"Deploy Z3 to Azure"**

คลิก **"Run workflow"** → เลือก environment (production) → **"Run workflow"**

**จะเห็น progress:** 
- ✅ Checkout
- ✅ Azure Login
- ✅ Build image
- ✅ Deploy container
- ✅ Test health
- ✅ Done!

**Deployment outputs จะ save เป็น artifact** ที่สามารถ download ได้

---

## วิธี 2️⃣ : AUTO-DEPLOY ทุกครั้งที่ push

Workflow จะ auto-run เมื่อ:
- Push to `main` branch
- Files `z3_main.py`, `requirements.txt`, หรือ workflow file เปลี่ยน

**ไม่ต้องคลิกอะไร - automatic** ✨

---

## วิธี 3️⃣ : Deploy ด้วย Azure Federated Identity (ปลอดภัยสุด)

แทนที่จะใช้ `AZURE_CLIENT_SECRET` (password) ที่อันตราย
ใช้ OpenID Connect (OIDC) ที่ไม่ต้องเก็บ secret เลย

### ขั้นตอน:
1. สร้าง Federated Identity Credential ใน Azure Portal
2. เชื่อม GitHub org/repo/branch กับ Azure
3. ใน workflow ใช้ `azure/login@v1` + OIDC

**ปลอดภัย:** ไม่มี password เก็บใน GitHub secrets

---

## 📊 Workflow Features

| Feature | มี/ไม่มี |
|---------|---------|
| Auto-deploy on push | ✅ (ปิด/เปิดได้) |
| Manual trigger (workflow_dispatch) | ✅ |
| Environment selection | ✅ (production/staging) |
| Docker build + push | ✅ (ใช้ Azure Container Build) |
| Container Instances deploy | ✅ |
| Health check test | ✅ |
| Artifact outputs (URL + Secret) | ✅ |
| Failure notifications | ✅ |

---

## 🔍 Monitor Deployment

ไปที่ GitHub → Actions → ดูสีไฟ:
- 🟢 Green = Success
- 🟡 Yellow = Running
- 🔴 Red = Failed

คลิกเข้า run ที่ fail เพื่อดู error logs

---

## ⚠️ Security Best Practices

```
✅ DO:
  - Keep secrets in GitHub, ไม่ commit ใน code
  - ใช้ Federated Identity (no password)
  - Review pull requests ก่อน merge
  - ใช้ environment protection rules

❌ DON'T:
  - Commit .env files
  - Share AZURE_CLIENT_SECRET
  - ใช้ personal access tokens
  - Allow auto-deploy ถ้าไม่แน่ใจ
```

---

## 🧪 Test Deployment Output

ตัวอย่าง artifact ที่จะออกมา:

```
SERVICE_URL: http://z3-solver-service.westus3.azurecontainer.io:8080
API_SECRET: a1b2c3d4e5f6...

Test curl:
curl -X POST "http://z3-solver-service.westus3.azurecontainer.io:8080/solve" \
  -H "Authorization: Bearer a1b2c3d4e5f6..." \
  -H "Content-Type: application/json" \
  -d '{"request_id":"test","problem_type":"QUBO","linear":[-4,-3,1],...}'
```

---

## 📋 Checklist

- [ ] สร้าง Service Principal ใน Azure
- [ ] เพิ่ม 4 GitHub Secrets
- [ ] Copy workflow ไป `.github/workflows/deploy-z3-azure.yml`
- [ ] Push z3_main.py, requirements.txt, Dockerfile
- [ ] ไปที่ Actions → Run workflow
- [ ] รอ deployment เสร็จ
- [ ] Download artifact ที่มี SERVICE_URL + API_SECRET
- [ ] Test curl command ให้ได้ SAT response

---

**ทำผ่าน GitHub ได้ ✅**  
**อ่านรายละเอียดมากกว่านี้ → ROUND_1_DEPLOYMENT_GUIDE.md**
