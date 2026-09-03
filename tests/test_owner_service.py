from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api_v1 import owner_service
from revenue import api as billing
from revenue.accounts import AccountStore
from revenue.engine import RevenueEngine
from revenue.ledger import LedgerStore


def _owner_key() -> tuple[str, str, str]:
    key_id = "0123456789abcdef"
    secret = "ab" * 24
    api_key = f"dsg_live_{key_id}_{secret}"
    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return api_key, key_id, secret_hash


def _write_config(tmp_path: Path) -> Path:
    _, key_id, secret_hash = _owner_key()
    path = tmp_path / "owner-service-accounts.json"
    path.write_text(
        json.dumps(
            [
                {
                    "account_id": "acct_dsg_owner_test",
                    "display_name": "Owner Test",
                    "plan": "enterprise",
                    "status": "active",
                    "channel": "owner_service",
                    "key_id": key_id,
                    "secret_hash": secret_hash,
                    "mode": "live",
                    "payment_linked": False,
                    "unit_price_micros": 0,
                    "hard_cap_units": None,
                    "created_at": "2026-09-04T00:00:00Z",
                    "updated_at": "2026-09-04T00:00:00Z",
                    "scopes": ["dsg:*", "broker:github:*", "broker:azure:*"],
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def owner_env(monkeypatch, tmp_path):
    path = _write_config(tmp_path)
    monkeypatch.setenv("DSG_OWNER_SERVICE_CONFIG", str(path))
    monkeypatch.setenv("DSG_REVENUE_ADMIN_SECRET", "r" * 40)
    engine = RevenueEngine(accounts=AccountStore(), ledger=LedgerStore(), enforce=True)
    billing.reset_engine(engine)
    return engine


def test_owner_key_bootstraps_enterprise_account_and_authorizes(owner_env):
    api_key, _, _ = _owner_key()
    authenticated = owner_service.authenticate_owner_key(api_key)
    assert authenticated is not None
    account, record = authenticated
    assert account.account_id == "acct_dsg_owner_test"
    assert account.channel == "owner_service"
    assert account.plan == "enterprise"
    assert account.unit_price_micros == 0
    assert account.hard_cap_units is None
    assert record["scopes"] == ["dsg:*", "broker:github:*", "broker:azure:*"]

    authorization = billing.authorize_request(api_key, "verified_execution")
    assert authorization is not None
    assert authorization.authorized is True
    assert authorization.units_remaining is None


def test_owner_middleware_preserves_owner_key_and_bridges_admin_secret(owner_env):
    api_key, _, _ = _owner_key()
    app = FastAPI()
    app.add_middleware(owner_service.OwnerServiceMiddleware)

    @app.get("/api/v1/mcp-probe")
    def mcp_probe(request: Request):
        return {
            "authorization": request.headers.get("authorization"),
            "api_key": request.headers.get("x-dsg-api-key"),
            "owner": bool(getattr(request.state, "dsg_owner_service", False)),
        }

    @app.get("/billing/report")
    def admin_probe(request: Request):
        return {
            "authorization": request.headers.get("authorization"),
            "api_key": request.headers.get("x-dsg-api-key"),
            "owner": bool(getattr(request.state, "dsg_owner_service", False)),
        }

    client = TestClient(app)
    mcp = client.get("/api/v1/mcp-probe", headers={"Authorization": f"Bearer {api_key}"})
    assert mcp.status_code == 200
    assert mcp.json()["authorization"] == f"Bearer {api_key}"
    assert mcp.json()["api_key"] == api_key
    assert mcp.json()["owner"] is True

    admin = client.get("/billing/report", headers={"Authorization": f"Bearer {api_key}"})
    assert admin.status_code == 200
    assert admin.json()["authorization"] == f"Bearer {'r' * 40}"
    assert admin.json()["api_key"] == api_key
    assert admin.json()["owner"] is True


def test_owner_status_never_returns_hash_or_plaintext(owner_env):
    body = owner_service.owner_service_status()
    encoded = json.dumps(body, sort_keys=True)
    assert body["configured"] is True
    assert body["plaintext_secret_stored"] is False
    assert body["admin_master_exposed_to_agent"] is False
    assert "secret_hash" not in encoded
    assert "api_key" not in encoded


def test_owner_config_refuses_plaintext_credentials(monkeypatch, tmp_path):
    path = _write_config(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[0]["api_key"] = "must-not-be-stored"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("DSG_OWNER_SERVICE_CONFIG", str(path))
    with pytest.raises(RuntimeError, match="plaintext"):
        owner_service.owner_service_status()


def test_repository_owner_config_is_hash_only():
    path = Path("config/owner-service-accounts.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload
    for record in payload:
        assert set(record).isdisjoint({"api_key", "secret", "plaintext_key"})
        assert len(record["secret_hash"]) == 64
        assert len(record["key_id"]) == 16


def test_cinema_image_packages_only_owner_hash_config():
    dockerfile = Path("Dockerfile.cinema").read_text(encoding="utf-8")
    assert (
        "COPY config/owner-service-accounts.json ./config/owner-service-accounts.json"
        in dockerfile
    )
    assert "COPY config ./config" not in dockerfile
    assert "COPY config/ ./config" not in dockerfile
