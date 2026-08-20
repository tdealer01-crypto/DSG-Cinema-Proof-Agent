#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/scripts/validate.sh"
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/dsg-verified-execution-plugin-1.0.0.zip"
rm -f "$OUT"
(
  cd "$ROOT"
  zip -qr "$OUT" .codex-plugin assets skills README.md PRIVACY.md TERMS.md SUPPORT.md submission \
    -x 'dist/*' '*.DS_Store'
)
echo "$OUT"
