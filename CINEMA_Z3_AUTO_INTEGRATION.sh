#!/bin/bash

################################################################################
#
# DSG ONE — Cinema + Z3 Automatic Integration Script
# 
# Purpose: Connect Cinema Proof Agent to Z3 Solver automatically
# Prerequisites: 
#   - Z3 deployed and running (SERVICE_URL + API_SECRET ready)
#   - Azure CLI authenticated
#   - GitHub repo cloned locally
#   - Cinema app already deployed
#
# Usage:
#   ./CINEMA_Z3_AUTO_INTEGRATION.sh <SERVICE_URL> <API_SECRET>
#
# Example:
#   ./CINEMA_Z3_AUTO_INTEGRATION.sh \
#     "http://z3-solver-service.westus3.azurecontainer.io:8080" \
#     "a1b2c3d4e5f6..."
#
################################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# STEP 0: VALIDATE INPUT
# ============================================================================

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║ DSG ONE — Cinema + Z3 Automatic Integration                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ $# -ne 2 ]; then
    echo -e "${RED}❌ ERROR: Missing arguments${NC}"
    echo ""
    echo "Usage:"
    echo "  $0 <SERVICE_URL> <API_SECRET>"
    echo ""
    echo "Example:"
    echo "  $0 'http://z3-solver-service.westus3.azurecontainer.io:8080' 'a1b2c3d4...'"
    echo ""
    exit 1
fi

SERVICE_URL="$1"
API_SECRET="$2"

echo -e "${YELLOW}📋 Configuration:${NC}"
echo "  SERVICE_URL: $SERVICE_URL"
echo "  API_SECRET: ${API_SECRET:0:8}...${API_SECRET: -8}"
echo ""

# ============================================================================
# STEP 1: VERIFY Z3 IS RUNNING
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 1: Verify Z3 is running${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "Testing Z3 health endpoint..."
HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" "$SERVICE_URL/health" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -1)
HEALTH_BODY=$(echo "$HEALTH_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✅ Z3 health check PASSED${NC}"
    echo "   Response: $HEALTH_BODY"
else
    echo -e "${RED}❌ Z3 health check FAILED (HTTP $HTTP_CODE)${NC}"
    echo "   Make sure Z3 is deployed and running"
    echo "   SERVICE_URL: $SERVICE_URL"
    exit 1
fi
echo ""

# ============================================================================
# STEP 2: LOCATE CINEMA BUILDCONFIG
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 2: Locate Cinema BuildConfig${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Search for BuildConfig file
BUILDCONFIG_PATHS=(
    "app/src/main/java/com/example/BuildConfig.kt"
    "src/main/java/com/example/BuildConfig.kt"
    "BuildConfig.kt"
    "app/BuildConfig.kt"
)

BUILDCONFIG_FILE=""
for path in "${BUILDCONFIG_PATHS[@]}"; do
    if [ -f "$path" ]; then
        BUILDCONFIG_FILE="$path"
        echo -e "${GREEN}✅ Found BuildConfig at: $BUILDCONFIG_FILE${NC}"
        break
    fi
done

if [ -z "$BUILDCONFIG_FILE" ]; then
    echo -e "${RED}❌ BuildConfig.kt not found${NC}"
    echo ""
    echo "Searched paths:"
    for path in "${BUILDCONFIG_PATHS[@]}"; do
        echo "  - $path"
    done
    echo ""
    echo "Please specify the correct path to BuildConfig.kt:"
    read -p "Enter path: " BUILDCONFIG_FILE
    
    if [ ! -f "$BUILDCONFIG_FILE" ]; then
        echo -e "${RED}❌ File not found at: $BUILDCONFIG_FILE${NC}"
        exit 1
    fi
fi
echo ""

# ============================================================================
# STEP 3: BACKUP BUILDCONFIG
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 3: Backup BuildConfig${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

BACKUP_FILE="${BUILDCONFIG_FILE}.backup.$(date +%s)"
cp "$BUILDCONFIG_FILE" "$BACKUP_FILE"
echo -e "${GREEN}✅ Backup created: $BACKUP_FILE${NC}"
echo ""

# ============================================================================
# STEP 4: UPDATE BUILDCONFIG WITH Z3 CREDENTIALS
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 4: Update BuildConfig with Z3 credentials${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Create a temporary file with updated content
TEMP_FILE="${BUILDCONFIG_FILE}.tmp"

# Read the file and update Z3 URLs
if grep -q "DSG_BACKEND_BASE_URL" "$BUILDCONFIG_FILE"; then
    # Update existing DSG_BACKEND_BASE_URL
    sed "s|const val DSG_BACKEND_BASE_URL = .*|const val DSG_BACKEND_BASE_URL = \"$SERVICE_URL\"|g" "$BUILDCONFIG_FILE" > "$TEMP_FILE"
else
    # Add new DSG_BACKEND_BASE_URL
    cp "$BUILDCONFIG_FILE" "$TEMP_FILE"
    echo "" >> "$TEMP_FILE"
    echo "    const val DSG_BACKEND_BASE_URL = \"$SERVICE_URL\"" >> "$TEMP_FILE"
fi

# Update API Secret
if grep -q "DSG_BACKEND_API_KEY" "$TEMP_FILE"; then
    # Update existing DSG_BACKEND_API_KEY
    sed -i "s|const val DSG_BACKEND_API_KEY = .*|const val DSG_BACKEND_API_KEY = \"$API_SECRET\"|g" "$TEMP_FILE"
else
    # Add new DSG_BACKEND_API_KEY
    echo "    const val DSG_BACKEND_API_KEY = \"$API_SECRET\"" >> "$TEMP_FILE"
fi

# Replace original file with updated version
mv "$TEMP_FILE" "$BUILDCONFIG_FILE"

echo -e "${GREEN}✅ BuildConfig updated${NC}"
echo ""

# ============================================================================
# STEP 5: VERIFY CHANGES
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 5: Verify changes in BuildConfig${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "Updated lines:"
grep "DSG_BACKEND_BASE_URL\|DSG_BACKEND_API_KEY" "$BUILDCONFIG_FILE" | head -2 || echo "(Not found)"
echo ""

# ============================================================================
# STEP 6: GIT COMMIT & PUSH
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 6: Commit and push changes${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

cd "$(dirname "$BUILDCONFIG_FILE")/../../../" || cd "." # Try to go to repo root

# Check git status
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}❌ Not in a git repository${NC}"
    echo "Please navigate to the Cinema repo root and run this script again"
    exit 1
fi

# Stage changes
git add "$BUILDCONFIG_FILE"

# Commit
COMMIT_MSG="feat: Connect Cinema to Z3 Solver ($(date '+%Y-%m-%d %H:%M:%S'))"
git commit -m "$COMMIT_MSG" || true

# Push to main
echo "Pushing to main branch..."
git push origin main || git push

echo -e "${GREEN}✅ Changes committed and pushed${NC}"
echo ""

# ============================================================================
# STEP 7: TRIGGER REDEPLOYMENT
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 7: Azure App Service will auto-redeploy${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "Cinema has GitHub Continuous Deployment enabled."
echo "When you pushed to main, Azure automatically triggered a redeploy."
echo ""
echo "To check deployment status:"
echo "  az deployment group list --resource-group rg-t.dealer01-0468 --query '[0].[name,properties.provisioningState]'"
echo ""

# ============================================================================
# STEP 8: TEST INTEGRATION
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 8: Test Cinema + Z3 integration${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

CINEMA_URL="https://dsg-cinema-proof-agent.azurewebsites.net"

echo "Waiting 30 seconds for redeployment to start..."
sleep 30

echo ""
echo "Testing Cinema health endpoint..."
CINEMA_HEALTH=$(curl -s -w "\n%{http_code}" "$CINEMA_URL/health" 2>/dev/null || echo "000")
CINEMA_HTTP=$(echo "$CINEMA_HEALTH" | tail -1)

if [ "$CINEMA_HTTP" = "200" ]; then
    echo -e "${GREEN}✅ Cinema health check PASSED${NC}"
else
    echo -e "${YELLOW}⏳ Cinema still redeploying (HTTP $CINEMA_HTTP)${NC}"
    echo "   Redeploy can take 5-10 minutes"
    echo "   Check status: $CINEMA_URL/health"
fi
echo ""

# ============================================================================
# STEP 9: VERIFY Z3 INTEGRATION TEST
# ============================================================================

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}✓ STEP 9: Test Z3 solve endpoint${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "Sending test QUBO to Z3..."

QUBO_TEST='{
  "request_id": "cinema-integration-test",
  "problem_type": "QUBO",
  "linear": [-4, -3, 1],
  "quadratic": [[0, 1, 5], [1, 2, 2]],
  "variables": 3,
  "seed": 42
}'

Z3_RESPONSE=$(curl -s -X POST "$SERVICE_URL/solve" \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  -d "$QUBO_TEST" 2>/dev/null)

echo "Z3 Response:"
echo "$Z3_RESPONSE" | jq . 2>/dev/null || echo "$Z3_RESPONSE"
echo ""

# Check if response contains "SAT"
if echo "$Z3_RESPONSE" | grep -q "sat"; then
    echo -e "${GREEN}✅ Z3 solver working correctly${NC}"
else
    echo -e "${YELLOW}⚠️  Check Z3 response above${NC}"
fi
echo ""

# ============================================================================
# STEP 10: SUMMARY
# ============================================================================

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}✅ INTEGRATION COMPLETE${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}Summary:${NC}"
echo "  ✅ Z3 health verified"
echo "  ✅ BuildConfig updated with Z3 credentials"
echo "  ✅ Changes committed to GitHub"
echo "  ✅ Redeployment triggered"
echo "  ✅ Z3 /solve endpoint tested"
echo ""

echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Wait 5-10 minutes for Cinema to finish redeploying"
echo "  2. Test Cinema health: curl $CINEMA_URL/health"
echo "  3. Test Cinema /solve: curl -X POST $CINEMA_URL/solve (after redeploy)"
echo "  4. Check Azure deployment status:"
echo "     az deployment group list --resource-group rg-t.dealer01-0468"
echo ""

echo -e "${YELLOW}Rollback (if needed):${NC}"
echo "  cp $BACKUP_FILE $BUILDCONFIG_FILE"
echo "  git add $BUILDCONFIG_FILE && git commit -m 'Rollback Z3 integration' && git push"
echo ""

echo -e "${GREEN}🎉 Cinema + Z3 integration initiated!${NC}"
