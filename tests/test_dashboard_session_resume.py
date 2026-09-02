from pathlib import Path


def test_dashboard_reuses_connect_agent_session_without_pasting_key() -> None:
    script = Path("web/customer-dashboard/dashboard.js").read_text(encoding="utf-8")

    assert 'const KEY_SLOT = "dsg-one-key-session"' in script
    assert "sessionStorage.getItem(KEY_SLOT)" in script
    assert "sessionStorage.setItem(KEY_SLOT, value)" in script
    assert "async function resumeSession()" in script
    assert "resumeSession();" in script
    assert '$("connection").textContent = "RECONNECTING"' in script
    assert "localStorage" not in script


def test_dashboard_activation_connects_automatically_and_disconnect_clears_tab_session() -> None:
    script = Path("web/customer-dashboard/dashboard.js").read_text(encoding="utf-8")

    assert "rememberSessionKey(body.api_key)" in script
    assert "await loadWithCurrentKey();" in script
    assert "Account activated and connected automatically" in script
    assert 'clearCredentials({ forgetSession: true })' in script
    assert "Credentials cleared from this browser tab" in script


def test_page_navigation_keeps_tab_scoped_session_for_seamless_return() -> None:
    script = Path("web/customer-dashboard/dashboard.js").read_text(encoding="utf-8")

    pagehide = script.split('window.addEventListener("pagehide"', 1)[1].split('$("firstProof")', 1)[0]
    assert "forgetSessionKey" not in pagehide
    assert "sessionStorage.removeItem" not in pagehide