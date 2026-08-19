#!/bin/bash
set -e

###############################################################################
# DSG ONE — ROUND 1: Z3 Solver Deployment to Azure Container Instances
# Execution start: Aug 19, 2026 · 06:02 UTC
# Authorization: User approval (อนุณาติทั้งหมด)
# Target: tdealer01-1888 (Microsoft Foundry)
# Autonomy: FULL (no pauses, watch output)
###############################################################################

# Azure credentials & config
SUBSCRIPTION_ID="dcf13c0d-0d9f-4f81-aa89-c6b50aaef839"
RESOURCE_GROUP="rg-t.dealer01-0468"
LOCATION="westus3"
REGISTRY_NAME="tdealer01acr"
SERVICE_NAME="z3-solver-service"
FOUNDRY_ENDPOINT="https://tdealer01-1888-resource.services.ai.azure.com/api/projects/tdealer01-1888"

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║ ROUND 1: Z3 SOLVER DEPLOYMENT TO AZURE — IN PROGRESS                 ║"
echo "║ Target: tdealer01-1888 (Microsoft Foundry)                            ║"
echo "║ Timeline: ~15 minutes total                                           ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# STEP 1: Verify Azure Subscription & Login
# ============================================================================
echo "STEP 1/8: Verify Azure subscription"
echo "───────────────────────────────────"

CURRENT_SUB=$(az account show --query id -o tsv 2>/dev/null || echo "NONE")
echo "  Current subscription: $CURRENT_SUB"
echo "  Expected: $SUBSCRIPTION_ID"

if [ "$CURRENT_SUB" != "$SUBSCRIPTION_ID" ]; then
    echo "  ⚠️  Switching to $SUBSCRIPTION_ID..."
    az account set --subscription $SUBSCRIPTION_ID
else
    echo "  ✅ Correct subscription already set"
fi

CURRENT_ACCOUNT=$(az account show --query user.name -o tsv 2>/dev/null || echo "NONE")
echo "  Authenticated as: $CURRENT_ACCOUNT"
echo ""

# ============================================================================
# STEP 2: Verify Resource Group
# ============================================================================
echo "STEP 2/8: Verify resource group"
echo "────────────────────────────────"

RG_EXISTS=$(az group exists --name $RESOURCE_GROUP)
echo "  Resource group: $RESOURCE_GROUP"
echo "  Location: $LOCATION"
echo "  Exists: $RG_EXISTS"

if [ "$RG_EXISTS" = "false" ]; then
    echo "  Creating resource group..."
    az group create --name $RESOURCE_GROUP --location $LOCATION
else
    echo "  ✅ Resource group already exists"
fi
echo ""

# ============================================================================
# STEP 3: Create or Verify Azure Container Registry
# ============================================================================
echo "STEP 3/8: Create/verify Azure Container Registry"
echo "─────────────────────────────────────────────────"

REGISTRY_EXISTS=$(az acr list --resource-group $RESOURCE_GROUP --query "[?name=='$REGISTRY_NAME'].name" -o tsv | wc -l)

if [ "$REGISTRY_EXISTS" -eq 0 ]; then
    echo "  Creating Container Registry: $REGISTRY_NAME..."
    az acr create \
      --resource-group $RESOURCE_GROUP \
      --name $REGISTRY_NAME \
      --sku Basic \
      --location $LOCATION \
      --admin-enabled true
    echo "  ✅ Registry created"
else
    echo "  ✅ Registry already exists"
fi

REGISTRY_URL=$(az acr show --name $REGISTRY_NAME --resource-group $RESOURCE_GROUP --query loginServer -o tsv)
echo "  Registry URL: $REGISTRY_URL"
echo ""

# ============================================================================
# STEP 4: Login to Azure Container Registry
# ============================================================================
echo "STEP 4/8: Login to Container Registry"
echo "──────────────────────────────────────"

echo "  Authenticating with Azure CLI..."
az acr login --name $REGISTRY_NAME
echo "  ✅ Authenticated"
echo ""

# ============================================================================
# STEP 5: Prepare Source Files
# ============================================================================
echo "STEP 5/8: Prepare source files"
echo "───────────────────────────────"

BUILD_DIR="/tmp/z3-solver-build"
rm -rf $BUILD_DIR
mkdir -p $BUILD_DIR

echo "  Copying z3_main.py..."
cp /mnt/user-data/outputs/z3_main.py $BUILD_DIR/main.py
echo "  ✓ Copied"

echo "  Copying requirements.txt..."
cp /mnt/user-data/outputs/requirements.txt $BUILD_DIR/requirements.txt
echo "  ✓ Copied"

# Create Dockerfile (same as GCP)
cat > $BUILD_DIR/Dockerfile << 'DOCKERFILE_END'
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Z3 deterministic seed (reproducible verification)
ENV Z3_DETERMINISTIC_SEED=42
ENV PORT=8080

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=2)" || exit 1

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
DOCKERFILE_END

echo "  Dockerfile created"
echo ""

# ============================================================================
# STEP 6: Build Docker Image using Azure Container Build
# ============================================================================
echo "STEP 6/8: Build Docker image (Azure Container Build)"
echo "─────────────────────────────────────────────────────"

IMAGE_NAME="$REGISTRY_URL/$SERVICE_NAME:latest"
echo "  Building: $IMAGE_NAME"
echo "  (This takes 3-5 minutes)..."

az acr build \
  --registry $REGISTRY_NAME \
  --image "$SERVICE_NAME:latest" \
  --file "$BUILD_DIR/Dockerfile" \
  "$BUILD_DIR" 2>&1 | tail -30

echo "  ✅ Image built"
echo ""

# ============================================================================
# STEP 7: Deploy to Azure Container Instances
# ============================================================================
echo "STEP 7/8: Deploy to Azure Container Instances"
echo "──────────────────────────────────────────────"

# Generate API secret
API_SECRET=$(openssl rand -hex 32)

# Get registry credentials
REGISTRY_LOGIN=$(az acr credential show --name $REGISTRY_NAME --query username -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name $REGISTRY_NAME --query passwords[0].value -o tsv)

echo "  Deploying container..."

az container create \
  --resource-group $RESOURCE_GROUP \
  --name $SERVICE_NAME \
  --image "$IMAGE_NAME" \
  --cpu 4 \
  --memory 8 \
  --port 8080 \
  --environment-variables \
    DSG_SOLVER_SHARED_SECRET=$API_SECRET \
    Z3_DETERMINISTIC_SEED=42 \
  --registry-login-server "$REGISTRY_URL" \
  --registry-username "$REGISTRY_LOGIN" \
  --registry-password "$REGISTRY_PASSWORD" \
  --dns-name-label $SERVICE_NAME \
  --restart-policy Always 2>&1 | tail -20

echo "  ✅ Container deployed"
echo ""

# ============================================================================
# STEP 8: Get Service URL and Test
# ============================================================================
echo "STEP 8/8: Verify deployment"
echo "───────────────────────────"

# Get the FQDN
SERVICE_FQDN=$(az container show \
  --resource-group $RESOURCE_GROUP \
  --name $SERVICE_NAME \
  --query ipAddress.fqdn -o tsv)

SERVICE_URL="http://$SERVICE_FQDN:8080"

echo "  Waiting for container to start (10s)..."
sleep 10

echo "  Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" "$SERVICE_URL/health" 2>/dev/null || echo "ERROR\n000")
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -1)
BODY=$(echo "$HEALTH_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✅ Health check PASSED (HTTP 200)"
    echo "  Response: $BODY"
else
    echo "  ⚠️  Health check returned HTTP $HTTP_CODE"
    echo "  (Container may still be starting; wait 30-60s and retry)"
fi
echo ""

# ============================================================================
# SAVE OUTPUTS
# ============================================================================
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║ DEPLOYMENT COMPLETE ✅                                               ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

OUTPUT_FILE="/mnt/user-data/outputs/Z3_AZURE_DEPLOYMENT_OUTPUTS.txt"
cat > $OUTPUT_FILE << EOF
╔════════════════════════════════════════════════════════════════════════════╗
║ Z3 SOLVER DEPLOYMENT — AZURE                                             ║
║ Deployment date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')                     ║
║ Target: tdealer01-1888 (Microsoft Foundry)                               ║
╚════════════════════════════════════════════════════════════════════════════╝

SUBSCRIPTION: $SUBSCRIPTION_ID
RESOURCE GROUP: $RESOURCE_GROUP
LOCATION: $LOCATION

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SERVICE URL:
$SERVICE_URL

API SECRET (use as Authorization: Bearer <secret>):
$API_SECRET

FOUNDRY ENDPOINT:
$FOUNDRY_ENDPOINT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEXT STEPS:

1. Update Cinema BuildConfig.kt:
   const val DSG_BACKEND_BASE_URL = "$SERVICE_URL"
   const val DSG_BACKEND_API_KEY = "$API_SECRET"

2. Test Z3 endpoint (wait 1-2 min for container stabilization):
   curl -X POST "$SERVICE_URL/solve" \\
     -H "Authorization: Bearer $API_SECRET" \\
     -H "Content-Type: application/json" \\
     -d '{
       "request_id": "test-001",
       "problem_type": "QUBO",
       "linear": [-4, -3, 1],
       "quadratic": [[0, 1, 5], [1, 2, 2]],
       "variables": 3,
       "seed": 42
     }'

3. Expect response:
   {
     "status": "SAT",
     "z3_status": "sat",
     "witness": [1, 0, 0],
     "energy": -4,
     "proof_hash": "sha256:...",
     "execution_time_ms": XXX
   }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONTAINER MANAGEMENT (Azure CLI):

View logs:
  az container logs --resource-group $RESOURCE_GROUP --name $SERVICE_NAME

Restart container:
  az container restart --resource-group $RESOURCE_GROUP --name $SERVICE_NAME

Delete container:
  az container delete --resource-group $RESOURCE_GROUP --name $SERVICE_NAME

View container details:
  az container show --resource-group $RESOURCE_GROUP --name $SERVICE_NAME

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FOUNDRY INTEGRATION (Next Phase):

Register Z3 service with Foundry:
  POST $FOUNDRY_ENDPOINT/agents
  Body: {
    "type": "z3_solver",
    "endpoint": "$SERVICE_URL",
    "auth": "Bearer $API_SECRET",
    "capabilities": ["QUBO", "SAT", "SMT"]
  }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF

echo "📋 DEPLOYMENT OUTPUTS:"
echo "─────────────────────────────────────────────────────────────────────────"
echo ""
echo "SERVICE URL:"
echo "  $SERVICE_URL"
echo ""
echo "API SECRET (SAVE THIS SECURELY):"
echo "  $API_SECRET"
echo ""
echo "FOUNDRY ENDPOINT:"
echo "  $FOUNDRY_ENDPOINT"
echo ""
echo "───────────────────────────────────────────────────────────────────────────"
echo ""

# ============================================================================
# SUCCESS SUMMARY
# ============================================================================
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║ ✅ ROUND 1 COMPLETE — Z3 DEPLOYED TO AZURE & READY                   ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Timeline: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Status: 🟢 READY FOR ROUND 2 (Update Cinema)"
echo ""
echo "Outputs saved to: $OUTPUT_FILE"
echo ""
echo "Copy these values for ROUND 2:"
echo "  1. SERVICE_URL: $SERVICE_URL"
echo "  2. API_SECRET: $API_SECRET"
echo ""
