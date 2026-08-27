from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from scripts import revenue_report
from revenue.accounts import Account, AccountStore, accounts_from_env, hash_secret
from revenue.engine import (
    ACCOUNT_SUSPENDED,
    AUTHORIZED,
    PAYMENT_NOT_LINKED,
    QUOTA_EXCEEDED,
    UNKNOWN_KEY,
    RevenueEngine,
)
from revenue.ledger import (
    ChainError,
    LedgerStore,
    QuotaExceededError,
    billing_period,
    verify_chain,
)
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
    verify_operational_link,
    verify_webhook_signature,
)

client = TestClient(cinema_main.app)

ADMIN_SECRET = "A" * 48

TEST_STRIPE_CONFIG = StripeConfig(
    secret_key="sk_test_configured",
    webhook_secret="whsec_test",
    meter_event_name="dsg_verified_execution",
    product_id="prod_dsg",
    price_id="price_dsg",
    meter_id="mtr_dsg",
    webhook_endpoint_id="we_dsg",
    webhook_endpoint_url="https://cinema.example.test/billing/webhook/stripe",
)

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
    for name in (
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRODUCT_ID",
        "STRIPE_PRICE_ID",
        "STRIPE_METER_ID",
        "STRIPE_WEBHOOK_ENDPOINT_ID",
        "STRIPE_WEBHOOK_ENDPOINT_URL",
    ):
        monkeypatch.delenv(name, raising=False)
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
    summary = engine.usage_summary(account)
    assert summary["total_amount_micros"] == 0
    assert summary["usage_percent"] == 100.0
    assert summary["upgrade"]["recommended"] is True
    assert summary["upgrade"]["reason"] == "QUOTA_EXHAUSTED"
    assert summary["upgrade"]["target_plan"] == "metered"
    assert summary["upgrade"]["checkout_endpoint"] == "/billing/checkout/session"


def test_usage_upgrade_signal_uses_exact_80_percent_boundary(engine):
    account, _api_key = engine.accounts.issue(
        display_name="Boundary",
        plan="free",
        hard_cap_units=100,
    )
    for index in range(79):
        engine.ledger.append(
            account_id=account.account_id,
            channel="api",
            sku="verified_execution",
            quantity=1,
            unit_price_micros=0,
            amount_micros=0,
            proof_hash=f"{index:064x}",
            context_hash=f"{index + 100:064x}",
            idempotency_key=f"boundary-{index}",
            units_before=index,
        )
    summary = engine.usage_summary(account)
    assert summary["usage_percent"] == 79.0
    assert summary["upgrade"]["recommended"] is False

    engine.ledger.append(
        account_id=account.account_id,
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=0,
        amount_micros=0,
        proof_hash="f" * 64,
        context_hash="e" * 64,
        idempotency_key="boundary-80",
        units_before=79,
    )
    summary = engine.usage_summary(account)
    assert summary["usage_percent"] == 80.0
    assert summary["upgrade"]["recommended"] is True
    assert summary["upgrade"]["reason"] == "QUOTA_80_PERCENT"


def test_uncapped_plan_has_no_quota_upgrade_signal(engine):
    account, _api_key = engine.accounts.issue(display_name="Paid", plan="metered")
    summary = engine.usage_summary(account)
    assert summary["usage_percent"] is None
    assert summary["upgrade"]["recommended"] is False


def test_supabase_database_url_requires_server_credentials():
    from revenue.postgres import validate_database_url

    assert validate_database_url(
        "postgresql://postgres.project:secret@aws-0.us-east-1.pooler.supabase.com:5432/postgres?sslmode=require"
    ).startswith("postgresql://")
    with pytest.raises(ValueError, match="server-side credentials"):
        validate_database_url("postgresql://db.example/dsg?sslmode=require")


def test_tls_is_enforced_by_the_connection_not_by_the_written_uri():
    """A URI that omits sslmode is opened with require, not refused."""
    from revenue.postgres import tls_mode_for, validate_database_url

    plain = "postgresql://postgres.project:secret@aws-1.pooler.supabase.com:6543/postgres"
    assert validate_database_url(plain) == plain
    assert tls_mode_for(plain) == "require"

    # A URI that already states a strong mode is left alone, so verify-full is
    # never quietly downgraded to require.
    assert tls_mode_for(plain + "?sslmode=verify-full") is None
    assert tls_mode_for(plain + "?sslmode=require") is None


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
def test_an_explicit_plaintext_fallback_is_refused(mode):
    from revenue.postgres import validate_database_url

    with pytest.raises(ValueError, match=f"sslmode={mode}"):
        validate_database_url(
            f"postgresql://user:secret@db.example/dsg?sslmode={mode}"
        )


def test_connect_supplies_the_tls_mode_a_uri_left_out(monkeypatch):
    from revenue import postgres

    captured = {}

    class FakePsycopg:
        @staticmethod
        def connect(url, **options):
            captured.update(url=url, **options)
            return "connection"

    monkeypatch.setitem(__import__("sys").modules, "psycopg", FakePsycopg)
    postgres.connect("postgresql://user:secret@db.example:6543/dsg")
    assert captured["sslmode"] == "require"

    captured.clear()
    postgres.connect("postgresql://user:secret@db.example:6543/dsg?sslmode=verify-full")
    assert "sslmode" not in captured, "an explicit strong mode must not be overridden"


def test_supabase_connect_does_not_log_database_url(monkeypatch):
    from revenue import postgres

    captured = {}

    class FakePsycopg:
        @staticmethod
        def connect(url, **options):
            captured.update(url=url, **options)
            return "connection"

    monkeypatch.setitem(__import__("sys").modules, "psycopg", FakePsycopg)
    assert postgres.connect("postgresql://user:secret@db.example/dsg?sslmode=require") == "connection"
    assert captured["autocommit"] is False
    # Supabase's transaction-mode pooler gives the next transaction another backend,
    # which would not know a statement this connection had prepared.
    assert captured["prepare_threshold"] is None


def test_postgres_account_store_uses_parameterized_tenant_queries(monkeypatch):
    from revenue.accounts import Account, hash_secret
    from revenue.postgres import PostgresAccountStore

    statements = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, statement, params=()): statements.append((statement, params))
        def fetchone(self): return None

    class Connection:
        def cursor(self): return Cursor()
        def commit(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr("revenue.postgres.connect", lambda _: Connection())
    monkeypatch.setattr("revenue.postgres.initialize_schema", lambda _: None)
    store = PostgresAccountStore("postgresql://user:secret@db.example/dsg?sslmode=require")
    account = Account(account_id="tenant-a", display_name="Tenant A", key_id="key-a", secret_hash=hash_secret("dsg_key-a_secret"))
    store.import_account(account)
    assert any("VALUES (%s" in statement and params[0] == "tenant-a" for statement, params in statements)


def test_postgres_database_url_activates_store_contract(monkeypatch):
    from revenue.engine import RevenueEngine
    monkeypatch.setattr("revenue.engine.PostgresAccountStore", lambda url: ("accounts", url))
    monkeypatch.setattr("revenue.engine.PostgresLedgerStore", lambda url: ("ledger", url))
    engine = RevenueEngine.from_env({"DSG_REVENUE_DATABASE_URL": "postgresql://u:p@db/dsg", "DSG_REVENUE_ENFORCE": "1"})
    assert getattr(engine, "accounts")[0] == "accounts"
    assert getattr(engine, "ledger")[0] == "ledger"
    assert engine.enforce is True


def test_postgres_ledger_read_back_keeps_the_hashed_timestamp_format():
    """A TIMESTAMPTZ read-back must reproduce the string the entry hash covers."""
    from datetime import datetime, timezone

    from revenue.ledger import compute_entry_hash
    from revenue.postgres import PostgresLedgerStore

    body = {
        "sequence": 0,
        "period": "2026-08",
        "account_id": "tenant-a",
        "channel": "api",
        "sku": "verified_execution",
        "quantity": 1,
        "units_before": 0,
        "unit_price_micros": 1000,
        "amount_micros": 1000,
        "proof_hash": "p" * 64,
        "context_hash": "c" * 64,
        "idempotency_key": "key-1",
        "recorded_at": "2026-08-23T11:22:33.123456Z",
        "prev_hash": "0" * 64,
    }
    entry_hash = compute_entry_hash(body)
    row = (
        body["sequence"], body["period"], body["account_id"], body["channel"], body["sku"],
        body["quantity"], body["units_before"], body["unit_price_micros"], body["amount_micros"],
        body["proof_hash"], body["context_hash"], body["idempotency_key"],
        datetime(2026, 8, 23, 11, 22, 33, 123456, tzinfo=timezone.utc),
        body["prev_hash"], entry_hash,
    )

    entry = PostgresLedgerStore._entry(row)

    assert entry.recorded_at == "2026-08-23T11:22:33.123456Z"
    assert compute_entry_hash(entry.commitment()) == entry.entry_hash


def test_postgres_account_read_back_keeps_timestamps_as_strings():
    from datetime import datetime, timezone

    from revenue.accounts import hash_secret
    from revenue.postgres import _account_from_row

    values = {
        "account_id": "tenant-a", "display_name": "Tenant A", "plan": "free",
        "status": "active", "channel": "api", "key_id": "key-a",
        "secret_hash": hash_secret("dsg_key-a_secret"), "mode": "live",
        "stripe_customer_id": None, "stripe_subscription_id": None, "payment_linked": False,
        "stripe_paid_amounts_micros": {}, "stripe_paid_invoice_ids": [],
        "stripe_processed_event_ids": [], "stripe_field_event_created": {},
        "activation_ref": None, "unit_price_micros": None, "hard_cap_units": None,
        "created_at": datetime(2026, 8, 23, 11, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 8, 23, 11, 30, 0, 500000, tzinfo=timezone.utc),
    }
    account = _account_from_row(tuple(values.values()))

    assert account.created_at == "2026-08-23T11:00:00Z"
    assert account.updated_at == "2026-08-23T11:30:00.500000Z"
    json.dumps(account.to_dict())  # the account must stay JSON-serialisable


def test_atomic_append_prevents_two_pre_authorized_requests_crossing_a_cap(engine):
    account, api_key = engine.accounts.issue(
        display_name="Acme",
        plan="free",
        hard_cap_units=1,
    )
    receipt = {
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": "a" * 64,
    }

    first = engine.authorize(api_key, "verified_execution")
    second = engine.authorize(api_key, "verified_execution")
    assert first.decision == AUTHORIZED
    assert second.decision == AUTHORIZED

    engine.record_usage(
        first,
        sku="verified_execution",
        receipt={**receipt, "context_hash": "1" * 64},
    )
    with pytest.raises(QuotaExceededError, match="another request"):
        engine.record_usage(
            second,
            sku="verified_execution",
            receipt={**receipt, "context_hash": "2" * 64},
        )

    assert engine.ledger.units_used(account.account_id, billing_period()) == 1


def test_post_authorization_quota_race_returns_402_instead_of_a_free_proof(engine):
    _, api_key = engine.accounts.issue(
        display_name="Acme",
        plan="free",
        hard_cap_units=1,
    )
    first = engine.authorize(api_key, "verified_execution")
    second = engine.authorize(api_key, "verified_execution")
    base_receipt = {
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": "a" * 64,
    }
    asyncio.run(
        billing.meter(
            first,
            sku="verified_execution",
            receipt={**base_receipt, "context_hash": "1" * 64},
        )
    )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            billing.meter(
                second,
                sku="verified_execution",
                receipt={**base_receipt, "context_hash": "2" * 64},
            )
        )
    assert getattr(caught.value, "status_code", None) == 402
    assert caught.value.detail["error"] == QUOTA_EXCEEDED
    assert caught.value.detail["remediation"]["code"] == QUOTA_EXCEEDED


def test_entitlement_change_after_authorization_never_releases_a_free_proof(
    engine,
    monkeypatch,
):
    configure_backend(monkeypatch)
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    engine.accounts.update(account.account_id, payment_linked=True)

    async def suspend_during_solver(method, path, payload=None):
        if path == "/solve":
            engine.accounts.update(account.account_id, status="suspended")
        return 200, dict(VALID_PROOF)

    monkeypatch.setattr(cinema_main, "z3_request", suspend_during_solver)
    response = client.post(
        "/verify/evaluate",
        json=VERIFY_BODY,
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == ACCOUNT_SUSPENDED
    assert response.json()["detail"]["remediation"]["code"] == ACCOUNT_SUSPENDED
    assert engine.ledger.size() == 0


def test_metered_plan_requires_a_linked_payment_method(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="metered")
    denied = engine.authorize(api_key, "verified_execution")
    assert denied.decision == PAYMENT_NOT_LINKED
    assert denied.http_status == 402

    engine.accounts.update(account.account_id, payment_linked=True)
    assert engine.authorize(api_key, "verified_execution").decision == AUTHORIZED


def test_team_plan_requires_a_paid_current_period_before_included_use(engine):
    account, api_key = engine.accounts.issue(display_name="Acme", plan="team")
    assert engine.authorize(api_key, "verified_execution").decision == PAYMENT_NOT_LINKED

    engine.accounts.update(account.account_id, payment_linked=True)
    assert engine.authorize(api_key, "verified_execution").decision == PAYMENT_NOT_LINKED


def test_unpaid_team_account_is_not_reported_as_recognized_revenue(engine):
    engine.accounts.issue(display_name="Acme", plan="team")
    report = engine.period_report()
    assert report["recognized_amount_micros"] == 0
    assert report["accounts_billed"] == 0


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
    assert summary["total_amount_micros"] == 150_000
    assert summary["total_amount_usd"] == "0.150000"

    report = engine.period_report()
    assert report["billable_units"] == 3
    assert report["recorded_usage_amount_micros"] == 150_000
    assert report["recognized_amount_micros"] == 0
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
    assert summary["total_amount_micros"] == 50_000


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
            "id": "evt_subscription_active",
            "created": 200,
            "livemode": False,
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_1",
                    "customer": "cus_123",
                    "status": "active",
                    "metadata": {"dsg_plan": "team"},
                    "items": {
                        "data": [
                            {
                                "price": {
                                    "id": "price_dsg",
                                    "product": "prod_dsg",
                                }
                            }
                        ]
                    },
                }
            },
        },
        store,
        TEST_STRIPE_CONFIG,
    )
    assert result["applied"] is True
    updated = store.get(account.account_id)
    assert updated.plan == "team"
    assert updated.payment_linked is True

    apply_webhook_event(
        {
            "id": "evt_invoice_failed",
            "created": 201,
            "livemode": False,
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_123",
                    "subscription": "sub_1",
                }
            },
        },
        store,
        TEST_STRIPE_CONFIG,
    )
    assert store.get(account.account_id).status == "suspended"


def test_webhook_for_an_unknown_customer_never_creates_entitlement():
    store = AccountStore()
    result = apply_webhook_event(
        {
            "id": "evt_unknown",
            "created": 100,
            "livemode": False,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_unknown",
                    "subscription": "sub_unknown",
                    "metadata": {
                        "dsg_product_id": "prod_dsg",
                        "dsg_price_id": "price_dsg",
                    },
                }
            },
        },
        store,
        TEST_STRIPE_CONFIG,
    )
    assert result["applied"] is False
    assert store.all() == []


def test_unlinked_stripe_configuration_reports_not_linked():
    config = config_from_env({})
    assert isinstance(config, StripeConfig)
    assert config.api_configured is False
    assert config.status()["link_state"] == "NOT_LINKED"
    assert config.status()["charges_enabled"] is False


def test_operational_link_verifies_product_price_and_meter(monkeypatch):
    bodies = {
        "products": {"id": "prod_dsg", "active": True, "livemode": False},
        "prices": {
            "id": "price_dsg",
            "active": True,
            "product": "prod_dsg",
            "livemode": False,
        },
        "meters": {
            "id": "mtr_dsg",
            "status": "active",
            "event_name": "dsg_verified_execution",
            "livemode": False,
        },
        "webhook_endpoints": {
            "id": "we_dsg",
            "status": "enabled",
            "url": "https://cinema.example.test/billing/webhook/stripe",
            "livemode": False,
            "enabled_events": [
                "checkout.session.completed",
                "customer.subscription.created",
                "customer.subscription.updated",
                "customer.subscription.deleted",
                "invoice.paid",
                "invoice.payment_failed",
            ],
        },
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            key = next(name for name in bodies if f"/{name}/" in url)
            return FakeResponse(bodies[key])

    monkeypatch.setattr("revenue.stripe_sync.httpx.AsyncClient", FakeClient)
    result = asyncio.run(verify_operational_link(TEST_STRIPE_CONFIG))
    assert result["verified"] is True
    assert set(result["checks"].values()) == {"PASS"}
    assert TEST_STRIPE_CONFIG.status(result)["link_state"] == "TEST_MODE_VERIFIED"
    assert TEST_STRIPE_CONFIG.status(result)["charges_enabled"] is False


def test_unrelated_subscription_and_invoice_cannot_mutate_dsg_entitlement():
    store = AccountStore()
    account, _ = store.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )
    unrelated_subscription = apply_webhook_event(
        {
            "id": "evt_unrelated_subscription",
            "created": 100,
            "livemode": False,
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_other",
                    "customer": "cus_123",
                    "status": "active",
                    "metadata": {"dsg_plan": "team"},
                    "items": {
                        "data": [
                            {"price": {"id": "price_other", "product": "prod_other"}}
                        ]
                    },
                }
            },
        },
        store,
        TEST_STRIPE_CONFIG,
    )
    assert unrelated_subscription["applied"] is False
    assert store.get(account.account_id).plan == "free"

    store.update(account.account_id, stripe_subscription_id="sub_dsg")
    unrelated_invoice = apply_webhook_event(
        {
            "id": "evt_unrelated_invoice",
            "created": 101,
            "livemode": False,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_unrelated",
                    "customer": "cus_123",
                    "subscription": "sub_other",
                }
            },
        },
        store,
        TEST_STRIPE_CONFIG,
    )
    assert unrelated_invoice["applied"] is False
    assert store.get(account.account_id).payment_linked is False


def test_test_mode_event_cannot_mutate_a_live_mode_entitlement():
    live_config = StripeConfig(
        secret_key="sk_" + "live_configured",
        webhook_secret="whsec_test",
        meter_event_name="dsg_verified_execution",
        product_id="prod_dsg",
        price_id="price_dsg",
    )
    store = AccountStore()
    account, _ = store.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )
    result = apply_webhook_event(
        {
            "id": "evt_test_mode",
            "created": 100,
            "livemode": False,
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_dsg",
                    "customer": "cus_123",
                    "status": "active",
                    "items": {
                        "data": [
                            {"price": {"id": "price_dsg", "product": "prod_dsg"}}
                        ]
                    },
                }
            },
        },
        store,
        live_config,
    )
    assert result["applied"] is False
    assert result["reason"] == "event mode does not match the DSG Stripe key"
    assert store.get(account.account_id).payment_linked is False


def test_stripe_events_are_idempotent_and_stale_events_are_ignored():
    store = AccountStore()
    account, _ = store.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )
    active_event = {
        "id": "evt_active",
        "created": 200,
        "livemode": False,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_dsg",
                "customer": "cus_123",
                "status": "active",
                "metadata": {"dsg_plan": "metered"},
                "items": {
                    "data": [
                        {"price": {"id": "price_dsg", "product": "prod_dsg"}}
                    ]
                },
            }
        },
    }
    assert apply_webhook_event(active_event, store, TEST_STRIPE_CONFIG)["applied"] is True
    duplicate = apply_webhook_event(active_event, store, TEST_STRIPE_CONFIG)
    assert duplicate["applied"] is False
    assert duplicate["reason"] == "duplicate"

    stale = apply_webhook_event(
        {
            "id": "evt_stale_failure",
            "created": 199,
            "livemode": False,
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_paid_first",
                    "customer": "cus_123",
                    "subscription": "sub_dsg",
                }
            },
        },
        store,
        TEST_STRIPE_CONFIG,
    )
    assert stale["applied"] is False
    assert stale["reason"] == "stale"
    assert store.get(account.account_id).status == "active"


def test_stripe_event_idempotency_survives_account_store_restart(tmp_path):
    path = tmp_path / "accounts.json"
    store = AccountStore(str(path))
    store.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )
    event = {
        "id": "evt_persisted",
        "created": 200,
        "livemode": False,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_dsg",
                "customer": "cus_123",
                "status": "active",
                "items": {
                    "data": [
                        {"price": {"id": "price_dsg", "product": "prod_dsg"}}
                    ]
                },
            }
        },
    }
    assert apply_webhook_event(event, store, TEST_STRIPE_CONFIG)["applied"] is True

    reopened = AccountStore(str(path))
    duplicate = apply_webhook_event(event, reopened, TEST_STRIPE_CONFIG)
    assert duplicate["applied"] is False
    assert duplicate["reason"] == "duplicate"


def test_invoice_arriving_before_subscription_event_does_not_lose_plan_state():
    engine = RevenueEngine()
    account, api_key = engine.accounts.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )
    period_start = int(time.time())
    paid = apply_webhook_event(
        {
            "id": "evt_paid_first",
            "created": 201,
            "livemode": False,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_paid_first",
                    "customer": "cus_123",
                    "subscription": "sub_dsg",
                    "period_start": period_start,
                    "amount_paid": 49_000,
                    "currency": "usd",
                    "lines": {
                        "data": [
                            {
                                "amount": 49_000,
                                "price": {
                                    "id": "price_dsg",
                                    "product": "prod_dsg",
                                }
                            }
                        ]
                    },
                }
            },
        },
        engine.accounts,
        TEST_STRIPE_CONFIG,
    )
    assert paid["applied"] is True

    subscription = apply_webhook_event(
        {
            "id": "evt_subscription_late",
            "created": 200,
            "livemode": False,
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_dsg",
                    "customer": "cus_123",
                    "status": "active",
                    "metadata": {"dsg_plan": "team"},
                    "items": {
                        "data": [
                            {"price": {"id": "price_dsg", "product": "prod_dsg"}}
                        ]
                    },
                }
            },
        },
        engine.accounts,
        TEST_STRIPE_CONFIG,
    )
    assert subscription["applied"] is True
    assert engine.accounts.get(account.account_id).plan == "team"
    assert engine.authorize(api_key, "verified_execution").decision == AUTHORIZED


def test_only_a_paid_scoped_invoice_recognizes_team_base_revenue():
    engine = RevenueEngine()
    account, _ = engine.accounts.issue(
        display_name="Acme",
        plan="team",
        stripe_customer_id="cus_123",
    )
    now = int(time.time())
    result = apply_webhook_event(
        {
            "id": "evt_paid",
            "created": now,
            "livemode": False,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_paid",
                    "customer": "cus_123",
                    "subscription": "sub_dsg",
                    "period_start": now,
                    "amount_paid": 49_000,
                    "currency": "usd",
                    "lines": {
                        "data": [
                            {
                                "amount": 49_000,
                                "price": {
                                    "id": "price_dsg",
                                    "product": "prod_dsg",
                                }
                            }
                        ]
                    },
                }
            },
        },
        engine.accounts,
        TEST_STRIPE_CONFIG,
    )
    assert result["applied"] is True
    assert engine.accounts.get(account.account_id).stripe_subscription_id == "sub_dsg"
    report = engine.period_report()
    assert report["recognized_amount_micros"] == 490_000_000
    assert report["accounts_billed"] == 1
    assert report["accounts"][0]["paid_invoice_amount_micros"] == 490_000_000

    duplicate_invoice = apply_webhook_event(
        {
            "id": "evt_paid_duplicate_object",
            "created": now + 1,
            "livemode": False,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_paid",
                    "customer": "cus_123",
                    "subscription": "sub_dsg",
                    "period_start": now,
                    "amount_paid": 49_000,
                    "currency": "usd",
                }
            },
        },
        engine.accounts,
        TEST_STRIPE_CONFIG,
    )
    assert duplicate_invoice["applied"] is False
    assert duplicate_invoice["reason"] == "duplicate_invoice"
    assert engine.period_report()["recognized_amount_micros"] == 490_000_000


def test_zero_value_paid_invoice_does_not_grant_or_recognize_team_base():
    engine = RevenueEngine()
    account, api_key = engine.accounts.issue(
        display_name="Acme",
        plan="team",
        stripe_customer_id="cus_123",
    )
    now = int(time.time())
    result = apply_webhook_event(
        {
            "id": "evt_zero_paid",
            "created": now,
            "livemode": False,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_zero_paid",
                    "customer": "cus_123",
                    "subscription": "sub_dsg",
                    "period_start": now,
                    "amount_paid": 0,
                    "currency": "usd",
                    "lines": {
                        "data": [
                            {
                                "amount": 0,
                                "price": {
                                    "id": "price_dsg",
                                    "product": "prod_dsg",
                                }
                            }
                        ]
                    },
                }
            },
        },
        engine.accounts,
        TEST_STRIPE_CONFIG,
    )
    assert result["applied"] is True
    assert engine.authorize(api_key, "verified_execution").decision == PAYMENT_NOT_LINKED
    assert engine.period_report()["recognized_amount_micros"] == 0
    assert engine.accounts.get(account.account_id).payment_linked is True


def test_paid_invoice_recognizes_only_the_exact_dsg_line_amount():
    engine = RevenueEngine()
    account, api_key = engine.accounts.issue(
        display_name="Acme",
        plan="team",
        stripe_customer_id="cus_123",
    )
    now = int(time.time())
    result = apply_webhook_event(
        {
            "id": "evt_mixed_invoice",
            "created": now,
            "livemode": False,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_mixed",
                    "customer": "cus_123",
                    "subscription": "sub_dsg",
                    "period_start": now,
                    "amount_paid": 149_000,
                    "currency": "usd",
                    "lines": {
                        "data": [
                            {
                                "amount": 49_000,
                                "price": {
                                    "id": "price_dsg",
                                    "product": "prod_dsg",
                                },
                            },
                            {
                                "amount": 100_000,
                                "price": {
                                    "id": "price_other",
                                    "product": "prod_other",
                                },
                            },
                        ]
                    },
                }
            },
        },
        engine.accounts,
        TEST_STRIPE_CONFIG,
    )
    assert result["applied"] is True
    assert engine.period_report()["recognized_amount_micros"] == 490_000_000
    assert engine.authorize(api_key, "verified_execution").decision == AUTHORIZED


def test_paid_invoice_without_scoped_line_amount_grants_no_team_capacity():
    engine = RevenueEngine()
    _, api_key = engine.accounts.issue(
        display_name="Acme",
        plan="team",
        stripe_customer_id="cus_123",
    )
    now = int(time.time())
    result = apply_webhook_event(
        {
            "id": "evt_missing_line_amount",
            "created": now,
            "livemode": False,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_missing_line_amount",
                    "customer": "cus_123",
                    "subscription": "sub_dsg",
                    "period_start": now,
                    "amount_paid": 49_000,
                    "currency": "usd",
                    "lines": {
                        "data": [
                            {
                                "price": {
                                    "id": "price_dsg",
                                    "product": "prod_dsg",
                                }
                            }
                        ]
                    },
                }
            },
        },
        engine.accounts,
        TEST_STRIPE_CONFIG,
    )
    assert result["applied"] is True
    assert engine.period_report()["recognized_amount_micros"] == 0
    assert engine.authorize(api_key, "verified_execution").decision == PAYMENT_NOT_LINKED


# ---------------------------------------------------------------- HTTP surface
def test_billing_status_is_public_and_declares_the_checkout_truth(engine):
    response = client.get("/billing/status")
    assert response.status_code == 200
    body = response.json()
    assert body["checkout_status"] == "NOT_VERIFIED_NOT_LINKED"
    assert body["stripe"]["charges_enabled"] is False
    assert body["metering_enforced"] is False
    assert body["storage"] == {
        "backend": "memory",
        "accounts_backend": "memory",
        "ledger_backend": "memory",
        "durable": False,
        "writes_frozen": False,
    }
    assert {plan["plan"] for plan in body["catalog"]["plans"]} == {
        "free",
        "metered",
        "team",
        "enterprise",
    }


def test_marketplace_entitlements_are_resolvable_but_never_sold_here(engine):
    """GitHub is the merchant of record for Marketplace subscriptions.

    Those plans have to resolve — an entitled buyer must get their quota — while
    staying out of the public direct-billing catalog, so a Marketplace
    entitlement is never presented as something Cinema will charge for.
    """
    from revenue.pricing import GITHUB_MARKETPLACE_PLAN_CATALOG, get_plan

    published = {plan["plan"] for plan in client.get("/billing/status").json()["catalog"]["plans"]}
    assert not (published & set(GITHUB_MARKETPLACE_PLAN_CATALOG))

    for name, plan in GITHUB_MARKETPLACE_PLAN_CATALOG.items():
        assert get_plan(name) is plan
        assert plan.base_price_micros == 0
        assert plan.unit_price_micros == 0
        assert plan.requires_linked_payment is False
        assert plan.hard_cap_units == plan.included_units


def test_billing_status_does_not_claim_linked_from_a_secret_string(engine, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    body = client.get("/billing/status").json()
    assert body["checkout_status"] == "NOT_VERIFIED_NOT_LINKED"
    assert body["stripe"]["link_state"] == "CONFIGURED_UNVERIFIED"
    assert body["stripe"]["charges_enabled"] is False


def test_billing_status_links_only_after_operational_verification(
    engine,
    monkeypatch,
):
    for name, value in {
        "STRIPE_SECRET_KEY": "sk_test_x",
        "STRIPE_PRODUCT_ID": "prod_dsg",
        "STRIPE_PRICE_ID": "price_dsg",
        "STRIPE_METER_ID": "mtr_dsg",
        "STRIPE_WEBHOOK_SECRET": "whsec_test",
        "STRIPE_WEBHOOK_ENDPOINT_ID": "we_dsg",
        "STRIPE_WEBHOOK_ENDPOINT_URL": "https://cinema.example.test/billing/webhook/stripe",
    }.items():
        monkeypatch.setenv(name, value)

    async def verified(_config):
        return {
            "verified": True,
            "livemode": True,
            "checks": {
                "product": "PASS",
                "price": "PASS",
                "meter": "PASS",
            },
        }

    monkeypatch.setattr(billing, "verify_operational_link", verified)
    body = client.get("/billing/status").json()
    assert body["checkout_status"] == "LINKED"
    assert body["stripe"]["link_state"] == "LINKED_VERIFIED"
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


def test_usage_history_returns_only_the_callers_recent_proofs(engine):
    account, api_key = engine.accounts.issue(display_name="History", plan="metered")
    other, _other_key = engine.accounts.issue(display_name="Other", plan="metered")
    for index in range(3):
        engine.ledger.append(
            account_id=account.account_id,
            channel="api",
            sku="verified_execution",
            quantity=1,
            unit_price_micros=50_000,
            amount_micros=50_000,
            proof_hash=f"{index + 1:064x}",
            context_hash=f"{index + 100:064x}",
            idempotency_key=f"history-{index}",
            units_before=index,
            recorded_at=f"2026-08-0{index + 1}T00:00:00Z",
        )
    engine.ledger.append(
        account_id=other.account_id,
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=50_000,
        amount_micros=50_000,
        proof_hash="f" * 64,
        context_hash="e" * 64,
        idempotency_key="other-history",
        units_before=0,
    )

    response = client.get(
        "/billing/usage/history?limit=2",
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == account.account_id
    assert body["count"] == 2
    assert [item["proof_hash"] for item in body["items"]] == [
        f"{3:064x}",
        f"{2:064x}",
    ]
    assert all("idempotency_key" not in item for item in body["items"])
    assert body["has_more"] is True
    assert body["next_before_sequence"] == body["items"][-1]["sequence"]

    next_page = client.get(
        f"/billing/usage/history?limit=2&before_sequence={body['next_before_sequence']}",
        headers={"X-DSG-API-Key": api_key},
    ).json()
    assert next_page["count"] == 1
    assert next_page["has_more"] is False
    assert next_page["items"][0]["proof_hash"] == f"{1:064x}"


def test_usage_history_rejects_invalid_limits(engine):
    _account, api_key = engine.accounts.issue(display_name="Limits", plan="free")
    for limit in (0, -1, 101, "bad"):
        response = client.get(
            f"/billing/usage/history?limit={limit}",
            headers={"X-DSG-API-Key": api_key},
        )
        assert response.status_code == 422


def test_usage_history_requires_a_valid_key(engine):
    assert client.get("/billing/usage/history").status_code == 401


def test_persist_uses_flush_and_fsync_before_replace(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    store = LedgerStore(str(path))
    calls = []
    original_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))
    store.append(
        account_id="acct", channel="api", sku="verified_execution", quantity=1,
        unit_price_micros=0, amount_micros=0, proof_hash="a" * 64,
        context_hash="b" * 64, idempotency_key="durability", units_before=0,
    )
    assert calls, "persist must fsync the temporary file before rename"


def test_usage_history_detail_is_tenant_scoped(engine):
    account, api_key = engine.accounts.issue(display_name="Proof detail", plan="metered")
    other, other_key = engine.accounts.issue(display_name="Other detail", plan="metered")
    entry, created = engine.ledger.append(
        account_id=account.account_id,
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=50_000,
        amount_micros=50_000,
        proof_hash="a" * 64,
        context_hash="b" * 64,
        idempotency_key="proof-detail",
        units_before=0,
    )
    assert created is True

    response = client.get(
        f"/billing/usage/history/{entry.sequence}",
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 200
    assert response.json() == {
        "sequence": entry.sequence,
        "period": entry.period,
        "channel": "api",
        "sku": "verified_execution",
        "quantity": 1,
        "amount_micros": 50_000,
        "proof_hash": "a" * 64,
        "context_hash": "b" * 64,
        "recorded_at": entry.recorded_at,
        "entry_hash": entry.entry_hash,
    }
    assert client.get(
        f"/billing/usage/history/{entry.sequence}",
        headers={"X-DSG-API-Key": other_key},
    ).status_code == 404


def test_usage_history_detail_requires_a_valid_key(engine):
    assert client.get("/billing/usage/history/1").status_code == 401


def test_billing_subscription_state_is_customer_scoped(engine):
    account, api_key = engine.accounts.issue(
        display_name="Subscriber",
        plan="metered",
        stripe_customer_id="cus_state",
    )
    engine.accounts.update(
        account.account_id,
        payment_linked=True,
        stripe_subscription_id="sub_state",
    )
    response = client.get(
        "/billing/subscription",
        headers={"X-DSG-API-Key": api_key},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "account_id": account.account_id,
        "plan": "metered",
        "billing_channel": "stripe",
        "payment_linked": True,
        "subscription_active": True,
        "can_manage_in_portal": True,
        "portal_endpoint": "/billing/portal/session",
    }
    assert "stripe_customer_id" not in body
    assert "stripe_subscription_id" not in body


def test_github_billing_state_never_offers_stripe_portal(engine):
    _account, api_key = engine.accounts.issue(
        display_name="GitHub",
        plan="github_pro",
        channel="github_marketplace",
    )
    body = client.get(
        "/billing/subscription",
        headers={"X-DSG-API-Key": api_key},
    ).json()
    assert body["billing_channel"] == "github_marketplace"
    assert body["subscription_active"] is True
    assert body["can_manage_in_portal"] is False
    assert body["portal_endpoint"] is None

    free, free_key = engine.accounts.issue(
        display_name="GitHub Free",
        plan="github_free",
        channel="github_marketplace",
    )
    free_body = client.get(
        "/billing/subscription",
        headers={"X-DSG-API-Key": free_key},
    ).json()
    assert free_body["subscription_active"] is False


def test_billing_subscription_requires_a_valid_key(engine):
    assert client.get("/billing/subscription").status_code == 401


def test_webhook_is_unavailable_until_a_signing_secret_is_configured(engine):
    response = client.post("/billing/webhook/stripe", json={"type": "invoice.paid"})
    assert response.status_code == 503


def test_signed_webhook_updates_the_account(engine, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_configured")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_PRODUCT_ID", "prod_dsg")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_dsg")
    account, _ = engine.accounts.issue(
        display_name="Acme",
        plan="free",
        stripe_customer_id="cus_123",
    )
    payload = json.dumps(
        {
            "id": "evt_1",
            "created": 100,
            "livemode": False,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_123",
                    "subscription": "sub_1",
                    "payment_status": "paid",
                    "metadata": {
                        "dsg_product_id": "prod_dsg",
                        "dsg_price_id": "price_dsg",
                    },
                }
            },
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
    assert block["amount_micros"] == 50_000
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
    assert summary["total_amount_micros"] == 50_000


def test_enforced_metering_requires_a_key(engine, monkeypatch):
    configure_backend(monkeypatch)
    billing.reset_engine(RevenueEngine(enforce=True))

    response = client.post("/verify/evaluate", json=VERIFY_BODY)
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == UNKNOWN_KEY


def test_env_enforcement_fails_closed_without_durable_single_writer_storage(
    engine,
    monkeypatch,
):
    configure_backend(monkeypatch)
    unsafe = RevenueEngine.from_env({"DSG_REVENUE_ENFORCE": "1"})
    billing.reset_engine(unsafe)

    response = client.post("/verify/evaluate", json=VERIFY_BODY)
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "BILLING_STORAGE_NOT_READY"
    assert response.json()["detail"]["remediation"]["code"] == "BILLING_STORAGE_NOT_READY"
    assert unsafe.enforcement_requested is True
    assert unsafe.enforcement_ready is False
    assert unsafe.enforce is False


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


def test_reconciliation_returns_nonzero_when_required_probes_are_unavailable(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        revenue_report,
        "probe",
        lambda _base_url, path, *_args, **_kwargs: {
            "ok": False,
            "status": None,
            "error": "unavailable",
            "path": path,
        },
    )
    result = revenue_report.main(
        [
            "--base-url",
            "https://cinema.invalid",
            "--admin-secret",
            ADMIN_SECRET,
            "--output",
            str(tmp_path / "report.md"),
        ]
    )
    assert result == 3
