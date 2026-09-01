from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import live_transport
from api_v1.store import RecordStore, reset_store


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(cinema_main.app)


@pytest.fixture(autouse=True)
def isolated_connect_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DSG_V1_STORE_PATH", raising=False)
    reset_store(RecordStore(str(tmp_path / "connect-records.json")))
    yield
    reset_store(RecordStore(None))


def test_connect_page_is_mobile_vendor_neutral_and_source_mirror_matches():
    deployed = ROOT / "azure-landing" / "connect.html"
    source = ROOT / "landing" / "connect.html"
    assert deployed.read_bytes() == source.read_bytes()

    html = deployed.read_text(encoding="utf-8")
    required = [
        "UNIVERSAL CONNECT",
        "Use your AI.",
        "GitHub Copilot",
        "Claude / MCP client",
        "ChatGPT / OpenAI",
        "Gemini / other AI",
        "Android",
        "My own Agent / API",
        "GUIDED INSTALL",
        "MCP LIVE",
        "NATIVE PUBLISH PENDING",
        "AUDITED ADAPTER",
        "DIRECT API LIVE",
        "Android detected",
        "/api/v1/mcp",
        "/api/v1/mobile/client-contract",
        "/docs",
        "ghapp%3A%2F%2Fplugins%2Fmarketplace%2Fadd",
        "source%3Dtdealer01-crypto%252FDSG-Cinema-Proof-Agent",
        "ghapp%3A%2F%2Fplugins%2Finstall",
        "source%3Ddsg-governance%2540dsg-agent-plugins",
        "ghapp://session/new?mode=interactive",
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

    # Universal means vendor-neutral transports, not a false native-installer claim.
    assert "No vendor-specific Gemini installer is claimed" in html
    assert "does not claim a one-click Claude installer" in html
    assert "native OpenAI Skills distribution is not yet published" in html
    assert "Native control is restricted to the audited DSG Android identity" in html

    # CLI and raw auth details remain outside normal-customer onboarding.
    assert "copilot plugin marketplace add" not in html
    assert "copilot plugin install" not in html
    assert "X-DSG-API-Key" not in html


def test_universal_connect_truth_matches_repository_channels():
    html = (ROOT / "azure-landing" / "connect.html").read_text(encoding="utf-8")
    plugin_mcp = json.loads((ROOT / "marketplace" / "agent-plugin" / "mcp.json").read_text(encoding="utf-8"))
    launch = json.loads((ROOT / "marketplace" / "launch-manifest.json").read_text(encoding="utf-8"))
    mobile = json.loads((ROOT / "mobile" / "base-apk.identity.json").read_text(encoding="utf-8"))

    mcp_url = plugin_mcp["mcpServers"]["dsg-one"]["url"]
    assert mcp_url.endswith("/api/v1/mcp")
    cinema_base = mcp_url.removesuffix("/api/v1/mcp")
    assert f"const CINEMA = '{cinema_base}'" in html
    assert "const MCP = `${CINEMA}/api/v1/mcp`;" in html

    channels = {item["channel"]: item for item in launch["channels"]}
    assert channels["Direct API"]["status"] == "LIVE"
    assert channels["Direct API"]["public_url"] == f"{cinema_base}/docs"
    assert "const DOCS = `${CINEMA}/docs`;" in html
    assert channels["OpenAI Skills"]["status"] == "READY_FOR_EXTERNAL_SUBMIT"

    assert mobile["package_name"] == "com.dsg.architect"
    assert mobile["artifact_role"] == "audited Android client identity; binary distributed outside source tree"
    assert "audited binary is distributed outside the source tree" in html


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
                "arguments": {"display_name": "Universal first Live", "ttl_seconds": 900},
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
