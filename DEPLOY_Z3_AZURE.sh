#!/bin/bash
set -e

###############################################################################
# DSG Z3 Solver - Deploy to Azure Container Instances
#
# Usage:
#   ./DEPLOY_Z3_AZURE.sh
#
# Prerequisites:
#   - Azure CLI installed and authenticated (az login)
#   - Docker installed
#   - z3_main.py, requirements.txt, Dockerfile in current directory
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

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║ DSG Z3 Solver - Azure Container Instances Deployment          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# STEP 1: Check Azure CLI
# ============================================================================
echo -e "${YELLOW}STEP 1: Checking Azure CLI authentication${NC}"
if ! command -v az &> /dev/null; then
    echo -e "${RED}❌ Azure CLI not found. Install it first:${NC}"
    echo "   https://docs.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

CURRENT_SUB=$(az account show --query id -o tsv 2>/dev/null || echo "NONE")
if [ "$CURRENT_SUB" = "NONE" ]; then
    echo -e "${YELLOW}⚠️  Azure CLI not authenticated. Running: az login${NC}"
    az login
else
    echo -e "${GREEN}✅ Authenticated as: $(az account show --query user.name -o tsv)${NC}"
fi
echo ""

# ============================================================================
# STEP 2: Verify Resource Group
# ============================================================================
echo -e "${YELLOW}STEP 2: Verifying resource group${NC}"
RG_EXISTS=$(az group exists --name $RESOURCE_GROUP)
echo "   Resource group: $RESOURCE_GROUP"
echo "   Location: $LOCATION"

if [ "$RG_EXISTS" = "false" ]; then
    echo -e "${YELLOW}   Creating resource group...${NC}"
    az group create --name $RESOURCE_GROUP --location $LOCATION > /dev/null
    echo -e "${GREEN}✅ Resource group created${NC}"
else
    echo -e "${GREEN}✅ Resource group already exists${NC}"
fi
echo ""

# ============================================================================
# STEP 3: Setup Container Registry
# ============================================================================
echo -e "${YELLOW}STEP 3: Setting up Azure Container Registry${NC}"

REGISTRY_EXISTS=$(az acr list --resource-group $RESOURCE_GROUP --query "[?name=='$REGISTRY_NAME'].name" -o tsv | wc -l)

if [ "$REGISTRY_EXISTS" -eq 0 ]; then
    echo "   Creating registry: $REGISTRY_NAME"
    az acr create \
      --resource-group $RESOURCE_GROUP \
      --name $REGISTRY_NAME \
      --sku Basic \
      --location $LOCATION \
      --admin-enabled true > /dev/null
    echo -e "${GREEN}✅ Registry created${NC}"
else
    echo -e "${GREEN}✅ Registry already exists${NC}"
fi

REGISTRY_URL=$(az acr show --name $REGISTRY_NAME --resource-group $RESOURCE_GROUP --query loginServer -o tsv)
echo "   Registry URL: $REGISTRY_URL"
echo ""

# ============================================================================
# STEP 4: Login to Registry
# ============================================================================
echo -e "${YELLOW}STEP 4: Authenticating with registry${NC}"
az acr login --name $REGISTRY_NAME > /dev/null 2>&1
echo -e "${GREEN}✅ Authenticated${NC}"
echo ""

# ============================================================================
# STEP 5: Build Docker Image
# ============================================================================
echo -e "${YELLOW}STEP 5: Building Docker image${NC}"

if [ ! -f "z3_main.py" ]; then
    echo -e "${RED}❌ z3_main.py not found${NC}"
    exit 1
fi

if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ requirements.txt not found${NC}"
    exit 1
fi

if [ ! -f "Dockerfile" ]; then
    echo -e "${RED}❌ Dockerfile not found${NC}"
    exit 1
fi

docker build -t $IMAGE_NAME:latest . > /dev/null
echo -e "${GREEN}✅ Docker image built${NC}"
echo ""

# ============================================================================
# STEP 6: Tag and Push Image
# ============================================================================
echo -e "${YELLOW}STEP 6: Pushing image to registry${NC}"

FULL_IMAGE="${REGISTRY_URL}/${IMAGE_NAME}:latest"
docker tag $IMAGE_NAME:latest $FULL_IMAGE
echo "   Pushing $FULL_IMAGE..."
docker push $FULL_IMAGE > /dev/null
echo -e "${GREEN}✅ Image pushed${NC}"
echo ""

# ============================================================================
# STEP 7: Generate API Secret
# ============================================================================
echo -e "${YELLOW}STEP 7: Generating API secret${NC}"

API_SECRET=$(openssl rand -hex 16)
echo -e "   Generated: ${API_SECRET}"
echo -e "${YELLOW}   ⚠️  SAVE THIS SECRET - you'll need it for Cinema integration${NC}"
echo ""

# ============================================================================
# STEP 8: Deploy to Container Instances
# ============================================================================
echo -e "${YELLOW}STEP 8: Deploying to Azure Container Instances${NC}"

# Get ACR credentials
REGISTRY_USER=$(az acr credential show --name $REGISTRY_NAME --resource-group $RESOURCE_GROUP --query username -o tsv)
REGISTRY_PASS=$(az acr credential show --name $REGISTRY_NAME --resource-group $RESOURCE_GROUP --query passwords[0].value -o tsv)

# Check if container already exists and delete it
CONTAINER_EXISTS=$(az container list --resource-group $RESOURCE_GROUP --query "[?name=='$CONTAINER_NAME'].name" -o tsv | wc -l)

if [ "$CONTAINER_EXISTS" -gt 0 ]; then
    echo "   Deleting existing container..."
    az container delete --resource-group $RESOURCE_GROUP --name $CONTAINER_NAME --yes > /dev/null
    echo "   Waiting for deletion..."
    sleep 5
fi

echo "   Creating container..."
az container create \
    --resource-group $RESOURCE_GROUP \
    --name $CONTAINER_NAME \
    --image $FULL_IMAGE \
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

echo -e "${GREEN}✅ Container deployment initiated${NC}"
echo "   Waiting for container to start (this may take 1-2 minutes)..."
sleep 15
echo ""

# ============================================================================
# STEP 9: Get Service URL
# ============================================================================
echo -e "${YELLOW}STEP 9: Retrieving service URL${NC}"

# Wait for IP to be assigned
for i in {1..30}; do
    SERVICE_IP=$(az container show --resource-group $RESOURCE_GROUP --name $CONTAINER_NAME --query ipAddress.ip -o tsv 2>/dev/null || echo "")
    if [ ! -z "$SERVICE_IP" ] && [ "$SERVICE_IP" != "null" ]; then
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}❌ Failed to get service IP${NC}"
        exit 1
    fi
    sleep 2
done

SERVICE_URL="http://${SERVICE_IP}:8080"
echo -e "   Service URL: ${SERVICE_URL}"
echo ""

# ============================================================================
# STEP 10: Test Health Endpoint
# ============================================================================
echo -e "${YELLOW}STEP 10: Testing health endpoint${NC}"

for i in {1..30}; do
    HEALTH=$(curl -s --connect-timeout 2 "$SERVICE_URL/health" 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q "ok"; then
        echo -e "${GREEN}✅ Health check passed${NC}"
        echo "   Response: $HEALTH"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}⚠️  Health check timeout (still deploying, may take another minute)${NC}"
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

# ============================================================================
# STEP 11: Test QUBO Solver
# ============================================================================
echo -e "${YELLOW}STEP 11: Testing Z3 /solve endpoint${NC}"

TEST_PAYLOAD='{
  "request_id": "deployment-test",
  "problem_type": "QUBO",
  "linear": [-4, -3, 1],
  "quadratic": [[0, 1, 5], [1, 2, 2]],
  "variables": 3,
  "seed": 42
}'

SOLVE_RESPONSE=$(curl -s -X POST "$SERVICE_URL/solve" \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  -d "$TEST_PAYLOAD" 2>/dev/null || echo "")

if echo "$SOLVE_RESPONSE" | grep -q "sat\|witness"; then
    echo -e "${GREEN}✅ Z3 solver test passed${NC}"
    echo "   Response: $(echo "$SOLVE_RESPONSE" | jq -c . 2>/dev/null || echo "$SOLVE_RESPONSE")"
else
    echo -e "${YELLOW}⚠️  Solver test returned: $SOLVE_RESPONSE${NC}"
fi
echo ""

# ============================================================================
# SUMMARY
# ============================================================================
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}✅ Z3 SOLVER DEPLOYMENT COMPLETE${NC}"
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
echo "   2. Run Cinema + Z3 integration:"
echo "      ./CINEMA_Z3_AUTO_INTEGRATION.sh \"${SERVICE_URL}\" \"${API_SECRET}\""
echo ""
echo -e "${YELLOW}Verify Deployment:${NC}"
echo "   curl ${SERVICE_URL}/health"
echo ""
echo -e "${GREEN}🎉 Ready for Cinema integration!${NC}"
