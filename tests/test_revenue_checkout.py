from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from revenue import checkout
from revenue.engine import RevenueEngine
from revenue.pricing import catalog_snapshot
from revenue.stripe_sync import apply_webhook_event, config_from_env


client = TestClient(cinema_main.app)


@pytest.fixture
def checkout_account(monkeypatch):
    engine = billing.reset_engine(RevenueEngine(enforce=False))
    account, api_key = engine.accounts.issue(
        display_name="Checkout Test",
        plan="free",
        channel="api",
        mode="live",
    )

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_checkout_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_checkout_test")
    monkeypatch.setenv("STRIPE_PRODUCT_ID", "prod_dsg_metered")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_dsg_metered")
    monkeypatch.setenv("STRIPE_METER_ID", "mtr_dsg")
    monkeypatch.setenv("STRIPE_WEBHOOK_ENDPOINT_ID", "we_dsg")
    monkeypatch.setenv(
        "STRIPE_WEBHOOK_ENDPOINT_URL",
        "https://cinema.example.test/billing/webhook/stripe",
    )
    monkeypatch.setenv(
        "DSG_CHECKOUT_RETURN_URL",
        "https://dsg.example.test/pricing",
    )

    async def verified_catalog(_config):
        return {
            "verified": True,
            "livemode": True,
            "checks": {
                "product": "PASS",
                "price": "PASS",
                "meter": "PASS",
                "webhook": "PASS",
            },
        }

    monkeypatch.setattr(checkout, "verify_operational_link", verified_catalog)
    yield engine, account, api_key
    billing.reset_engine(RevenueEngine(enforce=False))


def test_checkout_rejects_missing_or_invalid_api_key(checkout_account):
    response = client.post(
        "/billing/checkout/session",
        json={"plan": "metered", "checkout_id": "checkout-001"},
    )
    assert response.status_code == 401

    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": "not-a-dsg-key"},
        json={"plan": "metered", "checkout_id": "checkout-002"},
    )
    assert response.status_code == 401


def test_checkout_rejects_non_self_serve_catalog_plans(checkout_account, monkeypatch):
    _engine, _account, api_key = checkout_account
    snapshot = catalog_snapshot()
    assert [plan["plan"] for plan in snapshot["plans"] if plan["self_serve_checkout"]] == [
        "metered"
    ]

    async def must_not_verify_stripe(*args, **kwargs):
        raise AssertionError("Stripe must not be touched for an ineligible plan")

    monkeypatch.setattr(checkout, "verify_operational_link", must_not_verify_stripe)
    for plan in ("free", "team", "enterprise"):
        response = client.post(
            "/billing/checkout/session",
            headers={"X-DSG-API-Key": api_key},
            json={"plan": plan, "checkout_id": f"checkout-{plan}"},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "PLAN_NOT_SELF_SERVE"

    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": api_key},
        json={"plan": "unknown", "checkout_id": "checkout-unknown"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "UNKNOWN_PLAN"


def test_checkout_authenticates_before_disclosing_plan_policy(checkout_account):
    response = client.post(
        "/billing/checkout/session",
        json={"plan": "team", "checkout_id": "checkout-no-auth"},
    )
    assert response.status_code == 401


def test_checkout_fails_closed_until_live_stripe_catalog_is_verified(
    checkout_account, monkeypatch
):
    _engine, _account, api_key = checkout_account
    calls: list[str] = []

    async def unverified_catalog(_config):
        return {
            "verified": False,
            "livemode": True,
            "checks": {"price": "MISMATCH"},
        }

    async def must_not_call_stripe(*args, **kwargs):
        calls.append("stripe")
        raise AssertionError("Stripe mutation must not run before verification")

    monkeypatch.setattr(checkout, "verify_operational_link", unverified_catalog)
    monkeypatch.setattr(checkout, "_stripe_post", must_not_call_stripe)

    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": api_key},
        json={"plan": "metered", "checkout_id": "checkout-003"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == billing.CONFIGURATION_INCOMPLETE
    assert calls == []


def test_checkout_creates_customer_and_session_without_granting_entitlement(
    checkout_account, monkeypatch
):
    engine, account, api_key = checkout_account
    calls: list[tuple[str, dict[str, str], str]] = []

    async def fake_stripe_post(
        _config,
        path: str,
        *,
        data: dict[str, str],
        idempotency_key: str,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        calls.append((path, dict(data), idempotency_key))
        if path == "/v1/customers":
            return {"id": "cus_dsg_checkout"}
        if path == "/v1/checkout/sessions":
            return {
                "id": "cs_live_dsg_checkout",
                "url": "https://checkout.stripe.com/c/pay/cs_live_dsg_checkout",
            }
        raise AssertionError(path)

    monkeypatch.setattr(checkout, "_stripe_post", fake_stripe_post)

    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": api_key},
        json={"plan": "metered", "checkout_id": "checkout-004"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == checkout.CHECKOUT_STATE_CREATED
    assert body["entitled"] is False
    assert body["requested_plan"] == "metered"
    assert body["account"]["plan"] == "free"
    assert body["account"]["payment_linked"] is False

    current = engine.accounts.get(account.account_id)
    assert current is not None
    assert current.stripe_customer_id == "cus_dsg_checkout"
    assert current.plan == "free"
    assert current.payment_linked is False

    assert [path for path, _, _ in calls] == [
        "/v1/customers",
        "/v1/checkout/sessions",
    ]
    session_data = calls[1][1]
    assert session_data["mode"] == "subscription"
    assert session_data["customer"] == "cus_dsg_checkout"
    assert session_data["line_items[0][price]"] == "price_dsg_metered"
    assert "line_items[0][quantity]" not in session_data
    assert session_data["metadata[dsg_account_id]"] == account.account_id
    assert session_data["metadata[dsg_product_id]"] == "prod_dsg_metered"
    assert session_data["metadata[dsg_price_id]"] == "price_dsg_metered"
    assert session_data["metadata[dsg_plan]"] == "metered"
    assert session_data["subscription_data[metadata][dsg_plan]"] == "metered"
    assert "checkout=success" in session_data["success_url"]
    assert "session_id=" in session_data["success_url"]
    assert "checkout=cancelled" in session_data["cancel_url"]


def test_signed_scoped_subscription_event_is_what_promotes_plan(
    checkout_account, monkeypatch
):
    engine, account, api_key = checkout_account

    async def fake_stripe_post(
        _config,
        path: str,
        *,
        data: dict[str, str],
        idempotency_key: str,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        if path == "/v1/customers":
            return {"id": "cus_dsg_webhook"}
        return {
            "id": "cs_live_dsg_webhook",
            "url": "https://checkout.stripe.com/c/pay/cs_live_dsg_webhook",
        }

    monkeypatch.setattr(checkout, "_stripe_post", fake_stripe_post)

    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": api_key},
        json={"plan": "metered", "checkout_id": "checkout-005"},
    )
    assert response.status_code == 201
    assert engine.accounts.get(account.account_id).plan == "free"

    config = config_from_env()
    event = {
        "id": "evt_subscription_created",
        "type": "customer.subscription.created",
        "created": 1_787_000_000,
        "livemode": True,
        "data": {
            "object": {
                "id": "sub_dsg_metered",
                "customer": "cus_dsg_webhook",
                "status": "active",
                "metadata": {"dsg_plan": "metered"},
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_dsg_metered",
                                "product": "prod_dsg_metered",
                            }
                        }
                    ]
                },
            }
        },
    }
    result = apply_webhook_event(event, engine.accounts, config)
    assert result["applied"] is True

    promoted = engine.accounts.get(account.account_id)
    assert promoted is not None
    assert promoted.plan == "metered"
    assert promoted.payment_linked is True
    assert promoted.stripe_subscription_id == "sub_dsg_metered"


def test_checkout_reuses_existing_stripe_customer(checkout_account, monkeypatch):
    engine, account, api_key = checkout_account
    engine.accounts.update(account.account_id, stripe_customer_id="cus_existing")
    paths: list[str] = []

    async def fake_stripe_post(
        _config,
        path: str,
        *,
        data: dict[str, str],
        idempotency_key: str,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        paths.append(path)
        assert data["customer"] == "cus_existing"
        return {
            "id": "cs_live_existing",
            "url": "https://checkout.stripe.com/c/pay/cs_live_existing",
        }

    monkeypatch.setattr(checkout, "_stripe_post", fake_stripe_post)

    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": api_key},
        json={"plan": "metered", "checkout_id": "checkout-006"},
    )
    assert response.status_code == 201
    assert paths == ["/v1/checkout/sessions"]


def test_checkout_does_not_rebill_an_already_entitled_account(
    checkout_account, monkeypatch
):
    engine, account, api_key = checkout_account
    engine.accounts.update(
        account.account_id,
        plan="metered",
        payment_linked=True,
        stripe_customer_id="cus_paid",
    )

    async def must_not_call_stripe(*args, **kwargs):
        raise AssertionError("already-entitled account must not create checkout")

    monkeypatch.setattr(checkout, "_stripe_post", must_not_call_stripe)

    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": api_key},
        json={"plan": "metered", "checkout_id": "checkout-007"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "ALREADY_ENTITLED"


def test_billing_portal_requires_an_existing_stripe_customer(checkout_account):
    _engine, _account, api_key = checkout_account
    response = client.post(
        "/billing/portal/session",
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STRIPE_CUSTOMER_REQUIRED"


def test_billing_portal_returns_a_trusted_stripe_url(checkout_account, monkeypatch):
    engine, account, api_key = checkout_account
    engine.accounts.update(
        account.account_id,
        plan="metered",
        payment_linked=True,
        stripe_customer_id="cus_portal",
    )
    calls: list[tuple[str, dict[str, str]]] = []

    async def fake_stripe_post(
        _config,
        path: str,
        *,
        data: dict[str, str],
        idempotency_key: str,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        calls.append((path, dict(data)))
        return {
            "id": "bps_portal",
            "url": "https://billing.stripe.com/p/session/test_portal",
        }

    monkeypatch.setattr(checkout, "_stripe_post", fake_stripe_post)
    response = client.post(
        "/billing/portal/session",
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 201
    assert response.json()["portal_url"].startswith("https://billing.stripe.com/")
    assert calls == [
        (
            "/v1/billing_portal/sessions",
            {
                "customer": "cus_portal",
                "return_url": "https://dsg.example.test/pricing?portal=return",
            },
        )
    ]


def test_billing_portal_rejects_untrusted_stripe_url(checkout_account, monkeypatch):
    engine, account, api_key = checkout_account
    engine.accounts.update(account.account_id, stripe_customer_id="cus_portal_bad")

    async def fake_stripe_post(*args, **kwargs):
        return {"id": "bps_bad", "url": "https://evil.example/phish"}

    monkeypatch.setattr(checkout, "_stripe_post", fake_stripe_post)
    response = client.post(
        "/billing/portal/session",
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "STRIPE_PORTAL_INVALID_RESPONSE"
