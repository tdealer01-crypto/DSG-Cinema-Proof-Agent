#!/usr/bin/env bash
set -euo pipefail

REPO="${DSG_GITHUB_REPO:-tdealer01-crypto/DSG-Cinema-Proof-Agent}"
DEPLOY_WORKFLOW="deploy-cinema-production.yml"
PROBE_WORKFLOW="probe-cinema-azure.yml"
STATUS_URL="https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/marketplace/stripe/status"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command '$1' is not installed." >&2
    exit 1
  }
}

for cmd in gh curl jq; do need "$cmd"; done

gh auth status >/dev/null

echo "Repository: $REPO"
echo "Enter only values you have now. Press Enter to skip any unavailable value."
echo "Input is hidden for every credential/capability value."
echo

changed=0

set_secret_interactive() {
  local name="$1" label="$2" value
  printf '%s: ' "$label" >&2
  IFS= read -r -s value
  printf '\n' >&2
  if [[ -z "$value" ]]; then
    echo "SKIP  $name"
    return 0
  fi
  printf '%s' "$value" | gh secret set "$name" --repo "$REPO"
  unset value
  echo "SET   $name"
  changed=1
}

set_variable_interactive() {
  local name="$1" label="$2" value
  printf '%s: ' "$label" >&2
  IFS= read -r -s value
  printf '\n' >&2
  if [[ -z "$value" ]]; then
    echo "SKIP  $name"
    return 0
  fi
  gh variable set "$name" --repo "$REPO" --body "$value"
  unset value
  echo "SET   $name"
  changed=1
}

dispatch_and_wait() {
  local workflow="$1" label="$2" before_id run_id
  before_id="$(gh run list \
    --repo "$REPO" \
    --workflow "$workflow" \
    --event workflow_dispatch \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // empty')"

  echo "Triggering $label..."
  gh workflow run "$workflow" --repo "$REPO" --ref main

  run_id=""
  for _ in {1..20}; do
    run_id="$(gh run list \
      --repo "$REPO" \
      --workflow "$workflow" \
      --event workflow_dispatch \
      --limit 1 \
      --json databaseId \
      --jq '.[0].databaseId // empty')"
    if [[ -n "$run_id" && "$run_id" != "$before_id" ]]; then
      break
    fi
    run_id=""
    sleep 2
  done

  if [[ -z "$run_id" ]]; then
    echo "ERROR: $label was dispatched but its new workflow run could not be resolved." >&2
    return 1
  fi

  echo "$label run: $run_id"
  gh run watch "$run_id" --repo "$REPO" --exit-status
}

set_secret_interactive \
  STRIPE_APP_SIGNING_SECRET \
  'Stripe App signing secret (absec_...)'
set_secret_interactive \
  STRIPE_APP_OAUTH_TEST_SECRET_KEY \
  'Stripe test-mode developer secret key'
set_secret_interactive \
  STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY \
  'Stripe managed-sandbox developer secret key'
set_variable_interactive \
  DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL \
  'Stripe Public Install URL (live)'
set_secret_interactive \
  STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL \
  'Stripe test-mode authorize URL'
set_secret_interactive \
  STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL \
  'Stripe External Test sandbox authorize URL'

if [[ "$changed" -eq 0 ]]; then
  echo "No values were changed; deploy was not triggered."
  exit 0
fi

echo
dispatch_and_wait "$DEPLOY_WORKFLOW" "production deploy"

echo
dispatch_and_wait "$PROBE_WORKFLOW" "production probe"

echo
echo "Stripe Marketplace readiness:"
body="$(curl --fail --silent --show-error --max-time 30 "$STATUS_URL")"
printf '%s\n' "$body" | jq '{status, checks, blockers}'

status="$(printf '%s\n' "$body" | jq -r '.status // "UNKNOWN"')"
if [[ "$status" == "READY" ]]; then
  echo "PASS: Stripe Marketplace configuration is READY."
else
  echo "ACTION_REQUIRED: configuration is not READY yet. Run this script again after obtaining the remaining Dashboard values."
fi
