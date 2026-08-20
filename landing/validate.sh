#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
test -s index.html
grep -q 'VERIFIED_GLOBAL_OPTIMUM' index.html
grep -q 'EXACT Z3 VERIFICATION' index.html
grep -q 'https://github.com/marketplace/actions/dsg-secure-deploy-gate' index.html
if grep -Eqi 'TRINITY|CONTROL PLANE LAYER|AI RUNTIME LAYER|mock auth|mock data|tdealer01-crypto-dsg-control-plane|dsg-stripe-app\.vercel\.app' index.html; then
  echo 'legacy runtime reference found in landing page' >&2
  exit 1
fi
if grep -Eqi 'SOC 2 certified|ISO 27001 certified|certified compliance' index.html; then
  echo 'unsupported certification claim found in landing page' >&2
  exit 1
fi
echo 'DSG landing validation: PASS'
