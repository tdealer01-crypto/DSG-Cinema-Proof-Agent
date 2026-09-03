from __future__ import annotations

import base64
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "market_ready_ui"
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "index.html": ("index.html.b64.", "103d08d706838a629b041f60ebb959682b8de0413bcf8746e6d542a7c4de0c2f"),
    "styles.css": ("dashboard.css.b64.", "3a3bc80a48497d55d4d94638fde5eb1f3ad6604300e28f97f6b488c13678a1f9"),
    "app.js": ("dashboard.js.b64.", "16782b85e755820a2fb567ad507372dd27e98cf8068a4841eb781950ee710a35"),
}

for name, (prefix, expected) in FILES.items():
    chunks = sorted(ROOT.glob(prefix + "*"))
    if not chunks:
        raise SystemExit(f"missing Market-Ready payload chunks for {name}")
    encoded = "".join(p.read_text(encoding="ascii").strip() for p in chunks)
    data = base64.b64decode(encoded, validate=True)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"Market-Ready payload hash mismatch for {name}: {actual} != {expected}")
    (OUT / name).write_bytes(data)

# Cinema serves the UI from the same origin, so production intentionally uses
# the documented empty apiBase instead of the standalone sandbox /dsg proxy.
config = b'window.DSG_CONFIG = { apiBase: "" };\n'
expected_config = "8d2858079c900fb3deaf4e0e54bea9296ae1e2d617334d1f270705ff8c33f9ab"
if hashlib.sha256(config).hexdigest() != expected_config:
    raise SystemExit("production Market-Ready config hash mismatch")
(OUT / "config.js").write_bytes(config)
print("DSG_MARKET_READY_RECONSTRUCT=PASS")
