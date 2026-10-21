"""Source-level regression for the AWS DSG OS shared browser dashboard.

These assertions do not replace live user+agent same-session acceptance.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web" / "customer-dashboard" / "browserbase-live.js").read_text(encoding="utf-8")


def test_dashboard_accepts_canonical_self_hosted_and_exact_compatibility_viewers():
    assert "self-hosted\\/view" in JS
    assert "browserbase\\/embed" in JS
    assert "azure\\/view" in JS  # historical path label, NOT an Azure provider
    assert "VIEWER_PATH.test(embedUrl)" in JS
    assert 'embedUrl.startsWith("/remote-browser/browserbase/embed/")' not in JS


def test_dashboard_preserves_same_session_login_focus_across_refreshes():
    assert "lastSessionId" in JS
    assert "sessionId !== lastSessionId" in JS
    assert 'body.browser_session_id || body.browserbase_session_id' in JS
    assert "viewerMountedAt" in JS
    assert "VIEWER_RENEW_MS" in JS


def test_dashboard_clears_binding_when_remote_viewer_disconnects():
    assert 'lastSessionId = "";' in JS
    assert 'viewerMountedAt = 0;' in JS
    assert 'frame.removeAttribute("src")' in JS
