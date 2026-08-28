"""The Stripe App executor only performs the exact approved GitHub writes."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fastapi.testclient import TestClient
from nacl.public import PrivateKey, SealedBox

import cinema_main
from api_v1 import service, stripe_app_executor
from api_v1.guarded_store import MemoryGuardedEvidenceStore, reset_guarded_store
from api_v1.models import ApprovePlanRequest, PlanDocument
from api_v1.store import RecordStore, reset_store
from api_v1.stripe_app_executor import (
    GitHubActionsConfigurator,
    GitHubAppConfig,
    GitHubPermissionError,
    StripeAppProductionValues,
)
from revenue import api as billing
from revenue.engine import RevenueEngine

client = TestClient(cinema_main.app)


def production_values() -> dict[str, str]:
    return {
        "STRIPE_APP_SIGNING_SECRET": "absec_signing-secret-value",
        "STRIPE_APP_OAUTH_TEST_SECRET_KEY": "sk_test_test-mode-value",
        "STRIPE_APP_OAUTH_SANDBOX_SECRET_KEY": "sk_test_managed-sandbox-value",
        "STRIPE_APP_OAUTH_TEST_AUTHORIZE_URL": "https://connect.stripe.com/test/install/token-one",
        "STRIPE_APP_OAUTH_SANDBOX_AUTHORIZE_URL": "https://connect.stripe.com/sandbox/install/token-two",
        "DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL": (
            "https://connect.stripe.com/oauth/authorize?client_id=ca_live_public"
        ),
    }


@pytest.fixture
def tenant(tmp_path, monkeypatch):
    monkeypatch.delenv("DSG_REVENUE_ENFORCE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    monkeypatch.setenv("GITHUB_APP_CLIENT_ID", "Iv1.test-client-id")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "configured-for-test")
    monkeypatch.setenv(
        "DSG_GITHUB_REPOSITORY", "tdealer01-crypto/DSG-Cinema-Proof-Agent"
    )
    reset_store(RecordStore(str(tmp_path / "stripe-app-executor.json")))
    reset_guarded_store(MemoryGuardedEvidenceStore())
    engine = billing.reset_engine(RevenueEngine(enforce=False))
    account, api_key = engine.accounts.issue(display_name="Stripe App Owner", plan="free")
    yield account, api_key
    billing.reset_engine(RevenueEngine(enforce=False))
    reset_guarded_store(MemoryGuardedEvidenceStore())
    reset_store(RecordStore(None))


def approved_plan(*, target: str = stripe_app_executor.TARGET) -> dict:
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Configure Stripe App production",
                "agent_identity": "dsg-executor",
                "channel": "api",
                "steps": [
                    {
                        "step_id": stripe_app_executor.STEP_ID,
                        "action": stripe_app_executor.ACTION,
                        "target": target,
                        "parameters": {},
                    }
                ],
            }
        )
    )
    return service.approve_plan(
        created["plan_id"],
        ApprovePlanRequest(approver="owner", plan_hash=created["plan_hash"]),
    )


def payload(plan_id: str) -> dict:
    return {
        "plan_id": plan_id,
        "agent_identity": "dsg-executor",
        "idempotency_key": "stripe-config-0001",
        "values": production_values(),
    }


class SuccessfulConfigurator:
    received: StripeAppProductionValues | None = None

    def configure(self, values: StripeAppProductionValues) -> dict:
        self.received = values
        return {
            "source": "github-rest-read-back",
            "repository": "tdealer01-crypto/DSG-Cinema-Proof-Agent",
            "environment": "production",
            "installation": {"id": 117736073, "app_slug": "dsg-governance"},
            "environment_secrets": [
                {
                    "name": name,
                    "created_at": "2026-08-24T00:00:00Z",
                    "updated_at": "2026-08-24T00:00:01Z",
                    "value_exposed": False,
                }
                for name in stripe_app_executor.SECRET_NAMES
            ],
            "repository_variable": {
                "name": stripe_app_executor.VARIABLE_NAME,
                "created_at": "2026-08-24T00:00:00Z",
                "updated_at": "2026-08-24T00:00:01Z",
                "value_matches_submitted": True,
                "value_sha256": "a" * 64,
            },
            "secret_values_exposed": False,
            "read_back_at": "2026-08-24T00:00:02Z",
        }


def test_exact_approved_action_writes_then_returns_read_back_without_values(
    tenant, monkeypatch
):
    _, api_key = tenant
    plan = approved_plan()
    configurator = SuccessfulConfigurator()
    monkeypatch.setattr(stripe_app_executor, "_configurator_factory", lambda: configurator)

    response = client.post(
        "/api/v1/control/configure-stripe-app",
        json=payload(plan["plan_id"]),
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["executed"] is True
    assert body["control"]["decision"] == "ALLOW"
    assert body["evidence"]["source"] == "github-rest-read-back"
    assert body["evidence"]["repository_variable"]["value_matches_submitted"] is True
    assert body["audit"]["recorded"] is True
    assert configurator.received is not None

    serialized = response.text
    for secret in production_values().values():
        assert secret not in serialized
    assert "encrypted_value" not in serialized


def test_out_of_plan_target_blocks_before_configurator_is_built(tenant, monkeypatch):
    _, api_key = tenant
    plan = approved_plan(target="another.stripe.app")
    called = False

    def factory():
        nonlocal called
        called = True
        return SuccessfulConfigurator()

    monkeypatch.setattr(stripe_app_executor, "_configurator_factory", factory)
    response = client.post(
        "/api/v1/control/configure-stripe-app",
        json=payload(plan["plan_id"]),
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "BLOCK"
    assert response.json()["executed"] is False
    assert called is False


def test_missing_server_inputs_wait_without_touching_github(tenant, monkeypatch):
    _, api_key = tenant
    plan = approved_plan()
    monkeypatch.delenv("GITHUB_APP_CLIENT_ID")
    called = False

    def factory():
        nonlocal called
        called = True
        return SuccessfulConfigurator()

    monkeypatch.setattr(stripe_app_executor, "_configurator_factory", factory)
    response = client.post(
        "/api/v1/control/configure-stripe-app",
        json=payload(plan["plan_id"]),
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "WAITING_PERMISSION"
    assert body["executed"] is False
    assert body["control"]["decision"] == "WAITING_PERMISSION"
    assert called is False


def test_github_app_permission_failure_is_a_waiting_state(tenant, monkeypatch):
    _, api_key = tenant
    plan = approved_plan()

    class PermissionDenied:
        def configure(self, values):
            raise GitHubPermissionError(
                operation="verify GitHub App installation permissions",
                missing_permissions=["GitHub App repository permission: Variables (write)"],
                status_code=403,
            )

    monkeypatch.setattr(stripe_app_executor, "_configurator_factory", PermissionDenied)
    response = client.post(
        "/api/v1/control/configure-stripe-app",
        json=payload(plan["plan_id"]),
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "WAITING_PERMISSION"
    assert body["control"]["decision"] == "ALLOW"
    assert body["capability"]["missing"] == [
        "GitHub App repository permission: Variables (write)"
    ]
    assert body["executed"] is False


def test_validation_error_does_not_echo_secret_input(tenant):
    _, api_key = tenant
    plan = approved_plan()
    body = payload(plan["plan_id"])
    invalid = "not-absec-but-still-sensitive"
    body["values"]["STRIPE_APP_SIGNING_SECRET"] = invalid

    response = client.post(
        "/api/v1/control/configure-stripe-app",
        json=body,
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 422
    assert invalid not in response.text


def test_empty_incremental_values_are_rejected_before_github(tenant, monkeypatch):
    _, api_key = tenant
    plan = approved_plan()
    called = False

    def factory():
        nonlocal called
        called = True
        return SuccessfulConfigurator()

    monkeypatch.setattr(stripe_app_executor, "_configurator_factory", factory)
    body = payload(plan["plan_id"])
    body["values"] = {}
    response = client.post(
        "/api/v1/control/configure-stripe-app",
        json=body,
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 422
    assert response.json()["field"] == "values"
    assert response.json()["executed"] is False
    assert called is False


def test_incremental_request_accepts_one_fixed_value(tenant, monkeypatch):
    _, api_key = tenant
    plan = approved_plan()

    class IncrementalConfigurator:
        received: StripeAppProductionValues | None = None

        def configure(self, values: StripeAppProductionValues) -> dict:
            self.received = values
            return {
                "source": "github-rest-read-back",
                "repository": "tdealer01-crypto/DSG-Cinema-Proof-Agent",
                "environment": "production",
                "installation": {"id": 117736073, "app_slug": "dsg-governance"},
                "configured_value_names": ["STRIPE_APP_SIGNING_SECRET"],
                "environment_secrets": [
                    {
                        "name": "STRIPE_APP_SIGNING_SECRET",
                        "created_at": "2026-08-27T00:00:00Z",
                        "updated_at": "2026-08-27T00:00:01Z",
                        "value_exposed": False,
                    }
                ],
                "repository_variable": None,
                "secret_values_exposed": False,
                "read_back_at": "2026-08-27T00:00:02Z",
            }

    configurator = IncrementalConfigurator()
    monkeypatch.setattr(stripe_app_executor, "_configurator_factory", lambda: configurator)
    body = payload(plan["plan_id"])
    body["values"] = {"STRIPE_APP_SIGNING_SECRET": "absec_incremental-value"}
    response = client.post(
        "/api/v1/control/configure-stripe-app",
        json=body,
        headers={"X-DSG-API-Key": api_key},
    )

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "ALLOW"
    assert response.json()["evidence"]["configured_value_names"] == [
        "STRIPE_APP_SIGNING_SECRET"
    ]
    assert configurator.received is not None
    assert configurator.received.secret_values() == {
        "STRIPE_APP_SIGNING_SECRET": "absec_incremental-value"
    }
    assert configurator.received.live_authorize_url() is None
    assert "absec_incremental-value" not in response.text


def test_github_configurator_encrypts_writes_and_reads_back_metadata():
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = signing_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    secret_box_key = PrivateKey.generate()
    public_key = base64.b64encode(bytes(secret_box_key.public_key)).decode()
    values = StripeAppProductionValues.model_validate(production_values())
    state: dict[str, object] = {"variable_created": False, "encrypted": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/installation"):
            return httpx.Response(
                200,
                json={
                    "id": 117736073,
                    "app_slug": "dsg-governance",
                    "permissions": {"environments": "write", "variables": "write"},
                },
            )
        if request.method == "POST" and path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "ghs_installation_token"})
        if request.method == "GET" and path.endswith("/secrets/public-key"):
            return httpx.Response(200, json={"key_id": "key-1", "key": public_key})
        if request.method == "PUT" and "/secrets/STRIPE_" in path:
            submitted = json.loads(request.content)
            name = path.rsplit("/", 1)[-1]
            assert submitted["key_id"] == "key-1"
            assert submitted["encrypted_value"] not in production_values().values()
            encrypted = state["encrypted"]
            assert isinstance(encrypted, dict)
            encrypted[name] = submitted["encrypted_value"]
            return httpx.Response(201)
        if request.method == "GET" and "/secrets/STRIPE_" in path:
            name = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "name": name,
                    "created_at": "2026-08-24T00:00:00Z",
                    "updated_at": "2026-08-24T00:00:01Z",
                },
            )
        if request.method == "GET" and "/actions/variables/" in path:
            if not state["variable_created"]:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "name": stripe_app_executor.VARIABLE_NAME,
                    "value": production_values()[
                        "DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL"
                    ],
                    "created_at": "2026-08-24T00:00:00Z",
                    "updated_at": "2026-08-24T00:00:01Z",
                },
            )
        if request.method == "POST" and path.endswith("/actions/variables"):
            submitted = json.loads(request.content)
            assert submitted == {
                "name": stripe_app_executor.VARIABLE_NAME,
                "value": production_values()[
                    "DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL"
                ],
            }
            state["variable_created"] = True
            return httpx.Response(201)
        raise AssertionError(f"unexpected GitHub request: {request.method} {path}")

    config = GitHubAppConfig(
        client_id="Iv1.test-client-id",
        private_key=pem,
        owner="tdealer01-crypto",
        repository="DSG-Cinema-Proof-Agent",
    )
    http_client = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    evidence = GitHubActionsConfigurator(config, client=http_client).configure(values)

    assert evidence["secret_values_exposed"] is False
    assert len(evidence["environment_secrets"]) == 5
    assert evidence["repository_variable"]["value_matches_submitted"] is True
    encrypted = state["encrypted"]
    assert isinstance(encrypted, dict)
    for name in stripe_app_executor.SECRET_NAMES:
        decrypted = SealedBox(secret_box_key).decrypt(base64.b64decode(encrypted[name])).decode()
        assert decrypted == production_values()[name]


def test_github_configurator_secret_only_does_not_require_variable_permission():
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = signing_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    secret_box_key = PrivateKey.generate()
    public_key = base64.b64encode(bytes(secret_box_key.public_key)).decode()
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and path.endswith("/installation"):
            return httpx.Response(
                200,
                json={
                    "id": 117736073,
                    "app_slug": "dsg-governance",
                    "permissions": {"environments": "write", "variables": "read"},
                },
            )
        if request.method == "POST" and path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "ghs_installation_token"})
        if request.method == "GET" and path.endswith("/secrets/public-key"):
            return httpx.Response(200, json={"key_id": "key-1", "key": public_key})
        if request.method == "PUT" and path.endswith("/STRIPE_APP_SIGNING_SECRET"):
            return httpx.Response(204)
        if request.method == "GET" and path.endswith("/STRIPE_APP_SIGNING_SECRET"):
            return httpx.Response(
                200,
                json={
                    "name": "STRIPE_APP_SIGNING_SECRET",
                    "created_at": "2026-08-27T00:00:00Z",
                    "updated_at": "2026-08-27T00:00:01Z",
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.method} {path}")

    config = GitHubAppConfig(
        client_id="Iv1.test-client-id",
        private_key=pem,
        owner="tdealer01-crypto",
        repository="DSG-Cinema-Proof-Agent",
    )
    http_client = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    values = StripeAppProductionValues.model_validate(
        {"STRIPE_APP_SIGNING_SECRET": "absec_incremental-value"}
    )
    evidence = GitHubActionsConfigurator(config, client=http_client).configure(values)

    assert [row["name"] for row in evidence["environment_secrets"]] == [
        "STRIPE_APP_SIGNING_SECRET"
    ]
    assert evidence["repository_variable"] is None
    assert not any("/actions/variables" in path for _, path in seen)


def test_github_configurator_variable_only_does_not_read_environment_key():
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = signing_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    live_url = production_values()["DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL"]
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and path.endswith("/installation"):
            return httpx.Response(
                200,
                json={
                    "id": 117736073,
                    "app_slug": "dsg-governance",
                    "permissions": {"environments": "read", "variables": "write"},
                },
            )
        if request.method == "POST" and path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "ghs_installation_token"})
        if request.method == "GET" and "/actions/variables/" in path:
            return httpx.Response(
                200,
                json={
                    "name": stripe_app_executor.VARIABLE_NAME,
                    "value": live_url,
                    "created_at": "2026-08-27T00:00:00Z",
                    "updated_at": "2026-08-27T00:00:01Z",
                },
            )
        if request.method == "PATCH" and "/actions/variables/" in path:
            return httpx.Response(204)
        raise AssertionError(f"unexpected GitHub request: {request.method} {path}")

    config = GitHubAppConfig(
        client_id="Iv1.test-client-id",
        private_key=pem,
        owner="tdealer01-crypto",
        repository="DSG-Cinema-Proof-Agent",
    )
    http_client = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    values = StripeAppProductionValues.model_validate(
        {"DSG_STRIPE_APP_OAUTH_LIVE_AUTHORIZE_URL": live_url}
    )
    evidence = GitHubActionsConfigurator(config, client=http_client).configure(values)

    assert evidence["environment_secrets"] == []
    assert evidence["repository_variable"]["value_matches_submitted"] is True
    assert not any(path.endswith("/secrets/public-key") for _, path in seen)
