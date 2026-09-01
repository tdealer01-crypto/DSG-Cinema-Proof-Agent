from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from api_v1 import agent_pairing


def _client(monkeypatch):
    account = SimpleNamespace(account_id="acct_test")
    monkeypatch.setattr(agent_pairing, "_authenticated_account", lambda key: ((key or "").strip(), account))
    with agent_pairing._lock:
        agent_pairing._pairings.clear()

    app = FastAPI()
    agent_pairing.install(app)

    @app.post("/mcp")
    def fake_mcp(x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")):
        return {"seen_key": x_dsg_api_key}

    return TestClient(app)


def test_pairing_issues_short_lived_token_without_returning_master_key(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/remote-browser/agent-pair",
        headers={"X-DSG-API-Key": "dsg_live_master"},
        json={"agent_name": "muse-spark", "ttl_seconds": 600},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["paired"] is True
    assert body["pairing_token"].startswith("dsg_pair_")
    assert body["master_key_exposed_to_agent"] is False
    assert "dsg_live_master" not in str(body)
    assert body["mcp_endpoint"].endswith("/mcp")


def test_pairing_token_is_translated_server_side_for_mcp(monkeypatch):
    client = _client(monkeypatch)
    paired = client.post(
        "/remote-browser/agent-pair",
        headers={"X-DSG-API-Key": "dsg_live_master"},
        json={"agent_name": "chat-agent", "ttl_seconds": 600},
    ).json()

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {paired['pairing_token']}"},
    )
    assert response.status_code == 200
    assert response.json() == {"seen_key": "dsg_live_master"}


def test_expired_pairing_token_is_not_promoted_to_master_key(monkeypatch):
    client = _client(monkeypatch)
    paired = client.post(
        "/remote-browser/agent-pair",
        headers={"X-DSG-API-Key": "dsg_live_master"},
        json={"agent_name": "chat-agent", "ttl_seconds": 600},
    ).json()
    digest = agent_pairing._digest(paired["pairing_token"])
    with agent_pairing._lock:
        old = agent_pairing._pairings[digest]
        agent_pairing._pairings[digest] = agent_pairing._Pairing(
            api_key=old.api_key,
            account_id=old.account_id,
            agent_name=old.agent_name,
            expires_at=time.time() - 1,
        )

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {paired['pairing_token']}"},
    )
    assert response.status_code == 200
    assert response.json() == {"seen_key": None}


def test_connect_agent_page_has_show_copy_and_pair_controls(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/remote-browser/connect-agent")
    assert response.status_code == 200
    html = response.text
    assert "Show" in html
    assert "Copy" in html
    assert "Connect Agent" in html
    assert "master DSG key stays in this browser" in html
