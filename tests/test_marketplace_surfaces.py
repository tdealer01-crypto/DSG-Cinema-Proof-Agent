from __future__ import annotations

import json
import re
import struct
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


def test_landing_closes_the_self_serve_checkout_loop_without_claiming_redirect_payment():
    html = landing_html()
    required = [
        'id="checkoutButton"',
        "'/billing/checkout/session'",
        "plan:'metered'",
        "body.state!=='CHECKOUT_CREATED_NOT_ENTITLED'",
        "body.entitled!==false",
        "'/billing/subscription'",
        "subscription.subscription_active&&subscription.payment_linked",
        "Waiting for signed Stripe webhook confirmation",
        "only Z3-verified proofs are billable",
        'set("badgeTeam","CONTACT SALES","warn")',
    ]
    for value in required:
        assert value in html
    assert "Request billing access" not in html
    assert 'set("badgeTeam",live?"READY"' not in html


def test_landing_exposes_every_supported_marketplace_status_truthfully():
    html = landing_html()
    expected = {
        "GitHub Marketplace": "LIVE V1.1.0",
        "Stripe Apps": "V2.7.1 UPLOAD READY",
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
        "Stripe Apps Marketplace": "READY_FOR_EXTERNAL_UPLOAD",
        "Microsoft Marketplace": "SUBMISSION_PACK_PREPARED",
        "AWS Marketplace": "BLOCKED_EXTERNAL",
        "JetBrains Marketplace": "SPEC_ONLY",
        "OpenAI Skills": "READY_FOR_EXTERNAL_SUBMIT",
        "Direct API": "LIVE",
    }
    # This snapshot was raised only after the production route returned LINKED,
    # LINKED_VERIFIED, charges_enabled, and all operational checks PASS. A
    # Payment Link is a separate Stripe object and remains explicitly unclaimed.
    assert manifest["product"]["checkout_status"] == "LINKED"
    assert manifest["revenue_automation"]["verified_live"]["stripe_link_state"] == "LINKED_VERIFIED"
    assert manifest["product"]["public_landing"] == deployment["site_url"]
    assert deployment["status"] == "PASS"

    stripe_channel = next(
        item for item in manifest["channels"] if item["channel"] == "Stripe Apps Marketplace"
    )
    assert stripe_channel["production_status"] == "ACTION_REQUIRED"
    assert stripe_channel["submission_artifact"]["artifact_id"] == 9508761420
    assert stripe_channel["submission_artifact"]["digest"].startswith("sha256:")

    official_landing = manifest["product"]["public_landing"]
    assert all(
        item.get("website_url") == official_landing
        for item in manifest["channels"]
    )

    stripe_listing = (ROOT / "marketplace" / "stripe" / "LISTING.md").read_text(
        encoding="utf-8"
    )
    assert f"**Website:** {official_landing}" in stripe_listing
    openai_listing = (
        ROOT / "marketplace" / "openai-plugin" / "submission" / "LISTING.md"
    ).read_text(encoding="utf-8")
    assert f"**Website:** {official_landing}" in openai_listing

    for item in manifest["channels"]:
        package = item.get("package") or item.get("v2_package")
        if package:
            assert (ROOT / package).exists(), package


def test_production_probe_reports_stripe_marketplace_readiness():
    workflow = (
        ROOT / ".github" / "workflows" / "probe-cinema-azure.yml"
    ).read_text(encoding="utf-8")
    required = [
        '"https://$HOST/marketplace/stripe/status"',
        'STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL',
        'STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL',
        'STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL',
        'STRIPE_APP_OAUTH_TEST_SECRET_KEY',
        'STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY',
        'STRIPE_APP_SIGNING_SECRET',
        'stripe_marketplace: {',
        'Current production marketplace/stripe/status is unavailable or malformed.',
    ]
    for value in required:
        assert value in workflow


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
        ROOT / "marketplace" / "stripe" / "LISTING.md",
    ]
    for path in listing_files:
        assert official in path.read_text(encoding="utf-8"), path


def test_stripe_listing_and_icon_meet_objective_submission_limits():
    listing = (ROOT / "marketplace" / "stripe" / "LISTING.md").read_text(
        encoding="utf-8"
    )
    app_name = re.search(r"^- \*\*App name:\*\* (.+)$", listing, re.MULTILINE)
    subtitle = re.search(r"^- \*\*Subtitle:\*\* (.+)$", listing, re.MULTILINE)
    assert app_name is not None and len(app_name.group(1)) <= 35
    assert subtitle is not None and len(subtitle.group(1)) <= 80
    assert not re.search(
        r"\b(?:stripe|app|free|paid|rak|generator|api key|authenticator)\b",
        app_name.group(1),
        re.IGNORECASE,
    )

    about = listing.split("**About field (under 1,000 characters):**", 1)[1]
    about = " ".join(about.split("\n\n", 1)[0].split())
    assert 1 <= len(about) <= 1000
    assert "**Expected support response:** Within 2 business days." in listing
    assert "**Supported language:** English" in listing
    assert "**BLOCKED — Based in:**" in listing
    assert "exact Public Install URL" in listing
    assert "Settings" in listing
    assert "No external DSG credentials are required" in listing
    assert "$0.10 per Stripe policy decision proof" in listing
    assert "The panel verifies\n   the current object automatically" in listing
    assert "Verify with exact proof" not in listing

    feature_blocks = re.findall(
        r"^### Feature \d+\n\n(.*?)(?=^### Feature \d+|^## Pricing)",
        listing,
        re.MULTILINE | re.DOTALL,
    )
    assert len(feature_blocks) == 3
    for feature in feature_blocks:
        title = re.search(r"^- \*\*Title:\*\* (.+)$", feature, re.MULTILINE)
        assert title is not None and len(title.group(1)) <= 80
        description = feature.split("- **Description:**", 1)[1].split(
            "\n- **Image:**", 1
        )[0]
        normalized = " ".join(description.split())
        assert 1 <= len(normalized) <= 300
        assert "- **Image:** **BLOCKED**" in feature

    icon = (ROOT / "stripe-app" / "icon.png").read_bytes()
    assert len(icon) <= 10 * 1024 * 1024
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", icon[16:24]) == (300, 300)


def test_stripe_review_documents_cover_current_submission_gates():
    checklist = (
        ROOT / "marketplace" / "stripe" / "SUBMISSION_CHECKLIST.md"
    ).read_text(encoding="utf-8")
    support = (ROOT / "marketplace" / "stripe" / "SUPPORT.md").read_text(
        encoding="utf-8"
    )
    privacy = (ROOT / "marketplace" / "stripe" / "PRIVACY.md").read_text(
        encoding="utf-8"
    )
    for gate in (
        "account is activated",
        "not a Connect-enabled platform account",
        "only app published",
        "business purpose is not prohibited",
        "Public Install URL",
        "all three key features",
        "Review and publish",
        "click **Publish**",
    ):
        assert gate in checklist
    assert "within 2 business days" in support
    assert "confirm that each monitored route receives it" in support
    assert "**Effective date:** August 24, 2026" in privacy


def test_public_pricing_and_marketplace_claims_match_the_live_catalog():
    html = landing_html()
    assert "$0.05 <small>/ general proof receipt</small>" in html
    assert "Stripe Dashboard policy decisions: $0.10 per verified proof" in html
    assert "Marketplace-deployed" not in html
    assert "Stripe Apps and OpenAI Skills are prepared packages pending external review" in html


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
    assert 'Z3_SECRET_ARGS+=("solver-previous-secret=' in cinema
    assert "NOT_VERIFIED_NOT_LINKED" in cinema
    assert ".stripe.operational_checks.webhook == \"PASS\"" in cinema
    assert "Z3_SECRET=$(openssl rand -hex 32)" not in cinema
    assert "  push:\n    branches: [main]" not in z3
    assert "deploy-cinema-production.yml" in z3
    deploy_cinema = cinema.split("- name: Deploy Cinema production", 1)[1].split(
        "- name: Verify production Cinema", 1
    )[0]
    cinema_url_assignment = 'CINEMA_URL="https://$CINEMA_FQDN"'
    live_callback = (
        '"STRIPE_APP_OAUTH_LIVE_REDIRECT_URI='
        '$CINEMA_URL/marketplace/stripe/callback/live"'
    )
    assert deploy_cinema.index(cinema_url_assignment) < deploy_cinema.index(live_callback)
    assert "CONTAINER_ENV_DOMAIN=$(az containerapp env show" in deploy_cinema
