from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/dashboard"


def _html() -> str:
    return (ROOT / "azure-landing" / "dsg-live.html").read_text(encoding="utf-8")


def test_dsg_live_landing_source_and_deploy_copy_match():
    assert (ROOT / "azure-landing" / "dsg-live.html").read_bytes() == (
        ROOT / "landing" / "dsg-live.html"
    ).read_bytes()


def test_dsg_live_landing_points_customers_to_one_dashboard():
    html = _html()
    assert DASHBOARD in html
    assert html.count(DASHBOARD) >= 4
    assert "Open Live Dashboard" in html
    assert "Launch customer dashboard" in html
    assert "Use the product from one URL" in html
    assert "The normal customer flow stays on" in html
    assert "Agent Chat" in html
    assert "User + Agent" in html


def test_dsg_live_landing_exposes_current_five_monitor_views():
    html = _html()
    for value in (
        "ACTION",
        "PLAN ALIGNMENT",
        "PERMISSION",
        "EVIDENCE",
        "EXECUTION / AUDIT",
    ):
        assert value in html
    assert "USER / AGENT · current action" in html
    assert "PASS / WAITING_PERMISSION" in html
    assert "RUNNING / SUCCESS / BLOCKED / FAILED" in html


def test_dsg_live_landing_keeps_plugin_and_control_paths():
    html = _html()
    required = [
        "Install → Authorize → Live",
        "DEFAULT · OBSERVE",
        "OPT-IN · ENFORCE",
        "Replay is verification only",
        "copilot plugin marketplace add tdealer01-crypto/DSG-Cinema-Proof-Agent",
        "copilot plugin install dsg-governance@dsg-agent-plugins",
        "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/live/api/contract",
    ]
    for value in required:
        assert value in html


def test_dsg_live_landing_keeps_truth_and_replay_boundaries_explicit():
    html = _html()
    assert "Observe does not silently convert a policy BLOCK into an ALLOW" in html
    assert "Enforcement is opt-in" in html
    assert "never re-sends the action" in html
    assert "Sandbox re-execution" not in html
    assert "Re-run production" not in html
    assert "Execute Replay" not in html
    assert "SOC 2 certified" not in html
    assert "ISO 27001 certified" not in html
