from __future__ import annotations

from fastapi.testclient import TestClient

import cinema_main


client = TestClient(cinema_main.app)


def test_mcp_endpoint_is_full_selectable_and_copy_logic_is_csp_safe():
    response = client.get("/dashboard")
    assert response.status_code == 200
    page = response.text

    assert 'id="mcpEndpoint"' in page
    assert 'readonly' in page
    assert 'inputmode="url"' in page
    assert 'id="copyMcpEndpoint"' in page
    assert '<script src="/dashboard-assets/dashboard.js"></script>' in page
    assert "navigator.clipboard.writeText" not in page
    assert "document.execCommand" not in page

    script = client.get("/dashboard-assets/dashboard.js")
    assert script.status_code == 200
    body = script.text
    assert 'location.origin + "/mcp"' in body
    assert 'navigator.clipboard.writeText' in body
    assert 'document.execCommand("copy")' in body
    assert 'setSelectionRange(0, input.value.length)' in body
    assert 'wireAdvancedConnectionCopy();' in body


def test_mcp_copy_failure_keeps_the_real_url_visible_and_selected():
    script = client.get("/dashboard-assets/dashboard.js")
    body = script.text

    assert 'endpoint.value = endpointUrl();' in body
    assert 'selectCopyInput(input);' in body
    assert 'Copy was blocked. The value is selected' in body
    assert 'MCP endpoint copied.' in body
    assert 'Short-lived pairing token copied.' in body


def test_dashboard_csp_allows_external_script_but_not_inline_script():
    response = client.get("/dashboard")
    csp = response.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp
    assert '<script>' not in response.text
