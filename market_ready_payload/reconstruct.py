from __future__ import annotations

import base64
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "market_ready_ui"

FILES = {
    "index.html": ("index.html.b64.", "103d08d706838a629b041f60ebb959682b8de0413bcf8746e6d542a7c4de0c2f"),
    "styles.css": ("dashboard.css.b64.", "3a3bc80a48497d55d4d94638fde5eb1f3ad6604300e28f97f6b488c13678a1f9"),
    "app.js": ("dashboard.js.b64.", "16782b85e755820a2fb567ad507372dd27e98cf8068a4841eb781950ee710a35"),
}

CONFIG = b'window.DSG_CONFIG = { apiBase: "" };\n'
CONFIG_SHA256 = "8d2858079c900fb3deaf4e0e54bea9296ae1e2d617334d1f270705ff8c33f9ab"


class ReconstructionError(RuntimeError):
    """Raised when the committed Market-Ready payload cannot be proven exact."""


def _verified_bytes(name: str, prefix: str, expected: str) -> bytes:
    chunks = sorted(ROOT.glob(prefix + "*"))
    if not chunks:
        raise ReconstructionError(f"missing Market-Ready payload chunks for {name}")
    try:
        encoded = "".join(p.read_text(encoding="ascii").strip() for p in chunks)
        data = base64.b64decode(encoded, validate=True)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReconstructionError(f"invalid Market-Ready payload encoding for {name}") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ReconstructionError(
            f"Market-Ready payload hash mismatch for {name}: {actual} != {expected}"
        )
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def reconstruct() -> Path:
    """Materialize the exact sandbox-tested UI after proving every source hash.

    Docker invokes this during the image build. Source-checkout tests and local
    Cinema startup can call the same function, so there is only one verified
    reconstruction path and no fallback to mock or legacy customer markup.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (prefix, expected) in FILES.items():
        _atomic_write(OUT / name, _verified_bytes(name, prefix, expected))

    if hashlib.sha256(CONFIG).hexdigest() != CONFIG_SHA256:
        raise ReconstructionError("production Market-Ready config hash mismatch")
    _atomic_write(OUT / "config.js", CONFIG)
    return OUT


if __name__ == "__main__":
    reconstruct()
    print("DSG_MARKET_READY_RECONSTRUCT=PASS")
