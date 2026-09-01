from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _html() -> str:
    return (ROOT / "azure-landing" / "dsg-live.html").read_text(encoding="utf-8")


def test_dsg_live_landing_source_and_deploy_copy_match():
    assert (ROOT / "azure-landing" / "dsg-live.html").read_bytes() == (
        ROOT / "landing" / "dsg-live.html"
    ).read_bytes()


def test_dsg_live_landing_exposes_the_approved_customer_flow():
    html = _html()
    required = [
        "Install → Authorize → Live",
        "LIVE ACTION",
        "PLAN CHECK",
        "DSG EFFECT",
        "WHY",
        "EVIDENCE",
        "DEFAULT · OBSERVE",
        "OPT-IN · ENFORCE",
        "PASS / OUTSIDE PLAN / MISSING PERMISSION",
        "CONTINUE · EXECUTE · WAIT · STOP",
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
