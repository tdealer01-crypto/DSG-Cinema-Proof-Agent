#!/bin/bash
set -e

###############################################################################
# DSG Z3 Solver - Deploy to Azure Container Instances (v2 - Fixed)
#
# This version includes:
# - Robust error handling
# - ACR-based Docker build (no local Docker needed)
# - Better logging and progress tracking
# - Container health monitoring
#
# Prerequisites:
#   - Azure CLI installed and authenticated (az login)
#   - z3_main.py, requirements.txt in current directory
###############################################################################

# Configuration
SUBSCRIPTION_ID="dcf13c0d-0d9f-4f81-aa89-c6b50aaef839"
RESOURCE_GROUP="rg-t.dealer01-0468"
LOCATION="westus3"
REGISTRY_NAME="tdealer01acr"
SERVICE_NAME="z3-solver-service"
IMAGE_NAME="z3-solver-service"
CONTAINER_NAME="z3-solver-service"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Log function
log_step() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] $1${NC}"
}

log_success() {
    echo -e "${GREEN}[✓] $1${NC}"
}

log_error() {
    echo -e "${RED}[✗] $1${NC}"
}

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║ DSG Z3 Solver - Azure Container Instances Deployment (v2)     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# STEP 1: Check Azure CLI
# ============================================================================
log_step "STEP 1: Checking Azure CLI"
if ! command -v az &> /dev/null; then
    log_error "Azure CLI not found. Install: https://docs.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

CURRENT_SUB=$(az account show --query id -o tsv 2>/dev/null || echo "NONE")
if [ "$CURRENT_SUB" = "NONE" ]; then
    log_step "Azure CLI not authenticated. Running: az login"
    az login
fi
log_success "Authenticated as: $(az account show --query user.name -o tsv)"
echo ""

# ============================================================================
# STEP 2: Verify Resource Group
# ============================================================================
log_step "STEP 2: Verifying resource group: $RESOURCE_GROUP"
RG_EXISTS=$(az group exists --name $RESOURCE_GROUP)

if [ "$RG_EXISTS" = "false" ]; then
    log_step "Creating resource group..."
    az group create --name $RESOURCE_GROUP --location $LOCATION > /dev/null
    log_success "Resource group created"
else
    log_success "Resource group already exists"
fi
echo ""

# ============================================================================
# STEP 3: Setup Container Registry
# ============================================================================
log_step "STEP 3: Setting up Azure Container Registry"

REGISTRY_EXISTS=$(az acr list --resource-group $RESOURCE_GROUP --query "[?name=='$REGISTRY_NAME'].name" -o tsv | wc -l)

if [ "$REGISTRY_EXISTS" -eq 0 ]; then
    log_step "Creating registry: $REGISTRY_NAME"
    az acr create \
      --resource-group $RESOURCE_GROUP \
      --name $REGISTRY_NAME \
      --sku Basic \
      --location $LOCATION \
      --admin-enabled true > /dev/null
    log_success "Registry created"
else
    log_success "Registry already exists"
fi

REGISTRY_URL=$(az acr show --name $REGISTRY_NAME --resource-group $RESOURCE_GROUP --query loginServer -o tsv)
log_success "Registry URL: $REGISTRY_URL"
echo ""

# ============================================================================
# STEP 4: Login to Registry
# ============================================================================
log_step "STEP 4: Authenticating with registry"
az acr login --name $REGISTRY_NAME > /dev/null 2>&1
log_success "Authenticated with ACR"
echo ""

# ============================================================================
# STEP 5: Verify Source Files
# ============================================================================
log_step "STEP 5: Verifying source files"
if [ ! -f "z3_main.py" ]; then
    log_error "z3_main.py not found"
    exit 1
fi

if [ ! -f "requirements.txt" ]; then
    log_error "requirements.txt not found"
    exit 1
fi

if [ ! -f "Dockerfile" ]; then
    log_error "Dockerfile not found"
    exit 1
fi

log_success "All source files present"
echo ""

# ============================================================================
# STEP 6: Build Docker Image in ACR (no local Docker needed)
# ============================================================================
log_step "STEP 6: Building Docker image in ACR"
log_step "This may take 2-3 minutes..."

BUILD_RESULT=$(az acr build \
  --registry $REGISTRY_NAME \
  --image ${IMAGE_NAME}:latest \
  . 2>&1 || echo "BUILD_FAILED")

if echo "$BUILD_RESULT" | grep -q "BUILD_FAILED"; then
    log_error "Docker image build failed"
    echo "$BUILD_RESULT"
    exit 1
fi

log_success "Docker image built successfully"
echo ""

# ============================================================================
# STEP 7: Generate API Secret
# ============================================================================
log_step "STEP 7: Generating API secret"
API_SECRET=$(openssl rand -hex 16)
log_success "Generated: ${API_SECRET}"
echo ""

# ============================================================================
# STEP 8: Deploy to Container Instances
# ============================================================================
log_step "STEP 8: Deploying to Azure Container Instances"

# Get ACR credentials
REGISTRY_USER=$(az acr credential show --name $REGISTRY_NAME --resource-group $RESOURCE_GROUP --query username -o tsv)
REGISTRY_PASS=$(az acr credential show --name $REGISTRY_NAME --resource-group $RESOURCE_GROUP --query passwords[0].value -o tsv)

# Check if container already exists and delete it
CONTAINER_EXISTS=$(az container list --resource-group $RESOURCE_GROUP --query "[?name=='$CONTAINER_NAME'].name" -o tsv | wc -l)

if [ "$CONTAINER_EXISTS" -gt 0 ]; then
    log_step "Deleting existing container..."
    az container delete --resource-group $RESOURCE_GROUP --name $CONTAINER_NAME --yes > /dev/null
    log_step "Waiting for deletion to complete..."
    sleep 10
fi

log_step "Creating new container..."
FULL_IMAGE="${REGISTRY_URL}/${IMAGE_NAME}:latest"

az container create \
    --resource-group $RESOURCE_GROUP \
    --name $CONTAINER_NAME \
    --image $FULL_IMAGE \
    --os-type Linux \
    --cpu 2 \
    --memory 2 \
    --registry-login-server $REGISTRY_URL \
    --registry-username $REGISTRY_USER \
    --registry-password $REGISTRY_PASS \
    --ip-address public \
    --ports 8080 \
    --environment-variables \
        DSG_SOLVER_SHARED_SECRET=$API_SECRET \
        Z3_DETERMINISTIC_SEED=42 \
        PORT=8080 \
    --protocol TCP > /dev/null

log_success "Container deployment initiated"
log_step "Waiting for container to start (this may take 1-2 minutes)..."
sleep 20
echo ""

# ============================================================================
# STEP 9: Get Service URL
# ============================================================================
log_step "STEP 9: Retrieving service URL"

SERVICE_IP=""
for i in {1..30}; do
    SERVICE_IP=$(az container show --resource-group $RESOURCE_GROUP --name $CONTAINER_NAME --query ipAddress.ip -o tsv 2>/dev/null || echo "")
    if [ ! -z "$SERVICE_IP" ] && [ "$SERVICE_IP" != "null" ]; then
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Failed to get service IP after 60 seconds"
        exit 1
    fi
    echo -n "."
    sleep 2
done

SERVICE_URL="http://${SERVICE_IP}:8080"
log_success "Service URL: ${SERVICE_URL}"
echo ""

# ============================================================================
# STEP 10: Test Health Endpoint
# ============================================================================
log_step "STEP 10: Testing health endpoint"

HEALTH_OK=0
for i in {1..30}; do
    HEALTH=$(curl -s --connect-timeout 2 "$SERVICE_URL/health" 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q "status"; then
        log_success "Health check passed"
        echo "   Response: $HEALTH"
        HEALTH_OK=1
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Health check timeout after 60 seconds"
        log_step "Checking container logs for errors..."
        az container logs --resource-group $RESOURCE_GROUP --name $CONTAINER_NAME | head -50
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

# ============================================================================
# STEP 11: Test QUBO Solver
# ============================================================================
if [ "$HEALTH_OK" -eq 1 ]; then
    log_step "STEP 11: Testing Z3 /solve endpoint"

    TEST_PAYLOAD='{
      "request_id": "deployment-test",
      "preset_name": "test_deployment",
      "problem_type": "qubo",
      "linear": [-4, -3, 1],
      "quadratic": [[5], [2]],
      "proveOptimality": true,
      "z3TimeoutMs": 30000
    }'

    SOLVE_RESPONSE=$(curl -s -X POST "$SERVICE_URL/solve" \
      -H "Authorization: Bearer $API_SECRET" \
      -H "Content-Type: application/json" \
      -d "$TEST_PAYLOAD" 2>/dev/null || echo "")

    if echo "$SOLVE_RESPONSE" | grep -q "z3_status"; then
        log_success "Z3 solver test passed"
        echo "   Response: $(echo "$SOLVE_RESPONSE" | jq -c . 2>/dev/null || echo "$SOLVE_RESPONSE")"
    else
        log_error "Solver test returned: $SOLVE_RESPONSE"
    fi
    echo ""
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}✅ Z3 SOLVER DEPLOYMENT COMPLETE (v2)${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Service Details:${NC}"
echo "   Service URL:    ${SERVICE_URL}"
echo "   API Secret:     ${API_SECRET}"
echo "   Resource Group: ${RESOURCE_GROUP}"
echo "   Container Name: ${CONTAINER_NAME}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "   1. Save the API Secret above"
echo "   2. Verify health endpoint:"
echo "      curl ${SERVICE_URL}/health"
echo "   3. Run Cinema + Z3 integration:"
echo "      ./CINEMA_Z3_AUTO_INTEGRATION.sh \"${SERVICE_URL}\" \"${API_SECRET}\""
echo ""
echo -e "${GREEN}🎉 Ready for Cinema integration!${NC}"
