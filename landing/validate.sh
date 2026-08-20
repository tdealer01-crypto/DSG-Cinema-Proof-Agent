#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
test -s index.html
grep -q 'VERIFIED_GLOBAL_OPTIMUM' index.html
grep -q 'AZURE UI → CINEMA → EXACT Z3 → PROOF RECEIPT' index.html
grep -q 'https://github.com/marketplace/actions/dsg-secure-deploy-gate' index.html
grep -q 'dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io' index.html
grep -q 'Run live verification' index.html
grep -q 'Download receipt JSON' index.html
grep -q 'OpenAI Skills' index.html
grep -q 'Microsoft Marketplace' index.html
grep -q 'AWS Marketplace' index.html
grep -q 'JetBrains Marketplace' index.html
grep -q 'Checkout status: NOT VERIFIED / NOT LINKED' index.html
if grep -Eqi 'TRINITY|CONTROL PLANE LAYER|AI RUNTIME LAYER|mock auth|mock data|tdealer01-crypto-dsg-control-plane|dsg-stripe-app\.vercel\.app' index.html; then
  echo 'legacy runtime reference found in landing page' >&2
  exit 1
fi
if grep -Eqi 'SOC 2 certified|ISO 27001 certified|certified compliance' index.html; then
  echo 'unsupported certification claim found in landing page' >&2
  exit 1
fi
echo 'DSG landing validation: PASS'
