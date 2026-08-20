from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from revenue.accounts import Account, AccountStore, accounts_from_env, hash_secret
from revenue.engine import (
    ACCOUNT_SUSPENDED,
    AUTHORIZED,
    PAYMENT_NOT_LINKED,
    QUOTA_EXCEEDED,
    UNKNOWN_KEY,
    RevenueEngine,
)
from revenue.ledger import ChainError, LedgerStore, verify_chain
from revenue.pricing import (
    get_plan,
    get_sku,
    micros_to_usd_string,
    resolve_unit_price_micros,
    unit_amount_micros,
)
from revenue.stripe_sync import (
    SignatureError,
    StripeConfig,
    apply_webhook_event,
    config_from_env,
    verify_webhook_signature,
)

client = TestClient(cinema_main.app)

ADMIN_SECRET = "A" * 48

VALID_PROOF = {
    "request_id": "cinema-test",
    "z3_status": "SAT",
    "verification": "VERIFIED_GLOBAL_OPTIMUM",
    "verified": True,
    "witness": [1, 0, 0],
    "energy_exact": "-100",
    "proof_hash": "a" * 64,
    "request_hash": "b" * 64,
}

VERIFY_BODY = {
    "execution_id": "exec-revenue-001",
    "channel": "api",
    "agent_identity": "agent://dsg/test",
    "approved_plan_hash": "1" * 64,
    "proposed_action_hash": "2" * 64,
    "authorized": True,
    "plan_aligned": True,
    "constraints_pass": True,
    "execution_succeeded": True,
    "replay_match": True,
    "evidence_complete": True,
    "cost_microunits": 0,
}


@pytest.fixture
def engine(monkeypatch):
    """A fresh, isolated engine for each test."""
    monkeypatch.setenv("DSG_REVENUE_ADMIN_SECRET", ADMIN_SECRET)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    instance = billing.reset_engine(RevenueEngine(enforce=False))
    yield instance
    billing.reset_engine(RevenueEngine(enforce=False))


def configure_backend(monkeypatch):
    monkeypatch.setenv("DSG_BACKEND_BASE_URL", "https://z3.example.test")
    monkeypatch.setenv("DSG_BACKEND_API_KEY", "z" * 32)
    monkeypatch.setenv("CINEMA_API_SECRET", "c" * 32)

    async def fake_z3_request(method, path, payload=None):
        return 200, dict(VALID_PROOF)

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)


# ------------------------------------------------------------------- pricing
def test_included_units_are_consumed_before_any_charge():
    plan = get_plan("team")
    price = plan.unit_price_micros
    assert unit_amount_micros(plan, price, 0, 1) == 0
    assert unit_amount_micros(plan, price, plan.included_units - 1, 1) == 0
    assert unit_amount_micros(plan, price, plan.included_units, 1) == price
    assert unit_amount_micros(plan, price, plan.included_units + 10, 3) == 3 * price


def test_partially_included_batch_only_charges_the_overage():
    plan = get_plan("team")
    price = plan.unit_price_micros
    assert unit_amount_micros(plan, price, plan.included_units - 2, 5) == 3 * price


def test_account_unit_price_overrides_plan_and_sku_price():
    plan = get_plan("metered")
    sku = get_sku("verified_execution")
    assert resolve_unit_price_micros(plan, sku) == sku.list_price_micros
    assert resolve_unit_price_micros(plan, sku, 42) == 42
    assert resolve_unit_price_micros(get_plan("team"), sku) == 80_000


def test_money_is_rendered_without_float_drift():
    assert micros_to_usd_string(99_000_000) == "99.000000"
    assert micros_to_usd_string(100_000) == "0.100000"
    assert micros_to_usd_string(1) == "0.000001"
    assert micros_to_usd_string(-100_000) == "-0.100000"


# -------------------------------------------------------------------- ledger
def test_ledger_chain_verifies_and_detects_tampering():
    store = LedgerStore()
    for index in range(4):
        store.append(
            account_id="acct_1",
            channel="api",
            sku="verified_execution",
            quantity=1,
            unit_price_micros=100_000,
            amount_micros=100_000,
            proof_hash="a" * 64,
            context_hash=f"{index:064d}",
            idempotency_key=f"key-{index}",
            units_before=index,
        )

    report = verify_chain(store.entries())
    assert report["verified"] is True
    assert report["entries"] == 4
    assert report["total_amount_micros"] == 400_000

    entries = store.entries()
    tampered = entries[:2] + [
        entries[2].__class__(**{**entries[2].to_dict(), "amount_micros": 1})
    ] + entries[3:]
    with pytest.raises(ChainError):
        verify_chain(tampered)


def test_ledger_is_idempotent_per_context():
    store = LedgerStore()
    first, created_first = store.append(
        account_id="acct_1",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="a" * 64,
        context_hash="c" * 64,
        idempotency_key="same-key",
        units_before=0,
    )
    second, created_second = store.append(
        account_id="acct_1",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="a" * 64,
        context_hash="c" * 64,
        idempotency_key="same-key",
        units_before=1,
    )
    assert created_first is True
    assert created_second is False
    assert second.entry_hash == first.entry_hash
    assert store.size() == 1


def test_ledger_survives_a_restart_through_the_file_store(tmp_path):
    path = tmp_path / "ledger.json"
    first = LedgerStore(str(path))
    first.append(
        account_id="acct_1",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="a" * 64,
        context_hash="c" * 64,
        idempotency_key="key-0",
        units_before=0,
    )

    reopened = LedgerStore(str(path))
    assert reopened.size() == 1
    assert reopened.head_hash() == first.head_hash()


def test_reopening_a_tampered_ledger_file_fails_closed(tmp_path):
    path = tmp_path / "ledger.json"
    store = LedgerStore(str(path))
    store.append(
        account_id="acct_1",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="a" * 64,
        context_hash="c" * 64,
        idempotency_key="key-0",
        units_before=0,
    )

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[0]["amount_micros"] = 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ChainError):
        LedgerStore(str(path))


# ------------------------------------------------------------------ accounts
def test_api_key_is_verified_against_a_stored_hash_only():
    store = AccountStore()
    account, api_key = store.issue(display_name="Acme", plan="metered")

    assert store.authenticate(api_key).account_id == account.account_id
    assert api_key not in json.dumps(account.to_dict())
    assert account.secret_hash == hash_secret(api_key.rsplit("_", 1)[1])


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "nonsense",
        "dsg_live_short_key",
        "dsg_live_" + "0" * 16 + "_" + "0" * 48,
        "Bearer dsg_live_aaaaaaaaaaaaaaaa_" + "b" * 48,
    ],
)
def test_malformed_or_unknown_keys_never_authenticate(candidate):
    store = AccountStore()
    store.issue(display_name="Acme", plan="metered")
    assert store.authenticate(candidate) is None


def test_a_test_mode_key_cannot_authenticate_a_live_account():
    store = AccountStore()
    _, api_key = store.issue(display_name="Acme", plan="metered", mode="live")
    assert store.authenticate(api_key.replace("dsg_live_", "dsg_test_", 1)) is None


def test_bootstrap_accounts_refuse_plaintext_secrets():
    with pytest.raises(ValueError, match="secret_hash"):
        accounts_from_env(
            json.dumps(
                [
                    {
                        "account_id": "acct_1",
                        "display_name": "Acme",
                        "key_id": "a" * 16,
                        "api_key": "dsg_live_x",
                    }
                ]
            )
        )


def test_bootstrap_accounts_load_from_configuration():
    accounts = accounts_from_env(
        json.dumps(
            [
                {
                    "account_id": "acct_1",
                    "display_name": "Acme",
                    "plan": "metered",
                    "key_id": "a" * 16,
                    "secret_hash": hash_secret("secret"),
                }
            ]
        )
    )
    assert len(accounts) == 1
    assert accounts[0].plan == "metered"


# -------------------------------------------------------------------- engine
def test_unknown_key_is_denied_with_401(engine):
    authorization = engine.authorize("dsg_live_" + "0" * 16 + "_" + "0" * 48, "verified_execution")
    assert authorization.decision == UNKNOWN_KEY
    assert authorization.http_status == 401
    assert authorization.authorized is False


def test_suspended_account_is_denied(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, status="suspended")
    assert engine.authorize(api_key, "verified_execution").decision == ACCOUNT_SUSPENDED


def test_free_plan_quota_is_fail_closed_at_the_cap(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="free")
    plan = get_plan("free")
    receipt = {
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": "a" * 64,
        "context_hash": "c" * 64,
    }

    for index in range(plan.hard_cap_units):
        authorization = engine.authorize(api_key, "verified_execution")
        assert authorization.decision == AUTHORIZED
        engine.record_usage(
            authorization,
            sku="verified_execution",
            receipt={**receipt, "context_hash": f"{index:064d}"},
        )

    exhausted = engine.authorize(api_key, "verified_execution")
    assert exhausted.decision == QUOTA_EXCEEDED
    assert exhausted.http_status == 402
    assert engine.usage_summary(account)["total_amount_micros"] == 0


def test_metered_plan_requires_a_linked_payment_method(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    denied = engine.authorize(api_key, "verified_execution")
    assert denied.decision == PAYMENT_NOT_LINKED
    assert denied.http_status == 402

    engine.accounts.update(account.account_id, payment_linked=True)
    assert engine.authorize(api_key, "verified_execution").decision == AUTHORIZED


def test_an_unverified_receipt_is_never_metered(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="free")
    authorization = engine.authorize(api_key, "verified_execution")

    with pytest.raises(ValueError, match="unverified"):
        engine.record_usage(
            authorization,
            sku="verified_execution",
            receipt={
                "verified": False,
                "verification": "VERIFIED_GLOBAL_OPTIMUM",
                "proof_hash": "a" * 64,
                "context_hash": "c" * 64,
            },
        )

    with pytest.raises(ValueError, match="global optimum"):
        engine.record_usage(
            authorization,
            sku="verified_execution",
            receipt={
                "verified": True,
                "verification": "COUNTEREXAMPLE_FOUND",
                "proof_hash": "a" * 64,
                "context_hash": "c" * 64,
            },
        )

    assert engine.ledger.size() == 0


def test_metered_usage_prices_and_aggregates_deterministically(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, payment_linked=True)

    for index in range(3):
        authorization = engine.authorize(api_key, "verified_execution")
        engine.record_usage(
            authorization,
            sku="verified_execution",
            receipt={
                "verified": True,
                "verification": "VERIFIED_GLOBAL_OPTIMUM",
                "proof_hash": "a" * 64,
                "context_hash": f"{index:064d}",
            },
        )

    summary = engine.usage_summary(engine.accounts.get(account.account_id))
    assert summary["units"] == 3
    assert summary["total_amount_micros"] == 300_000
    assert summary["total_amount_usd"] == "0.300000"

    report = engine.period_report()
    assert report["billable_units"] == 3
    assert report["recognized_amount_micros"] == 300_000
    assert report["ledger"]["verified"] is True


def test_the_same_verification_context_is_billed_once(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, payment_linked=True)
    receipt = {
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": "a" * 64,
        "context_hash": "c" * 64,
    }

    for _ in range(3):
        authorization = engine.authorize(api_key, "verified_execution")
        engine.record_usage(authorization, sku="verified_execution", receipt=receipt)

    summary = engine.usage_summary(engine.accounts.get(account.account_id))
    assert summary["units"] == 1
    assert summary["total_amount_micros"] == 100_000


# ------------------------------------------------------------ Stripe webhooks
def signed_headers(payload: bytes, secret: str, offset: int = 0) -> dict:
    timestamp = int(time.time()) + offset
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + payload,
        hashlib.sha256,
    ).hexdigest()
    return {"Stripe-Signature": f"t={timestamp},v1={signature}"}


def test_valid_stripe_signature_is_accepted():
    payload = b'{"id":"evt_1"}'
    header = signed_headers(payload, "whsec_test")["Stripe-Signature"]
    verify_webhook_signature(payload, header, "whsec_test")


@pytest.mark.parametrize(
    "header,secret,offset,message",
    [
        (None, "whsec_test", 0, "header is required"),
        ("t=1,v1=deadbeef", "whsec_test", 0, "tolerance"),
        ("v1=deadbeef", "whsec_test", 0, "missing t"),
        ("t=1", "whsec_test", 0, "missing t"),
    ],
)
def test_malformed_stripe_signatures_are_rejected(header, secret, offset, message):
    with pytest.raises(SignatureError, match=message):
        verify_webhook_signature(b"{}", header, secret)


def test_a_forged_stripe_signature_is_rejected():
    payload = b'{"id":"evt_1"}'
    header = signed_headers(payload, "whsec_attacker")["Stripe-Signature"]
    with pytest.raises(SignatureError, match="matched"):
        verify_webhook_signature(payload, header, "whsec_test")


def test_webhooks_are_rejected_when_no_secret_is_configured():
    with pytest.raises(SignatureError, match="not configured"):
        verify_webhook_signature(b"{}", "t=1,v1=x", None)


def test_subscription_events_drive_entitlement_state():
    store = AccountStore()
    account, _ = store.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )

    result = apply_webhook_event(
        {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_1",
                    "customer": "cus_123",
                    "status": "active",
                    "metadata": {"dsg_plan": "team"},
                }
            },
        },
        store,
    )
    assert result["applied"] is True
    updated = store.get(account.account_id)
    assert updated.plan == "team"
    assert updated.payment_linked is True

    apply_webhook_event(
        {
            "type": "invoice.payment_failed",
            "data": {"object": {"customer": "cus_123"}},
        },
        store,
    )
    assert store.get(account.account_id).status == "suspended"


def test_webhook_for_an_unknown_customer_never_creates_entitlement():
    store = AccountStore()
    result = apply_webhook_event(
        {
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_unknown"}},
        },
        store,
    )
    assert result["applied"] is False
    assert store.all() == []


def test_unlinked_stripe_configuration_reports_not_linked():
    config = config_from_env({})
    assert isinstance(config, StripeConfig)
    assert config.linked is False
    assert config.status()["link_state"] == "NOT_LINKED"
    assert config.status()["charges_enabled"] is False


# ---------------------------------------------------------------- HTTP surface
def test_billing_status_is_public_and_declares_the_checkout_truth(engine):
    response = client.get("/billing/status")
    assert response.status_code == 200
    body = response.json()
    assert body["checkout_status"] == "NOT_VERIFIED_NOT_LINKED"
    assert body["stripe"]["charges_enabled"] is False
    assert body["metering_enforced"] is False
    assert {plan["plan"] for plan in body["catalog"]["plans"]} == {
        "free",
        "metered",
        "team",
        "enterprise",
    }


def test_billing_status_reports_linked_when_stripe_is_configured(engine, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    body = client.get("/billing/status").json()
    assert body["checkout_status"] == "LINKED"
    assert body["stripe"]["charges_enabled"] is True


def test_admin_endpoints_require_the_admin_secret(engine):
    assert client.get("/billing/report").status_code == 401
    assert (
        client.get("/billing/report", headers={"Authorization": "Bearer wrong"}).status_code
        == 403
    )
    assert (
        client.get("/billing/report", headers={"Authorization": f"Bearer {ADMIN_SECRET}"}).status_code
        == 200
    )


def test_admin_can_issue_a_key_that_is_returned_exactly_once(engine):
    response = client.post(
        "/billing/accounts",
        headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        json={"display_name": "Acme", "plan": "metered"},
    )
    assert response.status_code == 201
    body = response.json()
    api_key = body["api_key"]
    assert api_key.startswith("dsg_live_")
    assert "secret_hash" not in body["account"]

    usage = client.get("/billing/usage", headers={"X-DSG-API-Key": api_key})
    assert usage.status_code == 200
    assert usage.json()["units"] == 0


def test_usage_endpoint_rejects_a_missing_key(engine):
    assert client.get("/billing/usage").status_code == 401


def test_webhook_is_unavailable_until_a_signing_secret_is_configured(engine):
    response = client.post("/billing/webhook/stripe", json={"type": "invoice.paid"})
    assert response.status_code == 503


def test_signed_webhook_updates_the_account(engine, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    account, _ = engine.accounts.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )
    payload = json.dumps(
        {
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_123", "subscription": "sub_1"}},
        }
    ).encode("utf-8")

    response = client.post(
        "/billing/webhook/stripe",
        content=payload,
        headers={
            **signed_headers(payload, "whsec_test"),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["applied"] is True
    assert engine.accounts.get(account.account_id).payment_linked is True


def test_forged_webhook_is_rejected_with_400(engine, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    payload = b'{"id":"evt_1","type":"invoice.paid"}'
    response = client.post(
        "/billing/webhook/stripe",
        content=payload,
        headers={
            **signed_headers(payload, "whsec_attacker"),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


# ------------------------------------------------------- metered verification
def test_public_verification_stays_free_when_no_key_is_presented(engine, monkeypatch):
    configure_backend(monkeypatch)
    response = client.post("/verify/evaluate", json=VERIFY_BODY)
    assert response.status_code == 200
    assert "billing" not in response.json()
    assert engine.ledger.size() == 0


def test_a_presented_key_is_always_validated(engine, monkeypatch):
    configure_backend(monkeypatch)
    response = client.post(
        "/verify/evaluate",
        json=VERIFY_BODY,
        headers={"X-DSG-API-Key": "dsg_live_" + "0" * 16 + "_" + "0" * 48},
    )
    assert response.status_code == 401


def test_a_verified_receipt_is_metered_and_chained(engine, monkeypatch):
    configure_backend(monkeypatch)
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, payment_linked=True)

    response = client.post(
        "/verify/evaluate",
        json=VERIFY_BODY,
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 200
    block = response.json()["billing"]
    assert block["metered"] is True
    assert block["amount_micros"] == 100_000
    assert block["stripe_sync"]["sync_state"] == "PENDING_UNLINKED"
    assert engine.ledger.size() == 1
    assert verify_chain(engine.ledger.entries())["verified"] is True


def test_replaying_the_same_execution_does_not_double_bill(engine, monkeypatch):
    configure_backend(monkeypatch)
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, payment_linked=True)

    for _ in range(3):
        response = client.post(
            "/verify/evaluate",
            json=VERIFY_BODY,
            headers={"X-DSG-API-Key": api_key},
        )
        assert response.status_code == 200

    summary = engine.usage_summary(engine.accounts.get(account.account_id))
    assert summary["units"] == 1
    assert summary["total_amount_micros"] == 100_000


def test_enforced_metering_requires_a_key(engine, monkeypatch):
    configure_backend(monkeypatch)
    billing.reset_engine(RevenueEngine(enforce=True))

    response = client.post("/verify/evaluate", json=VERIFY_BODY)
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == UNKNOWN_KEY


def test_exhausted_quota_blocks_verification_with_402(engine, monkeypatch):
    configure_backend(monkeypatch)
    account, api_key = engine.accounts.issue(display_name="Acme", plan="free")
    engine.accounts.update(account.account_id, hard_cap_units=1)

    first = client.post(
        "/verify/evaluate",
        json=VERIFY_BODY,
        headers={"X-DSG-API-Key": api_key},
    )
    assert first.status_code == 200

    second = client.post(
        "/verify/evaluate",
        json={**VERIFY_BODY, "execution_id": "exec-revenue-002"},
        headers={"X-DSG-API-Key": api_key},
    )
    assert second.status_code == 402
    assert second.json()["detail"]["error"] == QUOTA_EXCEEDED


def test_a_failed_verification_produces_no_revenue(engine, monkeypatch):
    configure_backend(monkeypatch)
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, payment_linked=True)

    async def unverified_z3(method, path, payload=None):
        return 200, {**VALID_PROOF, "verified": False, "verification": "COUNTEREXAMPLE_FOUND"}

    monkeypatch.setattr(cinema_main, "z3_request", unverified_z3)
    response = client.post(
        "/verify/evaluate",
        json=VERIFY_BODY,
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 502
    assert engine.ledger.size() == 0


def test_stripe_decision_endpoint_is_metered_on_its_own_sku(engine, monkeypatch):
    configure_backend(monkeypatch)
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, payment_linked=True)

    response = client.post(
        "/stripe/evaluate",
        json={
            "stripe_account_id": "acct_test123",
            "object_type": "charge",
            "object_id": "ch_test123",
            "amount_cents": 5000,
            "currency": "usd",
            "stripe_status": "succeeded",
            "risk_level": "low",
        },
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 200
    block = response.json()["billing"]
    assert block["sku"] == "stripe_policy_decision"
    assert block["metered"] is True
    assert engine.ledger.entries()[0].channel == "stripe"
