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

HTTP_CODE=$(curl --silent --show-error --max-time 60 \
  --output "$TMP_OUTPUT" \
  --write-out '%{http_code}' \
  --request POST "$BASE_URL/verify/evaluate" \
  --header 'Content-Type: application/json' \
  --data "@$REQUEST_FILE" || true)

if [[ "$HTTP_CODE" != "200" ]]; then
  cat "$TMP_OUTPUT" >&2 || true
  echo "DSG verification failed with HTTP $HTTP_CODE" >&2
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
