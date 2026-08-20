#!/usr/bin/env bash
set -euo pipefail

# One-time Azure bootstrap for DSG-Cinema-Proof-Agent GitHub Actions.
# Run from an authenticated Azure Cloud Shell / Azure CLI session.
#
# Security model:
# - no client secret is created
# - GitHub deploy uses a dedicated user-assigned managed identity + OIDC
# - Cinema's existing managed identity is not granted broader permissions
# - Container Apps use separate AcrPull-only identities
# - subscription resource providers are registered only during this owner-run bootstrap

SUBSCRIPTION_ID="dcf13c0d-0d9f-4f81-aa89-c6b50aaef839"
TENANT_ID="cbc618d5-9aa3-46b5-ae64-d07794603a7a"
RESOURCE_GROUP="rg-t.dealer01-0468"
LOCATION="westus3"
ACR_NAME="tdealer01acr"
GITHUB_SUBJECT_BASE="repo:tdealer01-crypto@260597462/DSG-Cinema-Proof-Agent@1326742567"
GITHUB_IDENTITY="dsg-cinema-proof-agent-github-deployer"
STAGING_PULL_IDENTITY="dsg-z3-acr-pull-staging"
PRODUCTION_PULL_IDENTITY="dsg-z3-acr-pull-production"

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

RG_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

ensure_provider() {
  local namespace="$1"
  local state
  state=$(az provider show --namespace "$namespace" --query registrationState -o tsv 2>/dev/null || true)
  if [[ "$state" != "Registered" ]]; then
    echo "  - registering $namespace"
    az provider register --namespace "$namespace" --wait --output none
  else
    echo "  - $namespace already registered"
  fi

  state=$(az provider show --namespace "$namespace" --query registrationState -o tsv)
  [[ "$state" == "Registered" ]] || fail "$namespace provider registration did not reach Registered"
}

echo "[1/9] Ensure Azure resource providers"
ensure_provider "Microsoft.App"
ensure_provider "Microsoft.OperationalInsights"
ensure_provider "Microsoft.ContainerRegistry"
ensure_provider "Microsoft.ManagedIdentity"

echo "[2/9] Ensure resource group"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

echo "[3/9] Ensure Azure Container Registry"
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
  echo "  - runtime pull identity: $identity_name"

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
    --assignee-object-id "$principal_id" \
    --scope "$ACR_ID" \
    --query "[?roleDefinitionName=='AcrPull'] | length(@)" \
    -o tsv)

  if [[ "$count" == "0" ]]; then
    for attempt in 1 2 3 4 5; do
      if az role assignment create \
        --assignee-object-id "$principal_id" \
        --assignee-principal-type ServicePrincipal \
        --role AcrPull \
        --scope "$ACR_ID" \
        --output none 2>/tmp/acrpull.err; then
        break
      fi
      if [[ "$attempt" == "5" ]]; then
        cat /tmp/acrpull.err >&2 || true
        fail "Could not grant AcrPull to $identity_name"
      fi
      sleep $((attempt * 3))
    done
  fi
}

echo "[4/9] Ensure runtime ACR pull identities"
ensure_pull_identity "$STAGING_PULL_IDENTITY"
ensure_pull_identity "$PRODUCTION_PULL_IDENTITY"

echo "[5/9] Ensure dedicated GitHub deployment identity"
if ! az identity show --name "$GITHUB_IDENTITY" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az identity create \
    --name "$GITHUB_IDENTITY" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
fi

CLIENT_ID=$(az identity show \
  --name "$GITHUB_IDENTITY" \
  --resource-group "$RESOURCE_GROUP" \
  --query clientId -o tsv)
DEPLOY_PRINCIPAL_ID=$(az identity show \
  --name "$GITHUB_IDENTITY" \
  --resource-group "$RESOURCE_GROUP" \
  --query principalId -o tsv)

[[ -n "$CLIENT_ID" ]] || fail "Could not resolve GitHub deployment identity clientId"
[[ -n "$DEPLOY_PRINCIPAL_ID" ]] || fail "Could not resolve GitHub deployment identity principalId"

echo "[6/9] Ensure Contributor role on DSG resource group"
CONTRIB_COUNT=$(az role assignment list \
  --assignee-object-id "$DEPLOY_PRINCIPAL_ID" \
  --scope "$RG_SCOPE" \
  --query "[?roleDefinitionName=='Contributor'] | length(@)" \
  -o tsv)

if [[ "$CONTRIB_COUNT" == "0" ]]; then
  for attempt in 1 2 3 4 5; do
    if az role assignment create \
      --assignee-object-id "$DEPLOY_PRINCIPAL_ID" \
      --assignee-principal-type ServicePrincipal \
      --role Contributor \
      --scope "$RG_SCOPE" \
      --output none 2>/tmp/contributor.err; then
      break
    fi
    if [[ "$attempt" == "5" ]]; then
      cat /tmp/contributor.err >&2 || true
      fail "Could not grant Contributor to $GITHUB_IDENTITY"
    fi
    sleep $((attempt * 3))
  done
fi

ensure_federated_credential() {
  local name="$1"
  local environment="$2"
  local subject="$GITHUB_SUBJECT_BASE:environment:$environment"

  if az identity federated-credential show \
      --name "$name" \
      --identity-name "$GITHUB_IDENTITY" \
      --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az identity federated-credential update \
      --name "$name" \
      --identity-name "$GITHUB_IDENTITY" \
      --resource-group "$RESOURCE_GROUP" \
      --issuer "https://token.actions.githubusercontent.com" \
      --subject "$subject" \
      --audiences "api://AzureADTokenExchange" \
      --output none
  else
    az identity federated-credential create \
      --name "$name" \
      --identity-name "$GITHUB_IDENTITY" \
      --resource-group "$RESOURCE_GROUP" \
      --issuer "https://token.actions.githubusercontent.com" \
      --subject "$subject" \
      --audiences "api://AzureADTokenExchange" \
      --output none
  fi
}

echo "[7/9] Ensure GitHub OIDC federated credentials"
ensure_federated_credential "github-staging" "staging"
ensure_federated_credential "github-production" "production"

echo "[8/9] Verify provider, role, and federation state"
[[ "$(az provider show --namespace Microsoft.App --query registrationState -o tsv)" == "Registered" ]] || fail "Microsoft.App is not registered"
[[ "$(az provider show --namespace Microsoft.OperationalInsights --query registrationState -o tsv)" == "Registered" ]] || fail "Microsoft.OperationalInsights is not registered"

CONTRIB_COUNT=$(az role assignment list \
  --assignee-object-id "$DEPLOY_PRINCIPAL_ID" \
  --scope "$RG_SCOPE" \
  --query "[?roleDefinitionName=='Contributor'] | length(@)" \
  -o tsv)
[[ "$CONTRIB_COUNT" != "0" ]] || fail "Contributor role is missing"

STAGING_SUBJECT=$(az identity federated-credential show \
  --name github-staging \
  --identity-name "$GITHUB_IDENTITY" \
  --resource-group "$RESOURCE_GROUP" \
  --query subject -o tsv)
PRODUCTION_SUBJECT=$(az identity federated-credential show \
  --name github-production \
  --identity-name "$GITHUB_IDENTITY" \
  --resource-group "$RESOURCE_GROUP" \
  --query subject -o tsv)

[[ "$STAGING_SUBJECT" == "$GITHUB_SUBJECT_BASE:environment:staging" ]] || fail "staging federated subject mismatch"
[[ "$PRODUCTION_SUBJECT" == "$GITHUB_SUBJECT_BASE:environment:production" ]] || fail "production federated subject mismatch"

echo "[9/9] Bootstrap complete"
cat <<EOF

BOOTSTRAP PASS

Dedicated GitHub OIDC managed identity is ready.
Required Azure resource providers are registered.
No password or client secret was created.
Cinema's existing managed identity was not broadened.

AZURE_CLIENT_ID=$CLIENT_ID
AZURE_TENANT_ID=$TENANT_ID
AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID

GitHub OIDC subjects:
  $GITHUB_SUBJECT_BASE:environment:staging
  $GITHUB_SUBJECT_BASE:environment:production

NEXT:
Return to ChatGPT. No secret needs to be copied.
EOF
