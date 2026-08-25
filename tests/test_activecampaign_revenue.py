"""ActiveCampaign revenue integration is consent-gated and payment fail-closed."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from revenue import marketing_api
from revenue.accounts import Account
from revenue.activecampaign_sync import (
    ActiveCampaignConfig,
    EVENT_CHECKOUT_STARTED,
    EVENT_LEAD,
    sync_account_event,
)
from revenue.engine import RevenueEngine
from revenue.marketing_profiles import MarketingProfile, MarketingProfileStore

client = TestClient(cinema_main.app)
ADMIN_SECRET = "M" * 48


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setenv("DSG_REVENUE_ADMIN_SECRET", ADMIN_SECRET)
    monkeypatch.delenv("ACTIVECAMPAIGN_API_URL", raising=False)
    monkeypatch.delenv("ACTIVECAMPAIGN_API_TOKEN", raising=False)
    billing.reset_engine(RevenueEngine(enforce=False))
    marketing_api.reset_store(MarketingProfileStore())
    yield
    billing.reset_engine(RevenueEngine(enforce=False))
    marketing_api.reset_store(MarketingProfileStore())


def activate() -> tuple[str, str]:
    response = client.post(
        "/billing/activate",
        json={
            "channel": "dashboard",
            "activation_id": "marketing-test-001",
            "display_name": "Marketing Test",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["api_key"], body["account"]["account_id"]


def test_marketing_profile_persists_but_does_not_echo_email(tmp_path):
    path = tmp_path / "marketing-profiles.json"
    store = MarketingProfileStore(str(path))
    profile = store.upsert(
        account_id="acct_dsg_test",
        email="Person@Example.COM",
        marketing_consent=True,
        source="dashboard",
    )
    assert profile.email == "person@example.com"
    assert "email" not in profile.public_view()
    assert profile.public_view()["has_email"] is True

    reloaded = MarketingProfileStore(str(path)).get("acct_dsg_test")
    assert reloaded is not None
    assert reloaded.email == "person@example.com"
    assert reloaded.marketing_consent is True


def test_identify_records_profile_without_changing_entitlement():
    key, account_id = activate()
    before = billing.get_engine().accounts.get(account_id)
    assert before is not None
    assert before.plan == "free"
    assert before.payment_linked is False

    response = client.post(
        "/billing/marketing/identify",
        headers={"X-DSG-API-Key": key},
        json={
            "email": "lead@example.com",
            "marketing_consent": True,
            "source": "dashboard",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["account_id"] == account_id
    assert body["profile"]["marketing_consent"] is True
    assert body["profile"]["has_email"] is True
    assert "email" not in body["profile"]
    assert body["marketing_sync"]["sync_state"] == "PENDING_CONFIGURATION"

    after = billing.get_engine().accounts.get(account_id)
    assert after is not None
    assert after.plan == "free"
    assert after.payment_linked is False


def test_client_cannot_assert_payment_confirmed():
    key, _ = activate()
    response = client.post(
        "/billing/marketing/event",
        headers={"X-DSG-API-Key": key},
        json={"event": "payment_confirmed"},
    )
    assert response.status_code == 422


def test_reconcile_does_not_promote_payment_linked_without_paid_invoice(monkeypatch):
    _, account_id = activate()
    profile = marketing_api.get_store().upsert(
        account_id=account_id,
        email="trial@example.com",
        marketing_consent=True,
        source="dashboard",
    )
    account = billing.get_engine().accounts.get(account_id)
    assert account is not None
    billing.get_engine().accounts.import_account(replace(account, payment_linked=True))

    calls = []

    async def fake_sync(account, profile, *, event, source=None, config=None):
        calls.append((account.account_id, event))
        return {"sync_state": "SYNCED", "event": event}

    monkeypatch.setattr(marketing_api, "sync_account_event", fake_sync)
    response = client.post(
        "/billing/marketing/reconcile",
        headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["checked"] == 1
    assert body["eligible_from_paid_invoice"] == 0
    assert body["synced"] == 0
    assert calls == []
    assert profile.marketing_consent is True


def test_reconcile_promotes_only_after_scoped_paid_invoice_evidence(monkeypatch):
    _, account_id = activate()
    marketing_api.get_store().upsert(
        account_id=account_id,
        email="paid@example.com",
        marketing_consent=True,
        source="dashboard",
    )
    account = billing.get_engine().accounts.get(account_id)
    assert account is not None
    billing.get_engine().accounts.import_account(
        replace(
            account,
            payment_linked=True,
            stripe_paid_invoice_ids=["in_dsg_paid_001"],
        )
    )

    calls = []

    async def fake_sync(account, profile, *, event, source=None, config=None):
        calls.append((account.account_id, event, profile.email))
        return {"sync_state": "SYNCED", "event": event}

    monkeypatch.setattr(marketing_api, "sync_account_event", fake_sync)
    response = client.post(
        "/billing/marketing/reconcile",
        headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["eligible_from_paid_invoice"] == 1
    assert body["synced"] == 1
    assert calls == [(account_id, "payment_confirmed", "paid@example.com")]


def test_sync_writes_dsg_account_id_and_keeps_intent_tags_exclusive(monkeypatch):
    account = Account(
        account_id="acct_dsg_corr_001",
        display_name="Correlation Test",
        channel="dashboard",
    )
    profile = MarketingProfile(
        account_id=account.account_id,
        email="intent@example.com",
        marketing_consent=True,
        source="dashboard",
    )
    config = ActiveCampaignConfig(
        api_url="https://example.activehosted.com",
        api_token="test-token",
    )

    requests = []

    async def fake_request(client, config, method, path, *, json=None, params=None, allowed_statuses=frozenset({200, 201})):
        requests.append((method, path, json, params))
        if method == "POST" and path == "/api/3/contact/sync":
            fields = json["contact"]["fieldValues"]
            assert {"field": "5", "value": account.account_id} in fields
            return {"contact": {"id": "42"}}
        if method == "GET" and path == "/api/3/contactLists":
            return {"contactLists": [{"id": "77", "contact": "42", "list": "4", "status": "1"}]}
        if method == "GET" and path == "/api/3/tags":
            name = params["search"]
            mapping = {
                "dsg-intent-low": "1",
                "dsg-intent-medium": "2",
                "dsg-intent-high": "3",
                "dsg-checkout-started": "5",
                "dsg-checkout-abandoned": "9",
            }
            return {"tags": [{"id": mapping[name], "tag": name}]}
        if method == "DELETE" and path == "/api/3/contactTags/101":
            return {}
        if method == "GET" and path == "/api/3/contacts/42/contactTags":
            return {"contactTags": [{"id": "101", "contact": "42", "tag": "1"}]}
        if method == "POST" and path == "/api/3/contactTags":
            return {"contactTag": {"id": "202"}}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr("revenue.activecampaign_sync._request", fake_request)
    result = asyncio.run(
        sync_account_event(
            account,
            profile,
            event=EVENT_CHECKOUT_STARTED,
            config=config,
        )
    )
    assert result["sync_state"] == "SYNCED"
    assert "dsg-intent-high" in result["tags_added"]
    assert "dsg-checkout-started" in result["tags_added"]
    assert "dsg-intent-low" in result["tags_removed"]
    # Existing active list membership is reused; no duplicate POST is sent.
    assert not any(
        method == "POST" and path == "/api/3/contactLists"
        for method, path, _, _ in requests
    )


def test_no_consent_never_calls_activecampaign(monkeypatch):
    account = Account(account_id="acct_dsg_no_consent", display_name="No Consent")
    profile = MarketingProfile(
        account_id=account.account_id,
        email="private@example.com",
        marketing_consent=False,
        source="dashboard",
    )

    class BombClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ActiveCampaign network must not be opened without consent")

    monkeypatch.setattr("revenue.activecampaign_sync.httpx.AsyncClient", BombClient)
    result = asyncio.run(
        sync_account_event(
            account,
            profile,
            event=EVENT_LEAD,
            config=ActiveCampaignConfig(
                api_url="https://example.activehosted.com",
                api_token="token",
            ),
        )
    )
    assert result["sync_state"] == "SKIPPED_NO_CONSENT"
