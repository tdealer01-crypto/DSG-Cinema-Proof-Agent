from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            self.links.add(href)


def landing_html() -> str:
    return (ROOT / "azure-landing" / "index.html").read_text(encoding="utf-8")


def test_azure_and_render_landings_share_one_user_flow():
    assert (ROOT / "azure-landing" / "index.html").read_bytes() == (
        ROOT / "landing" / "index.html"
    ).read_bytes()


def test_landing_contains_live_proof_flow_and_fail_closed_contract():
    html = landing_html()
    required = [
        "Run live verification",
        "VERIFY_BASE+'/verify/evaluate'",
        "VERIFIED_GLOBAL_OPTIMUM",
        "validReceipt",
        "Download receipt JSON",
        "const button=event.currentTarget",
        "button.textContent='Proof hash copied'",
        "[hidden]{display:none!important}",
        "Verification unavailable — no decision issued.",
        "Checkout status: NOT VERIFIED / NOT LINKED",
        "const DELIVERY_CHANNEL=HOST.endsWith('.web.core.windows.net')?'azure':HOST.endsWith('.onrender.com')?'render':'api'",
        "channel:DELIVERY_CHANNEL",
        "agent_identity:`dsg-${DELIVERY_CHANNEL}-landing`",
    ]
    for value in required:
        assert value in html
    assert "event.currentTarget.textContent" not in html
    assert "channel:'azure'" not in html
    assert "channel:'api',activation_id" not in html


def test_landing_exposes_every_supported_marketplace_status_truthfully():
    html = landing_html()
    expected = {
        "GitHub Marketplace": "LIVE V1.1.0",
        "Stripe Apps": "PACKAGE V2.7 READY",
        "OpenAI Skills": "READY TO SUBMIT",
        "Microsoft Marketplace": "CONTACT-ME PACK READY",
        "AWS Marketplace": "BLOCKED EXTERNAL",
        "JetBrains Marketplace": "SPEC ONLY",
        "Direct API": "LIVE",
    }
    for channel, status in expected.items():
        assert channel in html
        assert status in html


def test_landing_links_current_packages_and_live_surfaces():
    parser = LinkParser()
    parser.feed(landing_html())
    required_links = {
        "https://github.com/marketplace/actions/dsg-secure-deploy-gate",
        "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/tree/main/marketplace/github-action-v2",
        "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/tree/main/stripe-app",
        "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/tree/main/marketplace/openai-plugin",
        "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/azure/offer.md",
        "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/aws/offer.md",
        "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main/marketplace/jetbrains/offer.md",
        "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/docs",
    }
    assert required_links <= parser.links


def test_launch_manifest_matches_repository_artifacts():
    manifest = json.loads(
        (ROOT / "marketplace" / "launch-manifest.json").read_text(encoding="utf-8")
    )
    deployment = json.loads(
        (ROOT / ".deployment" / "azure-3d-landing.json").read_text(encoding="utf-8")
    )
    statuses = {item["channel"]: item["status"] for item in manifest["channels"]}
    assert statuses == {
        "GitHub Marketplace Action": "LIVE_V1",
        "Stripe Apps Marketplace": "PACKAGE_V2_7_PREPARED",
        "Microsoft Marketplace": "SUBMISSION_PACK_PREPARED",
        "AWS Marketplace": "BLOCKED_EXTERNAL",
        "JetBrains Marketplace": "SPEC_ONLY",
        "OpenAI Skills": "READY_FOR_EXTERNAL_SUBMIT",
        "Direct API": "LIVE",
    }
    assert manifest["product"]["checkout_status"] == "NOT_VERIFIED_NOT_LINKED"
    assert manifest["product"]["public_landing"] == deployment["site_url"]
    assert deployment["status"] == "PASS"

    official_landing = manifest["product"]["public_landing"]
    assert all(
        item.get("website_url") == official_landing
        for item in manifest["channels"]
    )

    stripe_app = json.loads(
        (ROOT / "stripe-app" / "stripe-app.template.json").read_text(encoding="utf-8")
    )
    assert stripe_app["websiteUrl"] == official_landing
    openai_listing = (
        ROOT / "marketplace" / "openai-plugin" / "submission" / "LISTING.md"
    ).read_text(encoding="utf-8")
    assert f"**Website:** {official_landing}" in openai_listing

    for item in manifest["channels"]:
        package = item.get("package") or item.get("v2_package")
        if package:
            assert (ROOT / package).exists(), package


def test_request_flows_warn_against_secrets_and_false_checkout():
    paid = (ROOT / ".github" / "ISSUE_TEMPLATE" / "verified-proof-request.yml").read_text(
        encoding="utf-8"
    )
    enterprise = (ROOT / ".github" / "ISSUE_TEMPLATE" / "enterprise-inquiry.yml").read_text(
        encoding="utf-8"
    )
    assert "does not create a charge" in paid
    assert "Do not paste credentials" in paid
    assert "no secrets" in enterprise


def test_every_prepared_marketplace_uses_the_official_product_website():
    manifest = json.loads(
        (ROOT / "marketplace" / "launch-manifest.json").read_text(encoding="utf-8")
    )
    official = manifest["product"]["public_landing"]
    listing_files = [
        ROOT / "marketplace" / "github" / "offer.md",
        ROOT / "marketplace" / "stripe" / "offer.md",
        ROOT / "marketplace" / "azure" / "offer.md",
        ROOT / "marketplace" / "aws" / "offer.md",
        ROOT / "marketplace" / "jetbrains" / "offer.md",
        ROOT / "marketplace" / "openai-plugin" / "submission" / "LISTING.md",
        ROOT / "stripe-app" / "stripe-app.template.json",
    ]
    for path in listing_files:
        assert official in path.read_text(encoding="utf-8"), path


def test_retired_runtime_links_are_absent_from_current_surfaces():
    current_files = [
        ROOT / "azure-landing" / "index.html",
        ROOT / "landing" / "index.html",
        ROOT / "marketplace" / "launch-manifest.json",
    ]
    retired = [
        "tdealer01-crypto-dsg-control-plane",
        "proofgate-github-action",
        "dsg-stripe-app.vercel.app",
    ]
    for path in current_files:
        content = path.read_text(encoding="utf-8")
        for value in retired:
            assert value not in content, (path, value)


def test_production_deployments_have_one_coordinated_owner():
    azure = (ROOT / ".github" / "workflows" / "deploy-azure-3d-landing.yml").read_text(
        encoding="utf-8"
    )
    cinema = (ROOT / ".github" / "workflows" / "deploy-cinema-production.yml").read_text(
        encoding="utf-8"
    )
    z3 = (ROOT / ".github" / "workflows" / "deploy-z3-azure.yml").read_text(
        encoding="utf-8"
    )
    assert "    environment: production" in azure
    assert "SOLVE_CODE=$(curl" in cinema
    assert "Cinema production did not converge to the new authenticated revision" in cinema
    assert "CONFIGURED_SOLVER_SHARED_SECRET" in cinema
    assert "DSG_SOLVER_SHARED_SECRET is required" in cinema
    assert "--revision-suffix \"z3-${GITHUB_RUN_ATTEMPT}-${GITHUB_RUN_ID}\"" in cinema
    assert "--revision-suffix \"cinema-${GITHUB_RUN_ATTEMPT}-${GITHUB_RUN_ID}\"" in cinema
    assert 'Z3_SECRET_ARGS+=("solver-previous-secret=' not in cinema
    assert "Z3_SECRET=$(openssl rand -hex 32)" not in cinema
    assert "  push:\n    branches: [main]" not in z3
    assert "deploy-cinema-production.yml" in z3
