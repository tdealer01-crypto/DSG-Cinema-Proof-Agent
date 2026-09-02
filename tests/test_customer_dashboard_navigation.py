from pathlib import Path


def test_customer_dashboard_exposes_one_click_connect_agent_flow() -> None:
    html = Path("web/customer-dashboard/index.html").read_text(encoding="utf-8")

    assert ">Connect Agent<" in html
    assert "/remote-browser/connect-agent?auto=1" in html
    assert "Cinema handles Free Evaluation, Remote ON, secure pairing, and MCP verification automatically" in html
    assert "Plan approval remains explicit" in html
    assert "Activate free account" in html
