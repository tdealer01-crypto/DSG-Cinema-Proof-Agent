from __future__ import annotations

from fastapi.testclient import TestClient

import cinema_main


client = TestClient(cinema_main.app)


def test_mcp_endpoint_is_full_selectable_and_has_mobile_copy_fallback():
    response = client.get("/dashboard")
    assert response.status_code == 200
    page = response.text

    assert 'id="mcpEndpoint"' in page
    assert 'readonly' in page
    assert 'inputmode="url"' in page
    assert 'id="copyMcpEndpoint"' in page
    assert "location.origin + '/mcp'" in page
    assert "navigator.clipboard.writeText" in page
    assert "document.execCommand('copy')" in page
    assert "setSelectionRange(0, input.value.length)" in page
    assert "long-press" in page


def test_mcp_copy_failure_keeps_the_real_url_visible_and_selected():
    response = client.get("/dashboard")
    page = response.text

    assert "input.value = endpointUrl();" in page
    assert "selectEndpoint(input);" in page
    assert "Copy was blocked by this browser" in page
    assert "MCP endpoint copied." in page
