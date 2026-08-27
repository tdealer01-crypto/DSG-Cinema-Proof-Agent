"""Coverage for governed ActiveCampaign projection mutation boundaries."""

from __future__ import annotations

import asyncio

from revenue import activecampaign_projection_sync as projection_sync
from revenue.accounts import Account
from revenue.activecampaign_projection import project_activecampaign
from revenue.activecampaign_sync import ActiveCampaignConfig
from revenue.intent import evaluate_intent
from revenue.lifecycle import RevenueState
from revenue.marketing_profiles import MarketingProfile


def test_projection_sync_applies_exact_projected_tags(monkeypatch):
    account = Account(
        account_id="acct_projection_happy",
        display_name="Projection Happy Path",
        channel="dashboard",
    )
    profile = MarketingProfile(
        account_id=account.account_id,
        email="projection@example.com",
        marketing_consent=True,
        source="dashboard",
    )
    projection = project_activecampaign(
        state=RevenueState.CHECKOUT_STARTED,
        intent=evaluate_intent(["checkout_started"]),
        marketing_consent=True,
        lifecycle_facts=["checkout_started"],
    )
    config = ActiveCampaignConfig(
        api_url="https://example.activehosted.com",
        api_token="test-token",
    )

    requests: list[tuple[str, str, object]] = []

    async def fake_request(
        client,
        selected_config,
        method,
        path,
        *,
        json=None,
        params=None,
        allowed_statuses=frozenset({200, 201}),
    ):
        del client, params, allowed_statuses
        assert selected_config is config
        requests.append((method, path, json))
        if method == "POST" and path == "/api/3/contact/sync":
            fields = json["contact"]["fieldValues"]
            assert {"field": str(config.account_id_field_id), "value": account.account_id} in fields
            assert {"field": str(config.lead_source_field_id), "value": "dashboard"} in fields
            assert {"field": str(config.last_high_intent_field_id), "value": "Checkout started"} in fields
            return {"contact": {"id": "42"}}
        if method == "DELETE" and path == "/api/3/contactTags/900":
            return {}
        if method == "POST" and path == "/api/3/contactTags":
            return {"contactTag": {"id": "901"}}
        raise AssertionError(f"unexpected projection request: {method} {path}")

    async def fake_ensure_list_subscription(client, selected_config, contact_id):
        del client
        assert selected_config is config
        assert contact_id == 42

    async def fake_resolve_tag_ids(client, selected_config, names):
        del client
        assert selected_config is config
        assert set(names) == set(projection.desired_tags) | set(projection.remove_tags)
        return {
            "dsg-checkout-started": 101,
            "dsg-checkout-abandoned": 102,
            "dsg-intent-high": 103,
            "dsg-intent-medium": 104,
            "dsg-intent-low": 105,
        }

    async def fake_current_tag_relations(client, selected_config, contact_id):
        del client
        assert selected_config is config
        assert contact_id == 42
        return {102: 900}

    monkeypatch.setattr(projection_sync, "_request", fake_request)
    monkeypatch.setattr(
        projection_sync,
        "_ensure_list_subscription",
        fake_ensure_list_subscription,
    )
    monkeypatch.setattr(projection_sync, "_resolve_tag_ids", fake_resolve_tag_ids)
    monkeypatch.setattr(
        projection_sync,
        "_current_tag_relations",
        fake_current_tag_relations,
    )

    result = asyncio.run(
        projection_sync.sync_account_projection(
            account,
            profile,
            projection=projection,
            source="dashboard",
            signal="checkout_started",
            config=config,
        )
    )

    assert result["sync_state"] == "SYNCED"
    assert result["contact_id"] == 42
    assert result["correlation"] == {"dsg_account_id": account.account_id}
    assert "dsg-checkout-abandoned" in result["tags_removed"]
    assert "dsg-checkout-started" in result["tags_added"]
    assert "dsg-intent-high" in result["tags_added"]
    assert any(method == "DELETE" for method, _, _ in requests)
    assert any(method == "POST" and path == "/api/3/contactTags" for method, path, _ in requests)
