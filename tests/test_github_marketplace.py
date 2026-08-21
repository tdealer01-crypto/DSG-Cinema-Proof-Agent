from __future__ import annotations

import hashlib
import hmac
import json
import re

import pytest
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from revenue.accounts import AccountStore
from revenue.engine import RevenueEngine
from revenue.github_marketplace import (
    GithubMarketplaceStore,
    map_github_plan,
    reset_store,
    verify_github_signature,
)
from revenue.ledger import LedgerStore
from revenue.pricing import get_plan

client = TestClient(cinema_main.app)
WEBHOOK_SECRET = "g" * 48
OAUTH_SECRET = "o" * 48


@pytest.fixture
def marketplace(monkeypatch, tmp_path):
    account_path = tmp_path / "accounts.json"
    ledger_path = tmp_path / "ledger.json"
    marketplace_path = tmp_path / "github-marketplace.json"

    monkeypatch.setenv("DSG_REVENUE_ACCOUNT_STORE", str(account_path))
    monkeypatch.setenv("DSG_REVENUE_LEDGER_STORE", str(ledger_path))
    monkeypatch.setenv("DSG_GITHUB_MARKETPLACE_STORE", str(marketplace_path))
    monkeypatch.setenv("GITHUB_MARKETPLACE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("GITHUB_MARKETPLACE_OAUTH_CLIENT_ID", "Iv1.test-client")
    monkeypatch.setenv("GITHUB_MARKETPLACE_OAUTH_CLIENT_SECRET", OAUTH_SECRET)

    engine = RevenueEngine(
        accounts=AccountStore(str(account_path)),
        ledger=LedgerStore(str(ledger_path)),
        enforce=True,
        enforcement_ready=True,
    )
    billing.reset_engine(engine)
    store = reset_store(GithubMarketplaceStore(str(marketplace_path)))
    yield engine, store
    billing.reset_engine(RevenueEngine(enforce=False))
    reset_store(GithubMarketplaceStore())


def signed_headers(payload: bytes, delivery: str = "delivery-1") -> dict[str, str]:
    signature = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={signature}",
        "X-GitHub-Event": "marketplace_purchase",
        "X-GitHub-Delivery": delivery,
    }


def purchase_body(action: str = "purchased", plan: str = "Pro") -> dict:
    return {
        "action": action,
        "marketplace_purchase": {
            "account": {"id": 4242, "login": "acme-labs", "type": "Organization"},
            "plan": {"name": plan},
            "billing_cycle": "monthly",
            "effective_date": "2026-08-21T00:00:00Z",
        },
    }


def post_purchase(action: str = "purchased", plan: str = "Pro", delivery: str = "delivery-1"):
    payload = json.dumps(purchase_body(action, plan), separators=(",", ":")).encode()
    return client.post(
        "/marketplace/github/webhook",
        content=payload,
        headers=signed_headers(payload, delivery),
    )


def test_marketplace_plan_mapping_is_fail_closed():
    assert map_github_plan("Enterprise") == "github_enterprise"
    assert map_github_plan("Production") == "github_business"
    assert map_github_plan("Business") == "github_business"
    assert map_github_plan("Team") == "github_pro"
    assert map_github_plan("Pro") == "github_pro"
    assert map_github_plan("Solo") == "github_pro"
    assert map_github_plan("something-new") == "github_free"


@pytest.mark.parametrize(
    ("plan_key", "quota"),
    [
        ("github_free", 1_000),
        ("github_pro", 10_000),
        ("github_business", 100_000),
        ("github_enterprise", 1_000_000),
    ],
)
def test_marketplace_plans_preserve_control_plane_quotas_without_stripe_rebilling(plan_key, quota):
    plan = get_plan(plan_key)
    assert plan.included_units == quota
    assert plan.hard_cap_units == quota
    assert plan.unit_price_micros == 0
    assert plan.base_price_micros == 0
    assert plan.requires_linked_payment is False


def test_github_signature_verification_rejects_tampering():
    payload = b'{"action":"purchased"}'
    signature = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    verify_github_signature(payload, f"sha256={signature}", WEBHOOK_SECRET)
    with pytest.raises(ValueError, match="did not match"):
        verify_github_signature(payload + b"x", f"sha256={signature}", WEBHOOK_SECRET)


def test_purchase_creates_paid_entitlement_and_duplicate_is_idempotent(marketplace):
    engine, store = marketplace

    response = post_purchase("purchased", "Pro", "delivery-pro")
    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert response.json()["entitlement"]["plan_key"] == "github_pro"

    link = store.link_for(4242)
    assert link is not None
    account = engine.accounts.get(link["account_id"])
    assert account is not None
    assert account.plan == "github_pro"
    assert account.channel == "github_marketplace"
    assert account.payment_linked is False
    assert account.hard_cap_units == 10_000

    duplicate = post_purchase("purchased", "Pro", "delivery-pro")
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert store.link_for(4242)["account_id"] == account.account_id


def test_invalid_signature_changes_nothing(marketplace):
    _engine, store = marketplace
    payload = json.dumps(purchase_body(), separators=(",", ":")).encode()
    response = client.post(
        "/marketplace/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Event": "marketplace_purchase",
            "X-GitHub-Delivery": "bad-delivery",
        },
    )
    assert response.status_code == 401
    assert store.link_for(4242) is None


def test_unknown_plan_falls_to_free_instead_of_over_entitling(marketplace):
    engine, store = marketplace
    response = post_purchase("purchased", "Future Ultra Unlimited", "unknown-plan")
    assert response.status_code == 200
    assert response.json()["entitlement"]["plan_key"] == "github_free"
    account = engine.accounts.get(store.link_for(4242)["account_id"])
    assert account.plan == "github_free"
    assert account.hard_cap_units == 1_000


def test_changed_and_cancelled_events_update_same_account(marketplace):
    engine, store = marketplace
    assert post_purchase("purchased", "Pro", "p1").status_code == 200
    first_id = store.link_for(4242)["account_id"]

    changed = post_purchase("changed", "Business", "p2")
    assert changed.status_code == 200
    assert store.link_for(4242)["account_id"] == first_id
    assert engine.accounts.get(first_id).plan == "github_business"
    assert engine.accounts.get(first_id).hard_cap_units == 100_000

    cancelled = post_purchase("cancelled", "Business", "p3")
    assert cancelled.status_code == 200
    assert store.link_for(4242)["account_id"] == first_id
    assert engine.accounts.get(first_id).plan == "github_free"
    assert engine.accounts.get(first_id).status == "active"
    assert engine.accounts.get(first_id).hard_cap_units == 1_000


def test_pending_change_never_grants_future_plan_early(marketplace):
    engine, store = marketplace
    assert post_purchase("purchased", "Pro", "p1").status_code == 200
    account_id = store.link_for(4242)["account_id"]

    pending = post_purchase("pending_change", "Enterprise", "p2")
    assert pending.status_code == 200
    assert pending.json()["pending"] is True
    assert engine.accounts.get(account_id).plan == "github_pro"
    assert store.link_for(4242)["pending_plan_name"] == "Enterprise"


def test_github_account_never_sends_a_stripe_meter_request(marketplace, monkeypatch):
    engine, store = marketplace
    assert post_purchase("purchased", "Pro", "stripe-proof").status_code == 200
    link = store.link_for(4242)
    old_account = engine.accounts.get(link["account_id"])

    # Onboarding rotates the otherwise undisclosed webhook-created key.
    link, api_key = store.issue_browser_key(
        github_account_id=4242,
        github_login="acme-labs",
        installation_id=99,
    )
    assert engine.accounts.get(old_account.account_id).status == "suspended"
    account = engine.accounts.authenticate(api_key)
    assert account is not None
    assert account.account_id == link["account_id"]

    called = False

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("GitHub Marketplace proof must not open a Stripe HTTP client")

    monkeypatch.setattr("revenue.stripe_sync.httpx.AsyncClient", ExplodingClient)
    authorization = engine.authorize(api_key, "verified_execution")
    assert authorization.authorized is True
    entry, created = engine.record_usage(
        authorization,
        sku="verified_execution",
        receipt={
            "verified": True,
            "verification": "VERIFIED_GLOBAL_OPTIMUM",
            "proof_hash": "a" * 64,
            "context_hash": "b" * 64,
        },
        channel="github",
    )
    assert created is True
    assert entry.amount_micros == 0
    assert called is False


def test_callback_verifies_installation_then_rotates_key(marketplace, monkeypatch):
    engine, store = marketplace
    assert post_purchase("purchased", "Business", "before-oauth").status_code == 200
    old_account_id = store.link_for(4242)["account_id"]

    async def fake_exchange(code: str) -> str:
        assert code == "oauth-code"
        return "ghu_test_token"

    async def fake_installation(token: str, installation_id: int):
        assert token == "ghu_test_token"
        assert installation_id == 9001
        return 4242, "acme-labs"

    monkeypatch.setattr("revenue.github_marketplace._exchange_oauth_code", fake_exchange)
    monkeypatch.setattr("revenue.github_marketplace._verified_installation", fake_installation)

    response = client.get(
        "/marketplace/github/callback",
        params={"code": "oauth-code", "installation_id": 9001},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("no-store")
    assert "location.replace('/app')" in response.text

    match = re.search(r"dsg_live_[0-9a-f]{16}_[0-9a-f]{48}", response.text)
    assert match is not None
    new_account = engine.accounts.authenticate(match.group(0))
    assert new_account is not None
    assert new_account.plan == "github_business"
    assert new_account.hard_cap_units == 100_000
    assert store.link_for(4242)["account_id"] == new_account.account_id
    assert engine.accounts.get(old_account_id).status == "suspended"


def test_marketplace_status_says_exactly_what_is_missing(marketplace):
    response = client.get("/marketplace/github/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["checks"] == {
        "durable_store": "PASS",
        "webhook_secret": "PASS",
        "oauth_client_id": "PASS",
        "oauth_client_secret": "PASS",
    }
    assert body["truth_boundary"]["github_collects_subscription_payment"] is True
    assert body["truth_boundary"]["cinema_stripe_rebilling"] is False
