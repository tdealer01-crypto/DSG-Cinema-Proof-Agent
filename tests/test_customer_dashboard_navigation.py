from pathlib import Path


def test_customer_dashboard_exposes_connect_agent_flow() -> None:
    html = Path("web/customer-dashboard/index.html").read_text(encoding="utf-8")

    assert "Connect Agent / Create Free Key" in html
    assert "/remote-browser/connect-agent" in html
    assert "Activate free account" in html
