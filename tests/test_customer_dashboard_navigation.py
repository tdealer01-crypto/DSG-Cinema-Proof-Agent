from pathlib import Path


def test_customer_dashboard_exposes_one_click_connect_agent_flow() -> None:
    html = Path("web/customer-dashboard/index.html").read_text(encoding="utf-8")
    script = Path("web/customer-dashboard/dashboard.js").read_text(encoding="utf-8")

    assert ">Connect Agent<" in html
    assert 'id="connectAgent"' in html
    assert "/remote-browser/connect-agent?auto=1" not in html
    assert "/remote-browser/connect-agent?auto=1" not in script
    assert 'api("/remote-browser/enable"' in script
    assert 'api("/remote-browser/agent-pair"' in script
    assert "Pairing is ready" in script
    assert "real agent client contacts /mcp" in script
    assert "without leaving this dashboard" in html
    assert "Advanced agent connection" in html
    assert "Activate free account" in html
