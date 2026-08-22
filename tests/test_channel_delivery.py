"""Sales channel to delivered value: activation, attribution, and remediation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import cinema_main
from revenue import api as billing
from revenue.accounts import AccountStore
from revenue.activation import (
    ACTIVATED,
    ActivationService,
    RateLimiter,
    activation_ref,
)
from revenue.engine import RevenueEngine
from revenue.remediation import (
    ACCOUNT_SUSPENDED,
    ACTIVATION_DISABLED,
    ACTIVATION_EXISTS,
    ACTIVATION_RATE_LIMITED,
    BACKEND_UNAVAILABLE,
    PAYMENT_NOT_LINKED,
    QUOTA_EXCEEDED,
    UNKNOWN_KEY,
    VERIFICATION_NOT_PROVED,
    all_codes,
    remediation_for,
)

client = TestClient(cinema_main.app)

ADMIN_SECRET = "A" * 48

VALID_PROOF = {
    "verification": "VERIFIED_GLOBAL_OPTIMUM",
    "verified": True,
    "witness": [1, 0, 0],
    "energy_exact": "-100",
    "proof_hash": "a" * 64,
    "request_hash": "b" * 64,
}

VERIFY_BODY = {
    "execution_id": "exec-channel-001",
    "channel": "github",
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
    monkeypatch.setenv("DSG_REVENUE_ADMIN_SECRET", ADMIN_SECRET)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("DSG_ACTIVATION_ENABLED", raising=False)
    instance = billing.reset_engine(RevenueEngine(enforce=False))
    yield instance
    billing.reset_engine(RevenueEngine(enforce=False))


def configure_backend(monkeypatch, ready=True, proof=None):
    monkeypatch.setenv("DSG_BACKEND_BASE_URL", "https://z3.example.test")
    monkeypatch.setenv("DSG_BACKEND_API_KEY", "z" * 32)
    monkeypatch.setenv("CINEMA_API_SECRET", "c" * 32)

    async def fake_z3_request(method, path, payload=None):
        if path == "/ready":
            return (200, {"status": "ready"}) if ready else (503, {"status": "blocked"})
        return 200, dict(proof or VALID_PROOF)

    monkeypatch.setattr(cinema_main, "z3_request", fake_z3_request)


def activate(channel="github", activation_id="acme/repo", name="Acme"):
    return client.post(
        "/billing/activate",
        json={"channel": channel, "activation_id": activation_id, "display_name": name},
    )


# --------------------------------------------------------------- remediation
def test_every_denial_code_carries_a_concrete_next_step():
    for code in all_codes():
        fix = remediation_for(code).to_dict()
        assert fix["next_step"].strip(), code
        assert fix["problem"].strip(), code
        assert fix["cause"].strip(), code
        assert isinstance(fix["self_service"], bool), code
        assert fix["docs"].startswith("https://"), code


def test_an_unknown_code_still_produces_a_usable_next_step():
    fix = remediation_for("SOMETHING_NEW")
    assert fix.code == "SOMETHING_NEW"
    assert "diagnose" in fix.next_step


def test_the_key_denial_points_at_self_serve_activation():
    fix = remediation_for(UNKNOWN_KEY)
    assert fix.self_service is True
    assert "/billing/activate" in fix.next_step


def test_a_denial_needing_an_operator_says_so():
    assert remediation_for(ACTIVATION_EXISTS).self_service is False
    assert remediation_for(ACTIVATION_DISABLED).self_service is False


# ---------------------------------------------------------------- activation
def test_activation_issues_a_working_key_without_an_operator(engine, monkeypatch):
    configure_backend(monkeypatch)
    response = activate()
    assert response.status_code == 201

    body = response.json()
    assert body["decision"] == ACTIVATED
    assert body["api_key"].startswith("dsg_live_")
    assert body["plan"]["plan"] == "free"
    assert body["account"]["channel"] == "github"
    assert body["account"]["self_activated"] is True
    assert "secret_hash" not in json.dumps(body["account"])

    proof = client.post(
        "/verify/evaluate",
        json=VERIFY_BODY,
        headers={"X-DSG-API-Key": body["api_key"]},
    )
    assert proof.status_code == 200
    assert proof.json()["billing"]["metered"] is True


def test_activation_is_idempotent_and_case_insensitive(engine):
    first = activate(activation_id="Acme/Repo")
    assert first.status_code == 201

    second = activate(activation_id="acme/repo")
    assert second.status_code == 409
    assert second.json()["decision"] == ACTIVATION_EXISTS
    assert "api_key" not in second.json()
    assert len(engine.accounts.all()) == 1


def test_simultaneous_activation_retries_issue_exactly_one_key():
    store = AccountStore()
    service = ActivationService(store)

    def run(_: int):
        return service.activate(
            channel="github",
            activation_id="acme/concurrent",
            display_name="Acme",
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(run, range(24)))

    assert sum(result.decision == ACTIVATED for result in results) == 1
    assert sum(result.decision == ACTIVATION_EXISTS for result in results) == 23
    assert sum(result.api_key is not None for result in results) == 1
    assert len(store.all()) == 1


def test_activation_can_only_grant_the_free_plan(engine):
    body = activate().json()
    account = engine.accounts.get(body["account"]["account_id"])
    assert account.plan == "free"
    assert account.payment_linked is False


def test_activation_rejects_a_malformed_channel(engine):
    response = client.post(
        "/billing/activate",
        json={"channel": "Not A Channel", "activation_id": "x-1", "display_name": "X"},
    )
    assert response.status_code == 422


def test_activation_is_rate_limited_with_a_retry_hint(engine):
    engine_accounts = engine.accounts
    service = ActivationService(
        engine_accounts,
        limiter=RateLimiter(window_seconds=600, per_channel_limit=2, global_limit=10),
    )
    billing._activation = service

    assert activate(activation_id="a-1").status_code == 201
    assert activate(activation_id="a-2").status_code == 201

    limited = activate(activation_id="a-3")
    assert limited.status_code == 429
    body = limited.json()
    assert body["decision"] == ACTIVATION_RATE_LIMITED
    assert body["retry_after_seconds"] > 0
    assert limited.headers["Retry-After"] == str(body["retry_after_seconds"])


def test_the_global_limit_stops_a_multi_channel_flood():
    store = AccountStore()
    service = ActivationService(
        store,
        limiter=RateLimiter(window_seconds=600, per_channel_limit=50, global_limit=3),
    )
    for index in range(3):
        assert service.activate(
            channel=f"chan{index}", activation_id=f"id-{index}", display_name="X"
        ).decision == ACTIVATED

    blocked = service.activate(channel="chan9", activation_id="id-9", display_name="X")
    assert blocked.decision == ACTIVATION_RATE_LIMITED


def test_activation_can_be_turned_off(engine):
    billing._activation = ActivationService(engine.accounts, enabled=False)
    response = activate()
    assert response.status_code == 503
    assert response.json()["decision"] == ACTIVATION_DISABLED
    assert response.json()["remediation"]["self_service"] is False


def test_activation_reference_does_not_leak_the_activation_id():
    reference = activation_ref("github", "acme/private-repo")
    assert len(reference) == 64
    assert "acme" not in reference


def test_the_activation_reference_is_never_returned_to_the_caller(engine):
    body = activate().json()
    assert "activation_ref" not in body["account"]
    assert body["account"]["self_activated"] is True


# --------------------------------------------------------------- attribution
def test_revenue_is_attributed_to_the_channel_that_delivered_it(engine, monkeypatch):
    configure_backend(monkeypatch)

    github_key = activate(channel="github", activation_id="gh-1").json()["api_key"]
    plugin_key = activate(channel="openai_plugin", activation_id="ai-1").json()["api_key"]

    through_github = client.post(
        "/verify/evaluate",
        json={**VERIFY_BODY, "execution_id": "exec-github-1", "channel": "github"},
        headers={"X-DSG-API-Key": github_key},
    )
    through_plugin = client.post(
        "/verify/evaluate",
        json={**VERIFY_BODY, "execution_id": "exec-plugin-1", "channel": "openai_plugin"},
        headers={"X-DSG-API-Key": plugin_key},
    )
    assert through_github.status_code == 200
    assert through_plugin.status_code == 200

    by_channel = {row["channel"]: row for row in engine.channel_report()}
    assert by_channel["github"]["units"] == 1
    assert by_channel["openai_plugin"]["units"] == 1
    assert by_channel["github"]["accounts_acquired"] == 1
    assert by_channel["openai_plugin"]["accounts_acquired"] == 1


def test_acquisition_channel_and_delivery_channel_are_reported_separately(
    engine, monkeypatch
):
    configure_backend(monkeypatch)
    # Acquired through the landing page, but the proof is delivered via Azure.
    key = activate(channel="api", activation_id="landing-1").json()["api_key"]
    client.post(
        "/verify/evaluate",
        json={**VERIFY_BODY, "channel": "azure"},
        headers={"X-DSG-API-Key": key},
    )

    by_channel = {row["channel"]: row for row in engine.channel_report()}
    assert by_channel["api"]["accounts_acquired"] == 1
    assert by_channel["api"]["units"] == 0
    assert by_channel["azure"]["units"] == 1
    assert by_channel["azure"]["accounts_acquired"] == 0


def test_the_period_report_includes_the_channel_breakdown(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(channel="github", activation_id="gh-report").json()["api_key"]
    client.post("/verify/evaluate", json=VERIFY_BODY, headers={"X-DSG-API-Key": key})

    report = client.get(
        "/billing/report", headers={"Authorization": f"Bearer {ADMIN_SECRET}"}
    ).json()
    assert any(row["channel"] == "github" for row in report["by_channel"])


# ------------------------------------------------------- denials are useful
def test_a_refused_verification_returns_the_fix_not_just_a_status(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(activation_id="capped").json()["api_key"]
    account_id = client.get(
        "/billing/usage", headers={"X-DSG-API-Key": key}
    ).json()["account"]["account_id"]
    client.patch(
        f"/billing/accounts/{account_id}",
        headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        json={"hard_cap_units": 0},
    )

    refused = client.post(
        "/verify/evaluate", json=VERIFY_BODY, headers={"X-DSG-API-Key": key}
    )
    assert refused.status_code == 402
    detail = refused.json()["detail"]
    assert detail["error"] == QUOTA_EXCEEDED
    assert detail["remediation"]["code"] == QUOTA_EXCEEDED
    assert detail["remediation"]["self_service"] is True
    assert detail["remediation"]["next_step"]


def test_an_unverified_proof_is_refused_with_a_no_charge_assurance(engine, monkeypatch):
    configure_backend(
        monkeypatch,
        proof={**VALID_PROOF, "verified": False, "verification": "COUNTEREXAMPLE_FOUND"},
    )
    key = activate(activation_id="unverified").json()["api_key"]
    refused = client.post(
        "/verify/evaluate", json=VERIFY_BODY, headers={"X-DSG-API-Key": key}
    )
    assert refused.status_code == 502
    detail = refused.json()["detail"]
    assert detail["error"] == VERIFICATION_NOT_PROVED
    assert "never billed" in detail["remediation"]["next_step"]
    assert engine.ledger.size() == 0


def test_a_bad_key_is_refused_with_the_activation_path(engine, monkeypatch):
    configure_backend(monkeypatch)
    refused = client.post(
        "/verify/evaluate",
        json=VERIFY_BODY,
        headers={"X-DSG-API-Key": "dsg_live_" + "0" * 16 + "_" + "0" * 48},
    )
    assert refused.status_code == 401
    assert "/billing/activate" in refused.json()["detail"]["remediation"]["next_step"]


# ------------------------------------------------------------------ diagnose
def test_diagnose_needs_no_credential_and_reports_ready(engine, monkeypatch):
    configure_backend(monkeypatch)
    body = client.get("/support/diagnose").json()
    assert body["status"] == "READY"
    names = {check["check"]: check["status"] for check in body["checks"]}
    assert names["service_configuration"] == "pass"
    assert names["verification_backend"] == "pass"
    assert names["api_key"] == "skip"


def test_diagnose_reports_a_key_holder_quota(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(activation_id="diag-1").json()["api_key"]
    body = client.get("/support/diagnose", headers={"X-DSG-API-Key": key}).json()
    assert body["status"] == "READY"
    quota = next(c for c in body["checks"] if c["check"] == "quota")
    assert "25 remaining" in quota["detail"]


def test_diagnose_names_the_blocking_problem_for_a_capped_account(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(activation_id="diag-2").json()["api_key"]
    account_id = client.get(
        "/billing/usage", headers={"X-DSG-API-Key": key}
    ).json()["account"]["account_id"]
    client.patch(
        f"/billing/accounts/{account_id}",
        headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        json={"hard_cap_units": 0},
    )

    body = client.get("/support/diagnose", headers={"X-DSG-API-Key": key}).json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["remediation"]["code"] == QUOTA_EXCEEDED
    quota = next(c for c in body["checks"] if c["check"] == "quota")
    assert quota["status"] == "fail"


def test_diagnose_reports_a_suspended_account(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(activation_id="diag-3").json()["api_key"]
    account_id = client.get(
        "/billing/usage", headers={"X-DSG-API-Key": key}
    ).json()["account"]["account_id"]
    client.patch(
        f"/billing/accounts/{account_id}",
        headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        json={"status": "suspended"},
    )

    body = client.get("/support/diagnose", headers={"X-DSG-API-Key": key}).json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["remediation"]["code"] == ACCOUNT_SUSPENDED


def test_diagnose_reports_a_metered_plan_without_payment(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(activation_id="diag-4").json()["api_key"]
    account_id = client.get(
        "/billing/usage", headers={"X-DSG-API-Key": key}
    ).json()["account"]["account_id"]
    client.patch(
        f"/billing/accounts/{account_id}",
        headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        json={"plan": "metered"},
    )

    body = client.get("/support/diagnose", headers={"X-DSG-API-Key": key}).json()
    assert body["remediation"]["code"] == PAYMENT_NOT_LINKED
    payment = next(c for c in body["checks"] if c["check"] == "paid_entitlement")
    assert payment["status"] == "fail"


def test_diagnose_reports_an_unavailable_backend_without_blaming_the_caller(
    engine, monkeypatch
):
    configure_backend(monkeypatch, ready=False)
    body = client.get("/support/diagnose").json()
    assert body["status"] == "SERVICE_UNAVAILABLE"
    assert body["remediation"]["code"] == BACKEND_UNAVAILABLE
    assert "nothing was billed" in body["remediation"]["next_step"]


def test_diagnose_reports_incomplete_configuration(engine, monkeypatch):
    monkeypatch.delenv("DSG_BACKEND_BASE_URL", raising=False)
    monkeypatch.delenv("DSG_BACKEND_API_KEY", raising=False)
    body = client.get("/support/diagnose").json()
    assert body["status"] == "SERVICE_UNAVAILABLE"
    assert body["remediation"]["self_service"] is False
    backend = next(c for c in body["checks"] if c["check"] == "verification_backend")
    assert backend["status"] == "skip"


def test_diagnose_requires_a_key_when_enforcement_is_on(engine, monkeypatch):
    configure_backend(monkeypatch)
    billing.reset_engine(RevenueEngine(enforce=True))
    body = client.get("/support/diagnose").json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["remediation"]["code"] == UNKNOWN_KEY


def test_diagnose_reports_unsafe_paid_enforcement_as_service_configuration(
    engine,
    monkeypatch,
):
    configure_backend(monkeypatch)
    unsafe = RevenueEngine.from_env({"DSG_REVENUE_ENFORCE": "1"})
    billing.reset_engine(unsafe)

    body = client.get("/support/diagnose").json()
    assert body["status"] == "SERVICE_UNAVAILABLE"
    assert body["remediation"]["code"] == "BILLING_STORAGE_NOT_READY"
    storage = next(c for c in body["checks"] if c["check"] == "billing_storage")
    assert storage["status"] == "fail"


def test_diagnose_never_reveals_more_than_pass_or_fail_for_a_bad_key(engine, monkeypatch):
    configure_backend(monkeypatch)
    body = client.get(
        "/support/diagnose",
        headers={"X-DSG-API-Key": "dsg_live_" + "0" * 16 + "_" + "0" * 48},
    ).json()
    assert body["billing"] is None
    assert not any(check["check"] == "account_status" for check in body["checks"])


def test_onboarding_status_requires_a_valid_key(engine, monkeypatch):
    configure_backend(monkeypatch)
    assert client.get("/onboarding/status").status_code == 401


def test_onboarding_status_guides_an_activated_customer_to_first_proof(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(activation_id="onboarding-1").json()["api_key"]
    response = client.get("/onboarding/status", headers={"X-DSG-API-Key": key})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ACTION_REQUIRED"
    assert body["current_step"] == "RUN_FIRST_PROOF"
    assert body["progress"] == 67
    assert body["steps"] == {
        "account_activated": True,
        "api_key_authenticated": True,
        "backend_connected": True,
        "first_proof_completed": False,
    }
    assert body["next_action"]["method"] == "POST"
    assert body["next_action"]["endpoint"] == "/onboarding/first-proof"


def test_guided_first_proof_requires_a_valid_key(engine, monkeypatch):
    configure_backend(monkeypatch)
    assert client.post("/onboarding/first-proof").status_code == 401


def test_guided_first_proof_returns_a_real_metered_receipt(engine, monkeypatch):
    configure_backend(monkeypatch)
    key = activate(activation_id="guided-proof").json()["api_key"]
    response = client.post(
        "/onboarding/first-proof",
        headers={"X-DSG-API-Key": key},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["verified"] is True
    assert body["verification"] == "VERIFIED_GLOBAL_OPTIMUM"
    assert len(body["proof_hash"]) == 64
    assert body["billing"]["metered"] is True
    assert body["synthetic"] is True
    assert body["purpose"] == "onboarding"
    assert body["authorized_action_completion"] is False

    duplicate = client.post(
        "/onboarding/first-proof",
        headers={"X-DSG-API-Key": key},
    ).json()
    assert duplicate["proof_hash"] == body["proof_hash"]
    assert duplicate["billing"] == {"metered": False, "duplicate": True}

    status = client.get(
        "/onboarding/status", headers={"X-DSG-API-Key": key}
    ).json()
    assert status["current_step"] == "COMPLETE"
    assert status["progress"] == 100


def test_onboarding_status_completes_after_first_billable_proof(engine, monkeypatch):
    configure_backend(monkeypatch)
    activated = activate(activation_id="onboarding-2").json()
    key = activated["api_key"]
    account_id = activated["account"]["account_id"]
    account = engine.accounts.get(account_id)
    authorization = engine.authorize(key, "verified_execution")
    engine.record_usage(
        authorization,
        sku="verified_execution",
        receipt={
            "verified": True,
            "verification": "VERIFIED_GLOBAL_OPTIMUM",
            "proof_hash": "a" * 64,
            "context_hash": "b" * 64,
        },
    )

    body = client.get(
        "/onboarding/status", headers={"X-DSG-API-Key": key}
    ).json()
    assert body["status"] == "READY"
    assert body["current_step"] == "COMPLETE"
    assert body["progress"] == 100
    assert body["steps"]["first_proof_completed"] is True
    assert body["next_action"] is None
