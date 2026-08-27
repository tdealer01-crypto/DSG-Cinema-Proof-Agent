from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from revenue import checkout
from revenue.accounts import Account
from revenue.engine import RevenueEngine
from revenue.lifecycle import PaymentProof, RevenueState
from revenue.lifecycle_store import LifecycleStateStore
from revenue.marketing_profiles import MarketingProfile
from revenue.revenue_events import EventStatus, RevenueEventStore
from revenue.revenue_pipeline import (
    RevenuePipelineError,
    RevenueSignalPipeline,
    reset_revenue_pipeline,
)
from revenue.signals import RevenueSignal, SignalContractError


client = TestClient(cinema_main.app)


def _account(account_id: str = "acct_dsg_pipeline") -> Account:
    return Account(account_id=account_id, display_name="Pipeline Account")


def _profile(account_id: str = "acct_dsg_pipeline", *, consent: bool = True) -> MarketingProfile:
    return MarketingProfile(
        account_id=account_id,
        email="lead@example.com",
        marketing_consent=consent,
        source="api",
    )


def _pipeline(*, sync_state: str = "SYNCED"):
    calls: list[dict] = []

    async def projection_sync(account, profile, *, projection, source, signal):
        calls.append(
            {
                "account_id": account.account_id,
                "profile": profile,
                "projection": projection,
                "source": source,
                "signal": signal,
            }
        )
        return {"sync_state": sync_state, "projection": projection.public_view()}

    return (
        RevenueSignalPipeline(
            event_store=RevenueEventStore(),
            lifecycle_store=LifecycleStateStore(),
            projection_sync=projection_sync,
        ),
        calls,
    )


@pytest.mark.asyncio
async def test_checkout_signal_uses_legal_path_and_deterministic_high_intent():
    pipeline, calls = _pipeline()
    result = await pipeline.process_signal(
        account=_account(),
        profile=_profile(),
        signal=RevenueSignal.CHECKOUT_STARTED,
        source="stripe_checkout",
        source_event_id="cs_live_pipeline_1",
        payload={"requested_plan": "metered"},
        trusted_source=True,
    )

    assert result["lifecycle"]["state"] == RevenueState.CHECKOUT_STARTED.value
    assert result["intent"]["score"] == 50
    assert result["intent"]["band"] == "HIGH"
    assert result["intent"]["selected_tag"] == "dsg-intent-high"
    assert "dsg-intent-high" in result["projection"]["desired_tags"]
    assert "dsg-checkout-started" in result["projection"]["desired_tags"]
    assert result["event"]["status"] == EventStatus.PROCESSED.value
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_late_earlier_funnel_signal_never_regresses_lifecycle():
    pipeline, _calls = _pipeline()
    account = _account()
    profile = _profile()

    await pipeline.process_signal(
        account=account,
        profile=profile,
        signal=RevenueSignal.CHECKOUT_STARTED,
        source="stripe_checkout",
        source_event_id="cs_live_pipeline_2",
        trusted_source=True,
    )
    result = await pipeline.process_signal(
        account=account,
        profile=profile,
        signal=RevenueSignal.LEAD_CREATED,
        source="api",
        source_event_id="late-lead-1",
        payload={"email_hash": "0" * 64},
    )

    assert result["lifecycle"]["state"] == RevenueState.CHECKOUT_STARTED.value


@pytest.mark.asyncio
async def test_abandonment_fails_closed_without_checkout_truth():
    pipeline, _calls = _pipeline()
    with pytest.raises(RevenuePipelineError, match="requires CHECKOUT_STARTED"):
        await pipeline.process_signal(
            account=_account(),
            profile=_profile(),
            signal=RevenueSignal.CHECKOUT_ABANDONED,
            source="api",
            source_event_id="abandon-without-checkout",
        )

    event = pipeline.events.get(
        source="api", source_event_id="abandon-without-checkout"
    )
    assert event is not None
    assert event.status == EventStatus.FAILED


@pytest.mark.asyncio
async def test_client_cannot_assert_payment_and_non_invoice_proof_is_rejected():
    pipeline, _calls = _pipeline()
    account = _account()

    with pytest.raises(SignalContractError, match="trusted backend"):
        await pipeline.process_signal(
            account=account,
            profile=_profile(),
            signal=RevenueSignal.PAYMENT_CONFIRMED,
            source="client",
            source_event_id="client-paid-1",
            trusted_source=False,
        )

    checkout_proof = PaymentProof(
        account_id=account.account_id,
        source="stripe_checkout_session",
        source_id="cs_live_paid",
        livemode=True,
        status="paid",
        verified=True,
        evidence_ref="stripe:checkout:cs_live_paid",
    )
    with pytest.raises(RevenuePipelineError, match="paid-invoice"):
        await pipeline.process_signal(
            account=account,
            profile=_profile(),
            signal=RevenueSignal.PAYMENT_CONFIRMED,
            source="stripe_webhook",
            source_event_id="evt_wrong_source",
            trusted_source=True,
            payment_proof=checkout_proof,
        )


@pytest.mark.asyncio
async def test_paid_invoice_truth_reaches_customer_without_becoming_intent_score():
    pipeline, _calls = _pipeline()
    account = _account()
    profile = _profile()

    await pipeline.process_signal(
        account=account,
        profile=profile,
        signal=RevenueSignal.CHECKOUT_STARTED,
        source="stripe_checkout",
        source_event_id="cs_live_pipeline_paid",
        trusted_source=True,
    )
    proof = PaymentProof(
        account_id=account.account_id,
        source="stripe_paid_invoice",
        source_id="in_live_pipeline_paid",
        livemode=True,
        status="paid",
        verified=True,
        evidence_ref="stripe-webhook:evt_live_pipeline_paid",
    )
    result = await pipeline.process_signal(
        account=account,
        profile=profile,
        signal=RevenueSignal.PAYMENT_CONFIRMED,
        source="stripe_webhook",
        source_event_id="evt_live_pipeline_paid",
        trusted_source=True,
        payment_proof=proof,
    )

    assert result["lifecycle"]["state"] == RevenueState.CUSTOMER.value
    assert result["intent"]["score"] == 50
    assert "payment_confirmed" not in result["intent"]["scored_events"]
    desired = set(result["projection"]["desired_tags"])
    assert {"dsg-payment-confirmed", "dsg-customer", "dsg-onboarding"} <= desired
    assert not any(tag.startswith("dsg-intent-") for tag in desired)


@pytest.mark.asyncio
async def test_activecampaign_failure_cannot_rollback_dsg_truth_and_replay_is_idempotent():
    pipeline, calls = _pipeline(sync_state="FAILED")
    account = _account()
    kwargs = dict(
        account=account,
        profile=_profile(),
        signal=RevenueSignal.CHECKOUT_STARTED,
        source="stripe_checkout",
        source_event_id="cs_live_ac_failure",
        payload={"requested_plan": "metered"},
        trusted_source=True,
    )

    first = await pipeline.process_signal(**kwargs)
    assert first["marketing_sync"]["sync_state"] == "FAILED"
    assert first["event"]["status"] == EventStatus.PROCESSED.value
    assert pipeline.lifecycle.get(account.account_id).state == RevenueState.CHECKOUT_STARTED
    assert len(calls) == 1

    replay = await pipeline.process_signal(**kwargs)
    assert replay["duplicate"] is True
    assert replay["marketing_sync"]["sync_state"] == "SKIPPED_EVENT_ALREADY_PROCESSED"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_event_evidence_never_contains_raw_payload_pii():
    pipeline, _calls = _pipeline()
    raw_email = "private-address@example.com"
    result = await pipeline.process_signal(
        account=_account(),
        profile=_profile(),
        signal=RevenueSignal.LEAD_CREATED,
        source="api",
        source_event_id="lead-pii-1",
        payload={"email": raw_email, "marketing_consent": True},
    )

    encoded = json.dumps(result["event"], sort_keys=True)
    assert raw_email not in encoded
    assert len(result["event"]["payload_hash"]) == 64


def _configure_checkout(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_w2e_checkout")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_w2e_checkout")
    monkeypatch.setenv("STRIPE_PRODUCT_ID", "prod_w2e")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_w2e")
    monkeypatch.setenv("STRIPE_METER_ID", "mtr_w2e")
    monkeypatch.setenv("STRIPE_WEBHOOK_ENDPOINT_ID", "we_w2e")
    monkeypatch.setenv(
        "STRIPE_WEBHOOK_ENDPOINT_URL",
        "https://cinema.example.test/billing/webhook/stripe",
    )
    monkeypatch.delenv("DSG_MARKETING_PROFILE_STORE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_EVENT_STORE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_LIFECYCLE_STORE", raising=False)

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


def test_server_created_checkout_is_persisted_as_checkout_started(monkeypatch):
    _configure_checkout(monkeypatch)
    engine = billing.reset_engine(RevenueEngine(enforce=False))
    reset_revenue_pipeline()
    account, api_key = engine.accounts.issue(
        display_name="W2E Checkout",
        plan="free",
        channel="api",
        mode="live",
    )

    async def fake_stripe_post(
        _config,
        path: str,
        *,
        data: dict[str, str],
        idempotency_key: str,
        timeout_seconds: float = 15.0,
    ):
        if path == "/v1/customers":
            return {"id": "cus_w2e_checkout"}
        if path == "/v1/checkout/sessions":
            return {
                "id": "cs_live_w2e_checkout",
                "url": "https://checkout.stripe.com/c/pay/cs_live_w2e_checkout",
            }
        raise AssertionError(path)

    monkeypatch.setattr(checkout, "_stripe_post", fake_stripe_post)
    response = client.post(
        "/billing/checkout/session",
        headers={"X-DSG-API-Key": api_key},
        json={"plan": "metered", "checkout_id": "checkout-w2e-001"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["entitled"] is False
    assert body["governed_revenue"]["lifecycle"]["state"] == "CHECKOUT_STARTED"
    current = engine.accounts.get(account.account_id)
    assert current is not None
    assert current.plan == "free"
    assert current.payment_linked is False


def _stripe_signature(payload: bytes, secret: str) -> str:
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_signed_scoped_paid_invoice_drives_customer_and_replays_safely(monkeypatch):
    secret = "whsec_w2e_paid"
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_w2e_paid")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("STRIPE_PRODUCT_ID", "prod_w2e_paid")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_w2e_paid")
    monkeypatch.delenv("DSG_MARKETING_PROFILE_STORE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_EVENT_STORE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_LIFECYCLE_STORE", raising=False)

    engine = billing.reset_engine(RevenueEngine(enforce=False))
    reset_revenue_pipeline()
    account, _api_key = engine.accounts.issue(
        display_name="W2E Paid",
        plan="free",
        channel="api",
        mode="live",
        stripe_customer_id="cus_w2e_paid",
    )

    created = int(time.time())
    event = {
        "id": "evt_w2e_invoice_paid",
        "type": "invoice.paid",
        "created": created,
        "livemode": True,
        "data": {
            "object": {
                "id": "in_w2e_paid",
                "customer": "cus_w2e_paid",
                "subscription": "sub_w2e_paid",
                "currency": "usd",
                "amount_paid": 1200,
                "period_start": created,
                "lines": {
                    "data": [
                        {
                            "amount": 1200,
                            "price": {
                                "id": "price_w2e_paid",
                                "product": "prod_w2e_paid",
                            },
                        }
                    ]
                },
            }
        },
    }
    payload = json.dumps(event, separators=(",", ":")).encode("utf-8")

    first = client.post(
        "/billing/webhook/stripe",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": _stripe_signature(payload, secret),
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["result"]["applied"] is True
    assert body["governed_revenue"]["lifecycle"]["state"] == "CUSTOMER"
    assert "dsg-payment-confirmed" in body["governed_revenue"]["projection"]["desired_tags"]

    current = engine.accounts.get(account.account_id)
    assert current is not None
    assert "evt_w2e_invoice_paid" in current.stripe_processed_event_ids
    assert "in_w2e_paid" in current.stripe_paid_invoice_ids
    assert current.payment_linked is True

    replay = client.post(
        "/billing/webhook/stripe",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": _stripe_signature(payload, secret),
        },
    )
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["result"]["applied"] is False
    assert replay_body["result"]["reason"] == "duplicate"
    assert replay_body["governed_revenue"]["duplicate"] is True
