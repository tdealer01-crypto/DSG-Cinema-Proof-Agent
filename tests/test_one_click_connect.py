from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import live_transport, mcp
from api_v1.store import RecordStore, reset_store
from revenue import api as billing


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(cinema_main.app)


@pytest.fixture(autouse=True)
def isolated_connect_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DSG_V1_STORE_PATH", raising=False)
    reset_store(RecordStore(str(tmp_path / "connect-records.json")))
    yield
    reset_store(RecordStore(None))


def test_connect_page_is_mobile_no_terminal_onboarding_and_source_mirror_matches():
    deployed = ROOT / "azure-landing" / "connect.html"
    source = ROOT / "landing" / "connect.html"
    assert deployed.read_bytes() == source.read_bytes()

    html = deployed.read_text(encoding="utf-8")
    required = [
        "NO TERMINAL REQUIRED",
        "Open Copilot · Add DSG",
        "Open Copilot · Install DSG",
        "Open Copilot · Start Live",
        "No DSG key for first Live view",
        "ghapp%3A%2F%2Fplugins%2Fmarketplace%2Fadd",
        "source%3Dtdealer01-crypto%252FDSG-Cinema-Proof-Agent",
        "ghapp%3A%2F%2Fplugins%2Finstall",
        "source%3Ddsg-governance%2540dsg-agent-plugins",
        "ghapp://session/new?repo=",
        "start DSG Live in OBSERVE mode with dsg_live_start",
        "dsg_live_check_action",
        "01 · LIVE ACTION",
        "02 · PLAN CHECK",
        "03 · DSG EFFECT",
        "04 · WHY",
        "05 · EVIDENCE",
    ]
    for value in required:
        assert value in html

    # CLI remains a developer fallback, not the customer onboarding flow.
    assert "copilot plugin marketplace add" not in html
    assert "copilot plugin install" not in html
    assert "X-DSG-API-Key" not in html


def test_anonymous_observe_session_starts_even_when_enforce_policy_is_enabled(monkeypatch):
    class ProductionLikeEngine:
        enforce = True

    monkeypatch.setattr(live_transport.billing, "get_engine", lambda: ProductionLikeEngine())

    response = client.post(
        "/live/api/sessions",
        json={"display_name": "First value", "ttl_seconds": 900},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session"]["mode"] == "OBSERVE"
    assert body["monitor_url"].endswith(body["live_session_token"])

    # Possessing a Live session token is enough to observe, but production-like
    # enforcement requires a DSG account before control is armed.
    denied = client.post(
        "/live/api/mode",
        headers={"X-DSG-Live-Token": body["live_session_token"]},
        json={"mode": "enforce"},
    )
    assert denied.status_code == 401
    detail = denied.json()["detail"]
    assert detail["error"] == "DSG_ACCOUNT_REQUIRED"
    assert "Observe is available without an API key" in detail["message"]


def test_mcp_plugin_can_start_live_without_api_key_when_revenue_enforcement_is_on(monkeypatch):
    class ProductionLikeEngine:
        enforce = True

    monkeypatch.setattr(live_transport.billing, "get_engine", lambda: ProductionLikeEngine())

    response = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 41,
            "method": "tools/call",
            "params": {
                "name": "dsg_live_start",
                "arguments": {"display_name": "Copilot first Live", "ttl_seconds": 900},
            },
        },
    )
    assert response.status_code == 200
    tool = response.json()["result"]
    assert tool["isError"] is False
    payload = tool["structuredContent"]
    assert payload["session"]["mode"] == "OBSERVE"
    assert payload["monitor_url"].startswith(
        "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/live.html#"
    )


def test_live_contract_discloses_first_value_and_control_boundary():
    response = client.get("/live/api/contract")
    assert response.status_code == 200
    onboarding = response.json()["onboarding"]
    assert onboarding == {
        "anonymous_observe": True,
        "enforce_account_gate_when_revenue_enforced": True,
        "verified_proof_requires_entitlement": True,
    }
