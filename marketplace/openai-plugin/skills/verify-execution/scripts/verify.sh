#!/usr/bin/env bash
set -euo pipefail

REQUEST_FILE="${1:-}"
if [[ -z "$REQUEST_FILE" || ! -f "$REQUEST_FILE" ]]; then
  echo "usage: verify.sh REQUEST_JSON" >&2
  exit 64
fi

BASE_URL="${DSG_VERIFY_URL:-}"
if [[ -z "$BASE_URL" ]]; then
  echo "DSG_VERIFY_URL is required for live verification" >&2
  exit 78
fi
if [[ "$BASE_URL" != https://* ]]; then
  echo "DSG_VERIFY_URL must use HTTPS" >&2
  exit 78
fi
BASE_URL="${BASE_URL%/}"

TMP_OUTPUT="$(mktemp)"
trap 'rm -f "$TMP_OUTPUT"' EXIT

CURL_ARGS=(
  --silent --show-error --max-time 60
  --output "$TMP_OUTPUT"
  --write-out '%{http_code}'
  --request POST "$BASE_URL/verify/evaluate"
  --header 'Content-Type: application/json'
  --data "@$REQUEST_FILE"
)
# An optional key meters and attributes this agent's proofs. Without one the
# call still works wherever public evaluation is open.
if [[ -n "${DSG_API_KEY:-}" ]]; then
  CURL_ARGS+=(--header "X-DSG-API-Key: ${DSG_API_KEY}")
fi

HTTP_CODE=$(curl "${CURL_ARGS[@]}" || true)

if [[ "$HTTP_CODE" != "200" ]]; then
  # Emit the structured next action so the agent can tell the user how to fix
  # this instead of surfacing a bare HTTP status.
  python3 - "$TMP_OUTPUT" "$HTTP_CODE" <<'REMEDIATE' >&2
import json, sys

try:
    with open(sys.argv[1], encoding='utf-8') as handle:
        body = json.load(handle)
except Exception:
    body = {}

detail = body.get('detail') if isinstance(body.get('detail'), dict) else body
remediation = detail.get('remediation') if isinstance(detail, dict) else None

if isinstance(remediation, dict):
    print(f"DSG verification refused: {remediation.get('problem', '')}")
    print(f"Cause: {remediation.get('cause', '')}")
    print(f"Next step: {remediation.get('next_step', '')}")
    if remediation.get('endpoint'):
        print(f"Endpoint: {remediation['endpoint']}")
    print(f"Self-service: {remediation.get('self_service')}")
else:
    print(f"DSG verification failed with HTTP {sys.argv[2]}")
    print(json.dumps(body, indent=2)[:2000])
REMEDIATE
  exit 1
fi

python3 - "$TMP_OUTPUT" <<'PY'
import json, re, sys
p=sys.argv[1]
with open(p,'r',encoding='utf-8') as f:
    body=json.load(f)
if body.get('verified') is not True:
    raise SystemExit('verified must be true')
if body.get('verification') != 'VERIFIED_GLOBAL_OPTIMUM':
    raise SystemExit('verification must be VERIFIED_GLOBAL_OPTIMUM')
if body.get('decision') not in {'ALLOW','REVIEW','BLOCK'}:
    raise SystemExit('invalid decision')
for key in ('proof_hash','request_hash','context_hash'):
    value=body.get(key)
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise SystemExit(f'invalid {key}')
print(json.dumps(body, sort_keys=True, separators=(',',':')))
PY
