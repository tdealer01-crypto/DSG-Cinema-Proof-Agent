from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import market_ready_platform as platform


def _sandbox_client(monkeypatch, tmp_path: Path) -> TestClient:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(platform, "RUNTIME", runtime)
    monkeypatch.setattr(platform, "APPS", runtime / "apps")
    monkeypatch.setattr(platform, "STATE", runtime / "state")
    monkeypatch.setattr(platform, "SOURCE", runtime / "source-repo")
    monkeypatch.setattr(platform, "SOURCE_BARE", runtime / "source-repo.git")
    monkeypatch.setattr(platform, "SANDBOX_MODE", True)
    monkeypatch.setattr(platform, "REQUIRE_PLATFORM_AUTH", False)
    monkeypatch.setattr(platform, "MASTER_SECRET_RAW", "s" * 48)
    monkeypatch.setattr(platform, "MASTER_SECRET", ("s" * 48).encode())
    for path in (platform.APPS, platform.STATE):
        path.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    platform.install(app)
    return TestClient(app)


def test_market_ready_install_reaches_healthy_with_bound_callback(monkeypatch, tmp_path):
    client = _sandbox_client(monkeypatch, tmp_path)
    started = client.post(
        "/platform/install/start",
        json={
            "target_id": "market-ready-test",
            "integration": "github",
            "install_path": "web",
            "scope": "selected-repository",
            "permissions": ["metadata:read", "contents:read", "actions:write"],
        },
    )
    assert started.status_code == 200
    installation_id = started.json()["installation_id"]

    authorized = client.post(f"/platform/sandbox/authorize/{installation_id}")
    assert authorized.status_code == 200
    assert authorized.json()["status"] == "HEALTHY"
    assert authorized.json()["verification"]["ok"] is True
    assert authorized.json()["first_result"]["decision"] == "PASS"

    doctor = client.post(f"/platform/install/{installation_id}/doctor", json={})
    assert doctor.status_code == 200
    assert doctor.json()["ok"] is True


def test_production_callback_fails_closed_without_provisioner_secret(monkeypatch, tmp_path):
    client = _sandbox_client(monkeypatch, tmp_path)
    started = client.post(
        "/platform/install/start",
        json={"target_id": "market-ready-secret-test", "integration": "github"},
    ).json()
    monkeypatch.setattr(platform, "MASTER_SECRET_RAW", "")
    monkeypatch.setattr(platform, "MASTER_SECRET", b"")
    response = client.post(f"/platform/sandbox/authorize/{started['installation_id']}")
    assert response.status_code == 503
    assert "DSG_PROVISIONER_SECRET" in response.json()["detail"]
