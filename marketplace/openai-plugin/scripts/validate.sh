#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m json.tool "$ROOT/.codex-plugin/plugin.json" >/dev/null
bash -n "$ROOT/skills/verify-execution/scripts/verify.sh"
for f in \
  "$ROOT/README.md" \
  "$ROOT/PRIVACY.md" \
  "$ROOT/TERMS.md" \
  "$ROOT/SUPPORT.md" \
  "$ROOT/skills/verify-execution/SKILL.md" \
  "$ROOT/submission/LISTING.md" \
  "$ROOT/submission/STARTER_PROMPTS.md" \
  "$ROOT/submission/TEST_CASES.md" \
  "$ROOT/submission/RELEASE_NOTES.md" \
  "$ROOT/submission/SUBMISSION_CHECKLIST.md"; do
  test -s "$f"
done
test -s "$ROOT/assets/logo.png"
if grep -RniE 'control[- ]?plane.*runtime|SOC 2 certified|ISO 27001 certified' "$ROOT" --exclude=validate.sh; then
  echo "forbidden retired-runtime or certification claim found" >&2
  exit 1
fi
echo "OpenAI plugin package validation: PASS"
