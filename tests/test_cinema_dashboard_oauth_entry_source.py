"""Contract: normal DSG Cinema users can start with existing OAuth Workroom.

This is a navigation-only change, NOT a token exchange or Cinema account bind.
A separate, identity-verifying server-side bridge is required for same-session
Human Viewer before that acceptance can be claimed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/customer-dashboard/index.html").read_text(encoding="utf-8")
JS = (ROOT / "web/customer-dashboard/dashboard.js").read_text(encoding="utf-8")


def test_free_user_is_offered_existing_dsg_one_oauth_entry_without_api_key():
    assert 'id="oauthEntry"' in HTML
    assert 'id="oauthWorkroomLink"' in HTML
    assert 'href="https://dsg.pics/dsg/workroom?tool=browser#live-controls"' in HTML
    assert "Sign in with DSG ONE" in HTML
    assert HTML.index('id="oauthEntry"') < HTML.index('id="developerKeyOptions"')


def test_api_key_stays_available_in_opt_in_developer_mode():
    start = HTML.index('<details class="advanced" id="developerKeyOptions">')
    end = HTML.index('</details>', start)
    developer = HTML[start:end]
    assert 'id="apiKey"' in developer
    assert 'id="activate"' in developer
    assert 'id="connect"' in developer
    assert 'id="disconnect"' in developer
    assert 'id="remoteOn"' not in developer  # controls stay inside existing grid
    assert 'id="apiKey"' not in HTML[:start]
    assert 'X-DSG-API-Key' in JS  # legacy API clients remain compatible


def test_oauth_navigation_does_not_leak_credentials_or_claim_pairing():
    href = HTML.split('id="oauthWorkroomLink"', 1)[1].split('</a>', 1)[0]
    assert "access_token" not in href.lower()
    assert "api_key" not in href.lower()
    assert "pairing_token" not in href.lower()
    assert "It does not automatically pair" in HTML
    assert "Human Viewer" in HTML
