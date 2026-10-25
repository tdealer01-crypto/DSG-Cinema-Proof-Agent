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


# Deterministic, fail-closed UX migration. The underlying packaged HTML remains
# SHA-256-verified before this audited post-verification patch is applied.
# The user accesses the EXISTING DSG ONE Auth0 Workroom. This deliberately does
# not claim to bind the legacy Cinema Free account or create a human live viewer.
_OAUTH_WORK_ANCHOR = b'<div class="inline-actions"><button id="connectAgentTop"'
_OAUTH_WORK_LINK = (
    b'<a id="dsgOauthWorkroomLink" class="primary-btn" '
    b'href="https://dsg.pics/dsg/workroom?tool=browser#live-controls" '
    b'target="_blank" rel="noopener noreferrer">Open DSG ONE Workroom (separate sign-in)</a>'
)


def _add_oauth_entry(base: bytes) -> bytes:
    """Inject the audited OAuth user entry only into the exact verified UI."""
    if base.count(_OAUTH_WORK_ANCHOR) != 1:
        raise ReconstructionError("Market-Ready work header contract changed")
    return base.replace(
        _OAUTH_WORK_ANCHOR,
        b'<div class="inline-actions">' + _OAUTH_WORK_LINK + b'<button id="connectAgentTop"',
        1,
    )




# Deliberately identify product/scope boundaries instead of suggesting that
# local Cinema pairing, OAuth Workroom, Native desktop and owner approval share
# a single automatically transferred identity or browser session.
_SURFACE_NAV_ANCHOR = b'</header>\n\n      <section id="view-home"'
_SURFACE_NAV_HTML = (
    b'</header>\n\n'
    b'      <nav class="surface-boundary" aria-label="DSG runtime surfaces">\n'
    b'        <div class="surface-current" aria-current="page"><strong>Cinema dashboard</strong>'
    b'<small>Current tab: Cinema workspace, paired agent and browser</small></div>\n'
    b'        <a id="dsgWorkroomSurface" href="https://dsg.pics/dsg/workroom?tool=browser#live-controls" '
    b'target="_blank" rel="noopener noreferrer"><strong>DSG Workroom</strong>'
    b'<small>Separate OAuth sign-in and task scope</small></a>\n'
    b'        <a id="dsgNativeControlSurface" href="https://dsg.pics/control/" '
    b'target="_blank" rel="noopener noreferrer"><strong>Native Control</strong>'
    b'<small>Separate device and execution scope</small></a>\n'
    b'        <a id="dsgOwnerApprovalSurface" href="https://dsg.pics/dsg/approvals" '
    b'target="_blank" rel="noopener noreferrer"><strong>Owner approvals</strong>'
    b'<small>Only for pending, owner-authorized grants</small></a>\n'
    b'        <p class="surface-boundary-note">Switching pages does not transfer browser sessions, '
    b'API keys, MFA authority or approved plans. Pair a Cinema agent in Work; '
    b'use Native Control for device actions.</p>\n'
    b'      </nav>\n\n'
    b'      <section id="view-home"'
)
_SCOPE_STYLES = b"""
/* Explicit dashboard/runtime scope labels; no backend state is fabricated. */
.surface-boundary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;
  margin:16px 0 20px;padding:12px;border:1px solid #334253;border-radius:12px;
  background:#141b23}
.surface-boundary>a,.surface-current{display:flex;flex-direction:column;gap:4px;
  padding:10px 12px;border:1px solid #3b4a59;border-radius:8px;
  color:#eaf1f6;text-decoration:none;min-width:0}
.surface-current{border-color:#43d49e}
.surface-boundary small{color:#aebfca;line-height:1.4}
.surface-boundary a:focus-visible{outline:2px solid #43d49e;outline-offset:2px}
.surface-boundary-note{grid-column:1/-1;margin:0;color:#c0cbd3;font-size:12px}
@media(max-width:850px){.surface-boundary{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:480px){.surface-boundary{grid-template-columns:1fr}}
"""


def _add_scoped_navigation(base: bytes) -> bytes:
    """Insert visible, truthful boundaries into the actual hash-verified UI."""
    if base.count(_SURFACE_NAV_ANCHOR) != 1:
        raise ReconstructionError("Market-Ready topbar/first-view contract changed")
    return base.replace(_SURFACE_NAV_ANCHOR, _SURFACE_NAV_HTML, 1)


def _add_scope_styles(base: bytes) -> bytes:
    if b".surface-boundary{" in base:
        raise ReconstructionError("Market-Ready scope styles already present")
    return base + _SCOPE_STYLES


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
        verified = _verified_bytes(name, prefix, expected)
        # Apply a deterministic navigation-only UX patch after verifying the
        # immutable upstream HTML checksum, never before.
        rendered = (_add_scoped_navigation(_add_oauth_entry(verified)) if name == "index.html"
                    else _add_scope_styles(verified) if name == "styles.css" else verified)
        _atomic_write(OUT / name, rendered)

    if hashlib.sha256(CONFIG).hexdigest() != CONFIG_SHA256:
        raise ReconstructionError("production Market-Ready config hash mismatch")
    _atomic_write(OUT / "config.js", CONFIG)
    return OUT


if __name__ == "__main__":
    reconstruct()
    print("DSG_MARKET_READY_RECONSTRUCT=PASS")
