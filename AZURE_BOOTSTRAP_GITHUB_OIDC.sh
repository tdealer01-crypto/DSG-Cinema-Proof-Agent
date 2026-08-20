#!/usr/bin/env bash
set -euo pipefail

# One-time Azure bootstrap for DSG-Cinema-Proof-Agent GitHub Actions.
# Run this from an authenticated Azure Cloud Shell / Azure CLI session.
# It creates no client secret. Authentication from GitHub uses OIDC federation.

SUBSCRIPTION_ID="dcf13c0d-0d9f-4f81-aa89-c6b50aaef839"
TENANT_ID="cbc618d5-9aa3-46b5-ae64-d07794603a7a"
RESOURCE_GROUP="rg-t.dealer01-0468"
LOCATION="westus3"
ACR_NAME="tdealer01acr"
REPO="tdealer01-crypto/DSG-Cinema-Proof-Agent"
APP_NAME="dsg-cinema-proof-agent-github-deployer"
STAGING_IDENTITY="dsg-z3-acr-pull-staging"
PRODUCTION_IDENTITY="dsg-z3-acr-pull-production"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v az >/dev/null 2>&1 || fail "Azure CLI (az) is required"

CURRENT_TENANT=$(az account show --query tenantId -o tsv 2>/dev/null || true)
[[ -n "$CURRENT_TENANT" ]] || fail "Azure CLI is not logged in. Open Azure Cloud Shell or run az login first."
[[ "$CURRENT_TENANT" == "$TENANT_ID" ]] || fail "Logged-in tenant is $CURRENT_TENANT but expected $TENANT_ID"

az account set --subscription "$SUBSCRIPTION_ID"
ACTIVE_SUB=$(az account show --query id -o tsv)
[[ "$ACTIVE_SUB" == "$SUBSCRIPTION_ID" ]] || fail "Could not select subscription $SUBSCRIPTION_ID"

echo "[1/7] Ensure resource group"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
RG_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

echo "[2/7] Ensure Azure Container Registry"
if ! az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az acr create \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Basic \
    --admin-enabled false \
    --output none
fi
ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
[[ -n "$ACR_ID" ]] || fail "Could not resolve ACR resource ID"

ensure_pull_identity() {
  local identity_name="$1"
  echo "  - identity: $identity_name"
  if ! az identity show --name "$identity_name" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az identity create \
      --name "$identity_name" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --output none
  fi

  local principal_id
  principal_id=$(az identity show \
    --name "$identity_name" \
    --resource-group "$RESOURCE_GROUP" \
    --query principalId -o tsv)
  [[ -n "$principal_id" ]] || fail "Could not resolve principalId for $identity_name"

  local count
  count=$(az role assignment list \
    --assignee "$principal_id" \
    --scope "$ACR_ID" \
    --query "[?roleDefinitionName=='AcrPull'] | length(@)" \
    -o tsv)
  if [[ "$count" == "0" ]]; then
    az role assignment create \
      --assignee-object-id "$principal_id" \
      --assignee-principal-type ServicePrincipal \
      --role AcrPull \
      --scope "$ACR_ID" \
      --output none
  fi
}

echo "[3/7] Ensure ACR pull identities"
ensure_pull_identity "$STAGING_IDENTITY"
ensure_pull_identity "$PRODUCTION_IDENTITY"

echo "[4/7] Ensure Microsoft Entra application + service principal"
APP_OBJECT_ID=$(az ad app list --display-name "$APP_NAME" --query '[0].id' -o tsv)
CLIENT_ID=$(az ad app list --display-name "$APP_NAME" --query '[0].appId' -o tsv)

if [[ -z "$CLIENT_ID" || -z "$APP_OBJECT_ID" ]]; then
  APP_JSON=$(az ad app create --display-name "$APP_NAME" --sign-in-audience AzureADMyOrg -o json)
  CLIENT_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["appId"])' <<<"$APP_JSON")
  APP_OBJECT_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$APP_JSON")
fi

if ! az ad sp show --id "$CLIENT_ID" >/dev/null 2>&1; then
  az ad sp create --id "$CLIENT_ID" --output none
fi
SP_OBJECT_ID=$(az ad sp show --id "$CLIENT_ID" --query id -o tsv)
[[ -n "$SP_OBJECT_ID" ]] || fail "Could not resolve service principal object ID"

echo "[5/7] Ensure Contributor role on the DSG resource group"
CONTRIB_COUNT=$(az role assignment list \
  --assignee "$SP_OBJECT_ID" \
  --scope "$RG_SCOPE" \
  --query "[?roleDefinitionName=='Contributor'] | length(@)" \
  -o tsv)
if [[ "$CONTRIB_COUNT" == "0" ]]; then
  az role assignment create \
    --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role Contributor \
    --scope "$RG_SCOPE" \
    --output none
fi

ensure_federated_credential() {
  local name="$1"
  local environment="$2"
  local subject="repo:$REPO:environment:$environment"
  local existing
  existing=$(az ad app federated-credential list \
    --id "$APP_OBJECT_ID" \
    --query "[?name=='$name'] | length(@)" \
    -o tsv)
  if [[ "$existing" == "0" ]]; then
    az ad app federated-credential create \
      --id "$APP_OBJECT_ID" \
      --parameters "{\"name\":\"$name\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"$subject\",\"description\":\"GitHub Actions $environment deployment for $REPO\",\"audiences\":[\"api://AzureADTokenExchange\"]}" \
      --output none
  fi
}

echo "[6/7] Ensure GitHub OIDC federated credentials"
ensure_federated_credential "github-staging" "staging"
ensure_federated_credential "github-production" "production"

echo "[7/7] Verify bootstrap state"
STAGING_COUNT=$(az ad app federated-credential list --id "$APP_OBJECT_ID" --query "[?name=='github-staging'] | length(@)" -o tsv)
PRODUCTION_COUNT=$(az ad app federated-credential list --id "$APP_OBJECT_ID" --query "[?name=='github-production'] | length(@)" -o tsv)
[[ "$STAGING_COUNT" == "1" ]] || fail "staging federated credential missing"
[[ "$PRODUCTION_COUNT" == "1" ]] || fail "production federated credential missing"

cat <<EOF

BOOTSTRAP PASS

Azure GitHub OIDC deployment identity is ready.
No client secret was created.

AZURE_CLIENT_ID=$CLIENT_ID
AZURE_TENANT_ID=$TENANT_ID
AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID

GitHub OIDC subjects:
  repo:$REPO:environment:staging
  repo:$REPO:environment:production

NEXT:
Copy only the AZURE_CLIENT_ID value above and send it back to ChatGPT.
The client ID is an identifier, not a password or client secret.
EOF
