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
    _add_existing_workspace_recovery,
    _guard_workspace_activation,
    _add_scoped_navigation,
    _add_scope_styles,
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
    assert b'target="_blank" rel="noopener noreferrer"' in generated
    assert b"Open DSG ONE Workroom (separate sign-in)" in generated
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
    assert (output / "index.html").read_bytes() == _add_existing_workspace_recovery(
        _add_scoped_navigation(_add_oauth_entry(_verified_bytes("index.html", prefix, sha)))
    )
    prefix, sha = FILES["styles.css"]
    assert (output / "styles.css").read_bytes() == _add_scope_styles(
        _verified_bytes("styles.css", prefix, sha)
    )
    prefix, sha = FILES["app.js"]
    assert (output / "app.js").read_bytes() == _guard_workspace_activation(
        _verified_bytes("app.js", prefix, sha)
    )
    assert (output / "config.js").exists()



def test_actual_dashboard_labels_runtime_contexts_without_transferring_sessions():
    prefix, sha = FILES["index.html"]
    original = _verified_bytes("index.html", prefix, sha)
    rendered = _add_scoped_navigation(_add_oauth_entry(original))

    assert rendered.count(b'id="dsgNativeControlSurface"') == 1
    assert rendered.count(b'id="dsgWorkroomSurface"') == 1
    assert rendered.count(b'id="dsgOwnerApprovalSurface"') == 1
    assert b'aria-current="page"' in rendered
    assert b"Current tab: Cinema workspace" in rendered
    assert b"Switching pages does not transfer browser sessions" in rendered
    for url in (
        b"https://dsg.pics/control/",
        b"https://dsg.pics/dsg/approvals",
    ):
        assert url in rendered
    assert rendered.count(b'target="_blank" rel="noopener noreferrer"') >= 4
    # Existing customer view/controller IDs remain available to the running JS.
    assert b'id="connectAgentTop"' in rendered
    assert b'id="remoteToggle"' in rendered
    assert b'id="browserFrame"' in rendered


def test_scope_navigation_guard_rejects_ambiguous_page_or_css():
    prefix, sha = FILES["index.html"]
    original = _verified_bytes("index.html", prefix, sha)
    with pytest.raises(ReconstructionError, match="topbar/first-view"):
        _add_scoped_navigation(b"<html></html>")
    with pytest.raises(ReconstructionError, match="topbar/first-view"):
        _add_scoped_navigation(original + original)
    css_prefix, css_sha = FILES["styles.css"]
    css = _verified_bytes("styles.css", css_prefix, css_sha)
    styled = _add_scope_styles(css)
    assert b".surface-boundary{" in styled
    assert b"grid-template-columns:1fr" in styled
    with pytest.raises(ReconstructionError, match="already present"):
        _add_scope_styles(styled)


def test_existing_user_has_visible_noncreating_path_and_explicit_new_account_choice():
    prefix, sha = FILES["index.html"]
    original = _verified_bytes("index.html", prefix, sha)
    safe = _add_existing_workspace_recovery(_add_scoped_navigation(_add_oauth_entry(original)))
    assert safe.count(b'id="returningDsgWorkroom"') == 1
    assert safe.count(b'id="confirmSeparateCinemaWorkspace"') == 1
    assert safe.count(b'id="activateWorkspace"') == 1
    assert b"Open existing DSG ONE login" in safe
    assert b"DSG ONE OAuth and Cinema Free are separate account sessions" in safe
    assert b"close this dialog and use Settings" in safe
    assert b'target="_blank" rel="noopener noreferrer"' in safe
    assert b'access_token=' not in safe
    assert b'api_key=' not in safe


def test_duplicate_workspace_creation_guard_is_fail_closed_and_retry_is_stable():
    prefix, sha = FILES["app.js"]
    original = _verified_bytes("app.js", prefix, sha)
    guarded = _guard_workspace_activation(original)
    assert guarded != original
    assert b'if(!consent||!consent.checked)' in guarded
    assert b'confirmSeparateCinemaWorkspace' in guarded
    assert b'activation_id:activationAttemptId()' in guarded
    assert b'activation_id:uuid()' not in guarded
    assert b'function activationAttemptId()' in guarded
    assert b'remove(ACTIVATION_ATTEMPT_SLOT);key=body.api_key' in guarded
    assert b'localStorage.setItem(' not in guarded
    assert b'X-DSG-API-Key' in guarded


def test_missing_or_ambiguous_workspace_repair_anchors_fail_closed():
    prefix, sha = FILES["index.html"]
    original = _verified_bytes("index.html", prefix, sha)
    with pytest.raises(ReconstructionError, match="workspace modal contract changed"):
        _add_existing_workspace_recovery(b"<main>no workspace modal</main>")
    with pytest.raises(ReconstructionError, match="workspace modal contract changed"):
        _add_existing_workspace_recovery(original + original)
    prefix, sha = FILES["app.js"]
    script = _verified_bytes("app.js", prefix, sha)
    with pytest.raises(ReconstructionError, match="activation script contract changed"):
        _guard_workspace_activation(b"function unused(){}")
    with pytest.raises(ReconstructionError, match="activation script contract changed"):
        _guard_workspace_activation(script + script)
