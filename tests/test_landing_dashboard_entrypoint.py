from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/dashboard"


def test_primary_landing_points_to_customer_dashboard_and_mirrors_azure_copy():
    source = ROOT / "landing" / "index.html"
    azure = ROOT / "azure-landing" / "index.html"
    assert source.read_bytes() == azure.read_bytes()

    html = azure.read_text(encoding="utf-8")
    assert DASHBOARD in html
    assert 'class="navcta" href="' + DASHBOARD + '">Open Dashboard</a>' in html
    assert 'href="' + DASHBOARD + '">Open customer dashboard</a>' in html
    assert "Agent Chat" in html
    assert "Shared Browser session for User + Agent" in html
    assert "five live governance views" in html


def test_primary_landing_keeps_live_proof_and_truth_boundaries():
    html = (ROOT / "azure-landing" / "index.html").read_text(encoding="utf-8")
    for marker in (
        "AZURE UI → CINEMA → EXACT Z3 → PROOF RECEIPT",
        "Run live verification",
        "Download receipt JSON",
        "VERIFIED_GLOBAL_OPTIMUM",
        "Checkout status: NOT VERIFIED / NOT LINKED",
    ):
        assert marker in html
    assert "It is not SOC 2, ISO, legal, regulatory, or third-party certification." in html
