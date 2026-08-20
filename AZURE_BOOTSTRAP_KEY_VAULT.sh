#!/usr/bin/env bash
set -euo pipefail

# One-time Key Vault bootstrap for DSG Stripe credentials.
# Run from an authenticated Azure Cloud Shell / Azure CLI session.
#
# Why only Stripe lives here:
# - the Z3 and Cinema credentials are regenerated on every deployment and never
#   persist anywhere, which is stronger than vaulting them would be
# - Stripe keys are long-lived, externally issued, cannot be regenerated per
#   deployment, and a leak costs money, so they need storage, rotation, and an
#   access audit trail
#
# Security model:
# - RBAC authorization, not legacy access policies
# - the Container App's existing pull identity gets Key Vault Secrets User,
#   which is read-only on secret values and grants nothing else
# - soft delete and purge protection are on, so a deleted key is recoverable
# - this script never prints a secret value

SUBSCRIPTION_ID="dcf13c0d-0d9f-4f81-aa89-c6b50aaef839"
RESOURCE_GROUP="rg-t.dealer01-0468"
LOCATION="westus3"
VAULT_NAME="${DSG_KEY_VAULT_NAME:-dsg-cinema-kv}"
PRODUCTION_PULL_IDENTITY="dsg-z3-acr-pull-production"
STRIPE_SECRET_NAME="stripe-secret-key"
STRIPE_WEBHOOK_NAME="stripe-webhook-secret"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v az >/dev/null 2>&1 || fail "Azure CLI (az) is required"

echo "[1/6] Select subscription"
az account set --subscription "$SUBSCRIPTION_ID"

echo "[2/6] Ensure Key Vault $VAULT_NAME (RBAC, soft delete, purge protection)"
if az keyvault show --name "$VAULT_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "      vault already exists"
else
  az keyvault create \
    --name "$VAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --enable-rbac-authorization true \
    --retention-days 90 \
    --enable-purge-protection true \
    --output none
fi

VAULT_ID=$(az keyvault show --name "$VAULT_NAME" --resource-group "$RESOURCE_GROUP" --query id --output tsv)
test -n "$VAULT_ID" || fail "could not resolve the vault id"

echo "[3/6] Resolve the Container App pull identity"
IDENTITY_PRINCIPAL_ID=$(az identity show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$PRODUCTION_PULL_IDENTITY" \
  --query principalId --output tsv)
test -n "$IDENTITY_PRINCIPAL_ID" || fail "identity $PRODUCTION_PULL_IDENTITY not found; run AZURE_BOOTSTRAP_GITHUB_OIDC.sh first"

echo "[4/6] Grant Key Vault Secrets User (read-only on secret values)"
EXISTING=$(az role assignment list \
  --assignee "$IDENTITY_PRINCIPAL_ID" \
  --scope "$VAULT_ID" \
  --query "[?roleDefinitionName=='Key Vault Secrets User'] | length(@)" \
  --output tsv 2>/dev/null || echo 0)
if [[ "$EXISTING" == "0" ]]; then
  az role assignment create \
    --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Key Vault Secrets User" \
    --scope "$VAULT_ID" \
    --output none
else
  echo "      role already assigned"
fi

echo "[5/6] Seed Stripe secrets if they are not present"
# Values are read from the environment so they never appear in shell history or
# in this file. Leave a variable unset to skip that secret.
seed_secret() {
  local name="$1" value="$2"
  if az keyvault secret show --vault-name "$VAULT_NAME" --name "$name" >/dev/null 2>&1; then
    echo "      $name already present; leaving it untouched"
    return
  fi
  if [[ -z "$value" ]]; then
    echo "      $name not set in the environment; create it later with:"
    echo "        az keyvault secret set --vault-name $VAULT_NAME --name $name --value <value>"
    return
  fi
  az keyvault secret set --vault-name "$VAULT_NAME" --name "$name" --value "$value" --output none
  echo "      $name stored"
}

seed_secret "$STRIPE_SECRET_NAME" "${STRIPE_SECRET_KEY:-}"
seed_secret "$STRIPE_WEBHOOK_NAME" "${STRIPE_WEBHOOK_SECRET:-}"

echo "[6/6] Verify the identity can read, and report the repository variable to set"
az role assignment list --assignee "$IDENTITY_PRINCIPAL_ID" --scope "$VAULT_ID" \
  --query "[].roleDefinitionName" --output tsv

cat <<SUMMARY

Bootstrap complete.

Set this GitHub repository variable so the deployment reads from the vault:

  DSG_KEY_VAULT_NAME = $VAULT_NAME

Then remove the STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET repository secrets:
once the variable is set the deployment prefers the vault, and leaving copies in
GitHub keeps a second place the key can leak from.

To rotate a key later, add a new version and restart the app:

  az keyvault secret set --vault-name $VAULT_NAME --name $STRIPE_SECRET_NAME --value <new value>
  az containerapp revision restart --resource-group $RESOURCE_GROUP --name dsg-cinema-production --revision <current>

SUMMARY
