#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/scripts/dsg_browser.py"
TARGET_DIR="${DSG_BROWSER_INSTALL_DIR:-$HOME/.local/bin}"
TARGET="$TARGET_DIR/dsg-browser"
mkdir -p "$TARGET_DIR"
PYTHON_BIN="$(command -v python3 || true)"
[[ -n "$PYTHON_BIN" ]] || { echo "BLOCK: python3 is required" >&2; exit 20; }
install -m 0755 "$SOURCE" "$TARGET"
python3 - "$TARGET" "$PYTHON_BIN" <<'PYFIX'
from pathlib import Path
import sys
path=Path(sys.argv[1]); python=sys.argv[2]
lines=path.read_text(encoding="utf-8").splitlines()
lines[0]=f"#!{python}"
path.write_text("\n".join(lines)+"\n",encoding="utf-8")
PYFIX
printf 'installed=%s\n' "$TARGET"
case ":$PATH:" in
  *":$TARGET_DIR:"*) ;;
  *) printf 'PATH_HINT=export PATH="%s:$PATH"\n' "$TARGET_DIR" ;;
esac
