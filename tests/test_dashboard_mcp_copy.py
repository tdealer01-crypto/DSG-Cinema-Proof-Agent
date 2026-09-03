from __future__ import annotations

from fastapi.testclient import TestClient

import cinema_main


client = TestClient(cinema_main.app)


def test_mcp_endpoint_is_visible_readonly_and_copy_logic_is_csp_safe():
    response = client.get("/dashboard")
    assert response.status_code == 200
    page = response.text

    # Keep this regression aligned with the exact sandbox-tested Market-Ready
    # shell rather than adding attributes or legacy IDs that would change its
    # byte-for-byte verified HTML payload.
    assert 'id="mcpEndpoint"' in page
    assert 'readonly' in page
    assert 'id="copyMcp"' in page
    assert '<script src="/config.js"></script>' in page
    assert '<script src="/app.js"></script>' in page
    assert "navigator.clipboard.writeText" not in page
    assert "document.execCommand" not in page

    script = client.get("/app.js")
    assert script.status_code == 200
    body = script.text
    assert '$("mcpEndpoint").value=`${location.origin}${API_BASE}/mcp`' in body
    assert '$("copyMcp").onclick=()=>copyValue($("mcpEndpoint").value)' in body
    assert 'function copyValue(text)' in body
    assert 'navigator.clipboard?.writeText(text)' in body
    assert "document.execCommand" not in body
    assert "eval(" not in body


def test_mcp_copy_failure_keeps_the_real_url_in_the_readonly_field():
    script = client.get("/app.js")
    assert script.status_code == 200
    body = script.text

    # The endpoint value is derived from the current origin and is not replaced
    # on copy failure; only a truthful toast is emitted.
    assert '$("mcpEndpoint").value=`${location.origin}${API_BASE}/mcp`' in body
    assert '$("copyMcp").onclick=()=>copyValue($("mcpEndpoint").value)' in body
    assert 'toast("Copied")' in body
    assert 'toast("Copy blocked by browser")' in body
    assert '$("copyPair").onclick=()=>copyValue($("pairingToken").value)' in body


def test_dashboard_csp_allows_external_script_but_not_inline_script():
    response = client.get("/dashboard")
    csp = response.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp
    assert '<script>' not in response.text
