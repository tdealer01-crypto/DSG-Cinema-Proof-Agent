"""Acceptance for the *actual* AWS /dashboard reconstructed UI.

The original payload's exact SHA is verified by reconstruct._verified_bytes.
This feature is a navigation-only Auth0 entry, NOT automatic Cinema pairing.
"""
from pathlib import Path

import pytest

from market_ready_payload.reconstruct import (
    FILES,
    ReconstructionError,
    _add_oauth_entry,
    _verified_bytes,
    reconstruct,
)


def test_audited_oauth_entry_is_on_actual_reconstructed_work_header():
    prefix, sha = FILES["index.html"]
    original = _verified_bytes("index.html", prefix, sha)
    generated = _add_oauth_entry(original)
    assert generated != original
    assert generated.count(b'id="dsgOauthWorkroomLink"') == 1
    assert b'href="https://dsg.pics/dsg/workroom?tool=browser#live-controls"' in generated
    assert b'id="connectAgentTop"' in generated
    assert b'X-DSG-API-Key' not in generated[generated.index(b'id="dsgOauthWorkroomLink"'):generated.index(b'id="connectAgentTop"')]
    assert b'access_token=' not in generated
    assert b'pairing_token=' not in generated


def test_missing_or_duplicated_work_header_fails_closed():
    with pytest.raises(ReconstructionError, match="work header contract changed"):
        _add_oauth_entry(b'<main>no workspace</main>')
    prefix, sha = FILES["index.html"]
    original = _verified_bytes("index.html", prefix, sha)
    with pytest.raises(ReconstructionError, match="work header contract changed"):
        _add_oauth_entry(original + original)


def test_source_bound_build_emits_same_bytes_as_verified_payload(tmp_path, monkeypatch):
    from market_ready_payload import reconstruct as builder
    monkeypatch.setattr(builder, "OUT", tmp_path)
    output = reconstruct()
    prefix, sha = FILES["index.html"]
    assert (output / "index.html").read_bytes() == _add_oauth_entry(
        _verified_bytes("index.html", prefix, sha)
    )
    for name in ("styles.css", "app.js"):
        prefix, sha = FILES[name]
        assert (output / name).read_bytes() == _verified_bytes(name, prefix, sha)
    assert (output / "config.js").exists()
