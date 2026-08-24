from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from revenue.accounts import AccountStore
from revenue.engine import RevenueEngine
from revenue.ledger import LedgerStore
from revenue.stripe_marketplace import (
    StripeMarketplaceStore,
    _decode_state,
    _encode_state,
    _exchange_oauth_code,
    _oauth_exchange_secret,
    reset_store,
)

client = TestClient(cinema_main.app)
SECRET_KEY = "sk_live_" + ("s" * 48)
APP_ID = "pics.dsg.governance"
CLIENT_ID = "ca_test_client"
ACCOUNT = "acct_1TestInstaller"
SIGNING_SECRET = "absec_" + ("a" * 48)
TEST_OAUTH_SECRET = "sk_test_" + ("t" * 48)
SANDBOX_OAUTH_SECRET = "sk_test_" + ("b" * 48)


@pytest.fixture
def marketplace(monkeypatch, tmp_path):
    account_path = tmp_path / "accounts.json"
    ledger_path = tmp_path / "ledger.json"
    marketplace_path = tmp_path / "stripe-marketplace.json"

    monkeypatch.setenv("DSG_REVENUE_ACCOUNT_STORE", str(account_path))
    monkeypatch.setenv("DSG_REVENUE_LEDGER_STORE", str(ledger_path))
    monkeypatch.setenv("DSG_STRIPE_MARKETPLACE_STORE", str(marketplace_path))
    monkeypatch.setenv("STRIPE_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("STRIPE_APP_ID", APP_ID)
    monkeypatch.setenv("STRIPE_APP_OAUTH_CLIENT_ID", CLIENT_ID)
    for link_type in ("live", "test", "sandbox"):
        monkeypatch.setenv(
            f"STRIPE_APP_OAUTH_{link_type.upper()}_REDIRECT_URI",
            f"https://cinema.example.test/marketplace/stripe/callback/{link_type}",
        )
    monkeypatch.setenv(
        "STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL",
        f"https://marketplace.stripe.com/oauth/v2/authorize?client_id={CLIENT_ID}",
    )
    monkeypatch.setenv(
        "STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL",
        f"https://marketplace.stripe.com/oauth/v2/authorize?client_id={CLIENT_ID}",
    )
    monkeypatch.setenv(
        "STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL",
        f"https://marketplace.stripe.com/oauth/v2/authorize?client_id={CLIENT_ID}",
    )
    monkeypatch.setenv("STRIPE_APP_OAUTH_TEST_SECRET_KEY", TEST_OAUTH_SECRET)
    monkeypatch.setenv("STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY", SANDBOX_OAUTH_SECRET)
    monkeypatch.setenv("STRIPE_APP_SIGNING_SECRET", SIGNING_SECRET)

    engine = RevenueEngine(
        accounts=AccountStore(str(account_path)),
        ledger=LedgerStore(str(ledger_path)),
        enforce=True,
        enforcement_ready=True,
    )
    billing.reset_engine(engine)
    store = reset_store(StripeMarketplaceStore(str(marketplace_path)))
    yield engine, store
    billing.reset_engine(RevenueEngine(enforce=False))
    reset_store(StripeMarketplaceStore())


def patch_oauth(monkeypatch, *, account: str = ACCOUNT, livemode: bool = True, seen: dict | None = None):
    async def fake_exchange(code: str, link_type: str) -> dict:
        if seen is not None:
            seen["code"] = code
            seen["link_type"] = link_type
        return {
            "access_token": "sk_test_installer_token",
            "stripe_user_id": account,
            "livemode": livemode,
        }

    async def fake_account(token: str, stripe_user_id: str):
        assert token == "sk_test_installer_token"
        assert stripe_user_id == account
        return "Acme Labs"

    monkeypatch.setattr("revenue.stripe_marketplace._exchange_oauth_code", fake_exchange)
    monkeypatch.setattr("revenue.stripe_marketplace._verified_account", fake_account)


def test_status_reports_ready_when_configured(marketplace):
    response = client.get("/marketplace/stripe/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["checks"] == {
        "durable_store": "PASS",
        "app_id": "PASS",
        "oauth_client_id": "PASS",
        "oauth_live_redirect_uri": "PASS",
        "oauth_test_redirect_uri": "PASS",
        "oauth_sandbox_redirect_uri": "PASS",
        "oauth_live_authorize_url": "PASS",
        "oauth_test_authorize_url": "PASS",
        "oauth_sandbox_authorize_url": "PASS",
        "oauth_live_secret_key": "PASS",
        "oauth_test_secret_key": "PASS",
        "oauth_sandbox_secret_key": "PASS",
        "app_signing_secret": "PASS",
        "secret_key": "PASS",
    }
    assert body["truth_boundary"]["install_grants_free_plan_only"] is True
    assert body["truth_boundary"]["callback_parameter_trusted_alone"] is False
    assert body["truth_boundary"]["oauth_state_single_use"] is True
    assert body["truth_boundary"]["entitlement_mode_bound"] is True


def test_status_names_missing_configuration(marketplace, monkeypatch):
    monkeypatch.delenv("STRIPE_APP_OAUTH_CLIENT_ID")
    body = client.get("/marketplace/stripe/status").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["checks"]["oauth_client_id"] == "MISSING"


def test_status_and_setup_reject_an_untrusted_redirect_uri(marketplace, monkeypatch):
    monkeypatch.setenv("STRIPE_APP_OAUTH_LIVE_REDIRECT_URI", "http://localhost/callback")
    body = client.get("/marketplace/stripe/status").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["checks"]["oauth_live_redirect_uri"] == "MISSING"
    response = client.get("/marketplace/stripe/setup", follow_redirects=False)
    assert response.status_code == 503


def test_status_requires_dashboard_sandbox_authorize_url(marketplace, monkeypatch):
    monkeypatch.delenv("STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL")
    body = client.get("/marketplace/stripe/status").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["checks"]["oauth_sandbox_authorize_url"] == "MISSING"
    response = client.get(
        "/marketplace/stripe/setup?link_type=sandbox",
        follow_redirects=False,
    )
    assert response.status_code == 503


def test_status_requires_dashboard_live_authorize_url(marketplace, monkeypatch):
    monkeypatch.delenv("STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL")
    body = client.get("/marketplace/stripe/status").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["checks"]["oauth_live_authorize_url"] == "MISSING"
    response = client.get("/marketplace/stripe/setup", follow_redirects=False)
    assert response.status_code == 503


def test_status_rejects_generic_live_authorize_url(marketplace, monkeypatch):
    monkeypatch.setenv(
        "STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL",
        "https://marketplace.stripe.com/oauth/v2/authorize",
    )
    body = client.get("/marketplace/stripe/status").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["checks"]["oauth_live_authorize_url"] == "MISSING"


def test_status_requires_test_mode_key_and_authorize_url(marketplace, monkeypatch):
    monkeypatch.delenv("STRIPE_APP_OAUTH_TEST_SECRET_KEY")
    monkeypatch.delenv("STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL")
    body = client.get("/marketplace/stripe/status").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["checks"]["oauth_test_secret_key"] == "MISSING"
    assert body["checks"]["oauth_test_authorize_url"] == "MISSING"


def test_status_requires_app_signing_secret(marketplace, monkeypatch):
    monkeypatch.delenv("STRIPE_APP_SIGNING_SECRET")
    body = client.get("/marketplace/stripe/status").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["checks"]["app_signing_secret"] == "MISSING"


def _signed_request(payload: dict, secret: str = SIGNING_SECRET) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, f"t={timestamp},v1={digest}"


def _stripe_ui_payload(account_id: str = ACCOUNT, **overrides) -> dict:
    payload = {
        "stripe_account_id": account_id,
        "livemode": False,
        "object_type": "charge",
        "object_id": "ch_signed_test",
        "amount_cents": 5000,
        "currency": "usd",
        "stripe_status": "succeeded",
        "risk_level": "low",
        "user_id": "usr_signed_test",
        "account_id": account_id,
    }
    payload.update(overrides)
    return payload


def test_signed_ui_request_uses_linked_entitlement(marketplace, monkeypatch):
    engine, store = marketplace
    store.issue_browser_key(
        stripe_user_id=ACCOUNT,
        display_name="Stripe App — Acme Labs",
        livemode=False,
    )

    async def fake_z3_request(method, path, payload=None):
        assert method == "POST"
        assert path == "/solve"
        return 200, {
            "verified": True,
            "verification": "VERIFIED_GLOBAL_OPTIMUM",
            "witness": [1, 0, 0],
            "energy_exact": "-100",
            "proof_hash": "a" * 64,
            "request_hash": "b" * 64,
        }

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)
    raw, signature = _signed_request(_stripe_ui_payload())
    response = client.post(
        "/stripe/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "ALLOW"
    assert response.json()["billing"]["metered"] is True
    entries = engine.ledger.entries()
    assert len(entries) == 1
    assert entries[0].channel == "stripe_marketplace"


def test_signed_ui_request_refuses_forged_signature(marketplace):
    _, store = marketplace
    store.issue_browser_key(
        stripe_user_id=ACCOUNT,
        display_name="Stripe App — Acme Labs",
        livemode=False,
    )
    raw, signature = _signed_request(_stripe_ui_payload(), secret="wrong-" + ("x" * 48))
    response = client.post(
        "/stripe/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "INVALID_STRIPE_APP_SIGNATURE"


def test_signed_ui_request_refuses_account_mismatch(marketplace):
    raw, signature = _signed_request(
        _stripe_ui_payload(account_id="acct_signed_other", stripe_account_id=ACCOUNT)
    )
    response = client.post(
        "/stripe/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "signed Stripe account does not match stripe_account_id"


def test_signed_ui_request_refuses_unlinked_account(marketplace):
    raw, signature = _signed_request(_stripe_ui_payload(account_id="acct_unlinked_test"))
    response = client.post(
        "/stripe/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "STRIPE_APP_NOT_LINKED"


def test_signed_ui_request_requires_mode(marketplace):
    _, store = marketplace
    store.issue_browser_key(
        stripe_user_id=ACCOUNT,
        display_name="Stripe App — Acme Labs",
        livemode=False,
    )
    payload = _stripe_ui_payload()
    payload.pop("livemode")
    raw, signature = _signed_request(payload)
    response = client.post(
        "/stripe/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "signed Stripe App requests require livemode"


def test_signed_ui_request_does_not_cross_test_and_live_links(marketplace):
    _, store = marketplace
    store.issue_browser_key(
        stripe_user_id=ACCOUNT,
        display_name="Stripe App — Acme Labs test",
        livemode=False,
    )
    raw, signature = _signed_request(_stripe_ui_payload(livemode=True))
    response = client.post(
        "/stripe/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "STRIPE_APP_NOT_LINKED"


def test_signed_ui_request_fails_closed_without_signing_secret(marketplace, monkeypatch):
    monkeypatch.delenv("STRIPE_APP_SIGNING_SECRET")
    raw, signature = _signed_request(_stripe_ui_payload())
    response = client.post(
        "/stripe/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": signature},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "STRIPE_APP_SIGNING_SECRET_MISSING"


def test_setup_explains_install_before_leaving_for_stripe(marketplace):
    response = client.get("/marketplace/stripe/setup", follow_redirects=False)
    assert response.status_code == 200
    assert "Connect DSG Governance Gate" in response.text
    assert "free 25-proof monthly entitlement" in response.text
    assert "never captures, refunds, or blocks" in response.text
    assert "/marketplace/stripe/setup?link_type=live&amp;begin=true" in response.text
    assert marketplace[1].snapshot()["oauth_states"] == {}


def test_setup_redirects_to_stripe_authorize_with_signed_state(marketplace):
    response = client.get(
        "/marketplace/stripe/setup?link_type=live&begin=true",
        follow_redirects=False,
    )
    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "marketplace.stripe.com"
    assert parsed.path == "/oauth/v2/authorize"
    query = parse_qs(parsed.query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [
        "https://cinema.example.test/marketplace/stripe/callback/live"
    ]
    state = _decode_state(query["state"][0])
    assert state["nonce"]
    assert state["link_type"] == "live"


def test_setup_binds_sandbox_link_type_into_state(marketplace):
    response = client.get(
        "/marketplace/stripe/setup?link_type=sandbox&begin=true",
        follow_redirects=False,
    )
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert _decode_state(query["state"][0])["link_type"] == "sandbox"
    assert query["redirect_uri"] == [
        "https://cinema.example.test/marketplace/stripe/callback/sandbox"
    ]


def test_oauth_exchange_secret_matches_link_type(marketplace):
    assert _oauth_exchange_secret("live") == SECRET_KEY
    assert _oauth_exchange_secret("test") == TEST_OAUTH_SECRET
    assert _oauth_exchange_secret("sandbox") == SANDBOX_OAUTH_SECRET


def test_oauth_exchange_uses_http_basic_with_the_mode_key(marketplace, monkeypatch):
    from revenue import stripe_marketplace

    seen: dict = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "access_token": "sk_test_installer_token",
                "stripe_user_id": ACCOUNT,
                "livemode": False,
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            seen["url"] = url
            seen.update(kwargs)
            return Response()

    monkeypatch.setattr(stripe_marketplace.httpx, "AsyncClient", lambda **kwargs: Client())
    body = asyncio.run(_exchange_oauth_code("ac_external_test", "sandbox"))
    assert body["stripe_user_id"] == ACCOUNT
    assert seen["auth"] == (SANDBOX_OAUTH_SECRET, "")
    assert seen["data"] == {
        "code": "ac_external_test",
        "grant_type": "authorization_code",
    }
    assert "client_secret" not in seen["data"]


def test_callback_verifies_account_then_hands_key_to_console(marketplace, monkeypatch):
    engine, store = marketplace
    seen: dict = {}
    patch_oauth(monkeypatch, seen=seen)

    response = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "oauth-code", "state": _encode_state()},
    )
    assert response.status_code == 200
    assert seen["code"] == "oauth-code"
    assert seen["link_type"] == "live"
    assert response.headers["cache-control"].startswith("no-store")
    assert "localStorage.setItem('dsg-one-key'" in response.text
    assert "location.replace('/app')" in response.text

    match = re.search(r"dsg_live_[0-9a-f]{16}_[0-9a-f]{48}", response.text)
    assert match is not None
    account = engine.accounts.authenticate(match.group(0))
    assert account is not None
    assert account.plan == "free"
    assert account.hard_cap_units == 25
    assert store.link_for(ACCOUNT, livemode=True)["account_id"] == account.account_id


def test_reinstall_rotates_the_key_and_suspends_the_previous_account(marketplace, monkeypatch):
    engine, store = marketplace
    patch_oauth(monkeypatch)

    first = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "code-1", "state": _encode_state()},
    )
    assert first.status_code == 200
    old_account_id = store.link_for(ACCOUNT, livemode=True)["account_id"]

    second = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "code-2", "state": _encode_state()},
    )
    assert second.status_code == 200
    new_account_id = store.link_for(ACCOUNT, livemode=True)["account_id"]

    assert new_account_id != old_account_id
    assert engine.accounts.get(old_account_id).status == "suspended"


def test_live_and_test_installations_keep_separate_entitlements(marketplace):
    engine, store = marketplace
    live, _ = store.issue_browser_key(
        stripe_user_id=ACCOUNT,
        display_name="Stripe App — Acme Labs live",
        livemode=True,
    )
    test, _ = store.issue_browser_key(
        stripe_user_id=ACCOUNT,
        display_name="Stripe App — Acme Labs test",
        livemode=False,
    )

    assert live["account_id"] != test["account_id"]
    assert store.link_for(ACCOUNT, livemode=True)["account_id"] == live["account_id"]
    assert store.link_for(ACCOUNT, livemode=False)["account_id"] == test["account_id"]
    assert engine.accounts.get(live["account_id"]).status == "active"
    assert engine.accounts.get(test["account_id"]).status == "active"


def test_test_mode_install_issues_a_test_key(marketplace, monkeypatch):
    patch_oauth(monkeypatch, livemode=False)
    response = client.get(
        "/marketplace/stripe/callback/test",
        params={"code": "oauth-code", "state": _encode_state("test")},
    )
    assert response.status_code == 200
    assert re.search(r"dsg_test_[0-9a-f]{16}_[0-9a-f]{48}", response.text) is not None


def test_callback_refuses_a_forged_state(marketplace, monkeypatch):
    patch_oauth(monkeypatch)
    forged = _encode_state().split(".")[0] + "." + ("0" * 64)
    response = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "oauth-code", "state": forged},
    )
    assert response.status_code == 400
    assert "state signature" in response.json()["detail"]


def test_callback_refuses_a_state_for_another_mode(marketplace, monkeypatch):
    patch_oauth(monkeypatch)
    response = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "oauth-code", "state": _encode_state("test")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "OAuth state did not match the callback mode"


def test_callback_consumes_state_exactly_once(marketplace, monkeypatch):
    patch_oauth(monkeypatch)
    state = _encode_state()
    first = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "oauth-code-1", "state": state},
    )
    second = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "oauth-code-2", "state": state},
    )
    assert first.status_code == 200
    assert second.status_code == 400
    assert "already used" in second.json()["detail"]


def test_callback_requires_a_code(marketplace):
    assert client.get("/marketplace/stripe/callback/live").status_code == 400


def test_callback_requires_state_before_exchanging_code(marketplace, monkeypatch):
    patch_oauth(monkeypatch)
    response = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "oauth-code"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "state is required"


def test_denied_install_renders_a_page_rather_than_failing(marketplace):
    response = client.get(
        "/marketplace/stripe/callback/live",
        params={"error": "access_denied", "error_description": "user said no"},
    )
    assert response.status_code == 200
    assert "user said no" in response.text
    assert "dsg-one-key" not in response.text


def test_account_mismatch_is_refused(marketplace, monkeypatch):
    """The stripe_user_id beside the token is never trusted on its own."""
    from revenue import stripe_marketplace

    async def fake_exchange(code: str, link_type: str) -> dict:
        assert link_type == "live"
        return {
            "access_token": "sk_test_installer_token",
            "stripe_user_id": ACCOUNT,
            "livemode": True,
        }

    monkeypatch.setattr(stripe_marketplace, "_exchange_oauth_code", fake_exchange)

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "acct_SomeoneElse", "livemode": True}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(stripe_marketplace.httpx, "AsyncClient", lambda **kwargs: Client())

    response = client.get(
        "/marketplace/stripe/callback/live",
        params={"code": "oauth-code", "state": _encode_state()},
    )
    assert response.status_code == 403
    assert "did not match" in response.json()["detail"]
