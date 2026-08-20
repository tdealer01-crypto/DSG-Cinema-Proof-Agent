#!/usr/bin/env bash
set -euo pipefail

require_bool() {
  case "$2" in
    true|false) ;;
    *) echo "$1 must be true or false" >&2; exit 2 ;;
  esac
}

for name in DSG_AUTHORIZED DSG_PLAN_ALIGNED DSG_CONSTRAINTS_PASS DSG_EXECUTION_SUCCEEDED DSG_REPLAY_MATCH DSG_EVIDENCE_COMPLETE DSG_FAIL_ON_REVIEW; do
  require_bool "$name" "${!name}"
done

if [[ ! "$DSG_ENDPOINT" =~ ^https:// ]]; then
  echo "endpoint must use HTTPS" >&2
  exit 2
fi
if [[ ! "$DSG_APPROVED_PLAN_HASH" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "approved_plan_hash must be a SHA-256 hex value" >&2
  exit 2
fi
if [[ ! "$DSG_PROPOSED_ACTION_HASH" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "proposed_action_hash must be a SHA-256 hex value" >&2
  exit 2
fi
if [[ ! "$DSG_COST_MICROUNITS" =~ ^[0-9]+$ ]]; then
  echo "cost_microunits must be a non-negative integer" >&2
  exit 2
fi

EXECUTION_ID="$DSG_EXECUTION_ID"
if [[ -z "$EXECUTION_ID" ]]; then
  EXECUTION_ID="gh-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
fi

TRACE_JSON=null
if [[ -n "$DSG_TRACE_ID" ]]; then
  TRACE_JSON=$(jq -Rn --arg value "$DSG_TRACE_ID" '$value')
fi

jq -n \
  --arg execution_id "$EXECUTION_ID" \
  --argjson trace_id "$TRACE_JSON" \
  --arg agent_identity "$DSG_AGENT_IDENTITY" \
  --arg approved_plan_hash "${DSG_APPROVED_PLAN_HASH,,}" \
  --arg proposed_action_hash "${DSG_PROPOSED_ACTION_HASH,,}" \
  --argjson authorized "$DSG_AUTHORIZED" \
  --argjson plan_aligned "$DSG_PLAN_ALIGNED" \
  --argjson constraints_pass "$DSG_CONSTRAINTS_PASS" \
  --argjson execution_succeeded "$DSG_EXECUTION_SUCCEEDED" \
  --argjson replay_match "$DSG_REPLAY_MATCH" \
  --argjson evidence_complete "$DSG_EVIDENCE_COMPLETE" \
  --argjson cost_microunits "$DSG_COST_MICROUNITS" \
  '{
    execution_id: $execution_id,
    trace_id: $trace_id,
    channel: "github",
    agent_identity: $agent_identity,
    approved_plan_hash: $approved_plan_hash,
    proposed_action_hash: $proposed_action_hash,
    authorized: $authorized,
    plan_aligned: $plan_aligned,
    constraints_pass: $constraints_pass,
    execution_succeeded: $execution_succeeded,
    replay_match: $replay_match,
    evidence_complete: $evidence_complete,
    cost_microunits: $cost_microunits
  }' > /tmp/dsg-verify-request.json

CURL_ARGS=(
  --silent --show-error
  --output "$DSG_RECEIPT_FILE"
  --write-out '%{http_code}'
  --request POST "$DSG_ENDPOINT"
  --header 'Content-Type: application/json'
  --data @/tmp/dsg-verify-request.json
)
if [[ -n "${DSG_API_KEY:-}" ]]; then
  CURL_ARGS+=(--header "X-DSG-API-Key: ${DSG_API_KEY}")
fi

HTTP_CODE=$(curl "${CURL_ARGS[@]}" || true)

# A refusal should tell the maintainer how to fix it, in the run summary where
# they are already looking, rather than leaving them an HTTP status to decode.
report_remediation() {
  local file="$1"
  local next_step problem code

  code=$(jq -r '.detail.error // .error // empty' "$file" 2>/dev/null || true)
  problem=$(jq -r '.detail.remediation.problem // .remediation.problem // empty' "$file" 2>/dev/null || true)
  next_step=$(jq -r '.detail.remediation.next_step // .remediation.next_step // empty' "$file" 2>/dev/null || true)

  if [[ -z "$next_step" ]]; then
    return 1
  fi

  # The endpoint is configurable by the workflow author. Keep response text to
  # one line before writing the GitHub output protocol so a hostile or broken
  # endpoint cannot inject additional output keys.
  code="${code//$'\r'/ }"
  code="${code//$'\n'/ }"
  problem="${problem//$'\r'/ }"
  problem="${problem//$'\n'/ }"
  next_step="${next_step//$'\r'/ }"
  next_step="${next_step//$'\n'/ }"

  printf 'remediation=%s\n' "$next_step" >> "$GITHUB_OUTPUT"
  {
    echo "### DSG Verified Execution — action required"
    echo
    echo "- **Problem:** ${problem:-The verification request was refused.}"
    [[ -n "$code" ]] && echo "- **Code:** \`$code\`"
    echo "- **Next step:** $next_step"
  } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

  echo "DSG verification refused: ${problem:-HTTP $HTTP_CODE}" >&2
  echo "Next step: $next_step" >&2
  return 0
}

if [[ "$HTTP_CODE" != "200" ]]; then
  if ! report_remediation "$DSG_RECEIPT_FILE"; then
    echo "DSG verification endpoint returned HTTP $HTTP_CODE" >&2
    cat "$DSG_RECEIPT_FILE" 2>/dev/null || true
  fi
  exit 1
fi

jq -e '
  .verified == true and
  .verification == "VERIFIED_GLOBAL_OPTIMUM" and
  (.decision == "ALLOW" or .decision == "REVIEW" or .decision == "BLOCK") and
  (.proof_hash | type == "string" and length == 64) and
  (.context_hash | type == "string" and length == 64) and
  .receipt_version == "dsg-proof-receipt-1.0.0"
' "$DSG_RECEIPT_FILE" >/dev/null

DECISION=$(jq -r '.decision' "$DSG_RECEIPT_FILE")
PROOF_HASH=$(jq -r '.proof_hash' "$DSG_RECEIPT_FILE")
CONTEXT_HASH=$(jq -r '.context_hash' "$DSG_RECEIPT_FILE")

echo "decision=$DECISION" >> "$GITHUB_OUTPUT"
echo "proof_hash=$PROOF_HASH" >> "$GITHUB_OUTPUT"
echo "context_hash=$CONTEXT_HASH" >> "$GITHUB_OUTPUT"
echo "receipt_file=$DSG_RECEIPT_FILE" >> "$GITHUB_OUTPUT"

echo "DSG Verified Execution: $DECISION"
echo "proof_hash=$PROOF_HASH"

BILLED_UNITS=$(jq -r '.billing.quantity // empty' "$DSG_RECEIPT_FILE")
{
  echo "### DSG Verified Execution — $DECISION"
  echo
  echo "- **Proof hash:** \`$PROOF_HASH\`"
  echo "- **Context hash:** \`$CONTEXT_HASH\`"
  if [[ -n "$BILLED_UNITS" ]]; then
    ACCOUNT=$(jq -r '.billing.account_id // "unknown"' "$DSG_RECEIPT_FILE")
    echo "- **Metered:** $BILLED_UNITS unit(s) to \`$ACCOUNT\`"
  else
    echo "- **Metered:** no (unattributed public evaluation)"
  fi
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

if [[ "$DECISION" == "BLOCK" ]]; then
  exit 1
fi
if [[ "$DECISION" == "REVIEW" && "$DSG_FAIL_ON_REVIEW" == "true" ]]; then
  exit 1
fi
