#!/usr/bin/env bash
set -euo pipefail

# Thin wrapper around the single canonical integration implementation.
# Secrets are read from environment variables only and are never written to Git.
#
# Required:
#   export Z3_SERVICE_URL='https://...'
#   export Z3_API_SECRET='...'
#
# Optional:
#   export AZURE_RESOURCE_GROUP='rg-t.dealer01-0468'
#   export CINEMA_APP_NAME='dsg-cinema-proof-agent'
#   export CINEMA_BASE_URL='https://dsg-cinema-proof-agent.azurewebsites.net'
#   export CINEMA_VERIFY_PATH='/solve'
#
# Usage:
#   ./CINEMA_Z3_AUTO_INTEGRATION.sh
#   ./CINEMA_Z3_AUTO_INTEGRATION.sh --verify-only

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "BLOCK: python3 is required" >&2
  exit 1
fi

exec python3 "$SCRIPT_DIR/cinema_z3_integration.py" "$@"
