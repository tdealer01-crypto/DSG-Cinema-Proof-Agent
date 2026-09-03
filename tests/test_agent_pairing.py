from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from api_v1 import agent_pairing


def _client(tmp_path: Path, monkeypatch, *, clear: bool = True):
    account = SimpleNamespace(account_id="acct_test")
    monkeypatch.setattr(agent_pairing, "_authenticated_account", lambda key: ((key or "").strip(), account))
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("DSG_AGENT_PAIRING_KEY", "p" * 64)
    if clear:
        with agent_pairing._lock:
            agent_pairing._pairings.clear()

    app = FastAPI()
    agent_pairing.install(app)

    @app.post("/mcp")
    def fake_mcp(x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key")):
        return {"seen_key": x_dsg_api_key}

    return TestClient(app)


def _pair(client: TestClient) -> dict:
    response = client.post(
        "/remote-browser/agent-pair",
        headers={"X-DSG-API-Key": "dsg_live_master"},
        json={"agent_name": "chat-agent", "ttl_seconds": 600},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pairing_issues_short_lived_token_without_returning_master_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _pair(client)
    assert body["paired"] is True
    assert body["pairing_token"].startswith("dsg_pair_")
    assert body["master_key_exposed_to_agent"] is False
    assert body["durable_pairing_store"] is True
    assert body["pairing_token_persisted"] is False
    assert body["api_key_persisted_plaintext"] is False
    assert "dsg_live_master" not in str(body)
    assert body["mcp_endpoint"].endswith("/mcp")


def test_pairing_record_persists_only_hash_and_encrypted_api_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    paired = _pair(client)
    token = paired["pairing_token"]
    digest = agent_pairing._digest(token)
    record_path = agent_pairing._record_path(digest)
    assert record_path.exists()

    raw = record_path.read_text(encoding="utf-8")
    record = json.loads(raw)
    assert record["token_hash"] == digest
    assert record["api_key_ciphertext"]
    assert record["claimed_at"] is None
    assert token not in raw
    assert "dsg_live_master" not in raw
    assert "api_key\"" not in raw


def test_pairing_token_is_translated_server_side_for_mcp(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    paired = _pair(client)

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {paired['pairing_token']}"},
    )
    assert response.status_code == 200
    assert response.json() == {"seen_key": "dsg_live_master"}


def test_pairing_survives_replica_process_state_reset_via_shared_store(tmp_path, monkeypatch):
    replica_a = _client(tmp_path, monkeypatch)
    paired = _pair(replica_a)

    # Simulate a second replica/restarted process: a fresh registry instance has
    # no process memory, but it points at the same durable production-style store.
    monkeypatch.setattr(agent_pairing, "_pairings", agent_pairing._DurablePairingRegistry())
    replica_b = _client(tmp_path, monkeypatch, clear=False)
    response = replica_b.post(
        "/mcp",
        headers={"Authorization": f"Bearer {paired['pairing_token']}"},
    )
    assert response.status_code == 200
    assert response.json() == {"seen_key": "dsg_live_master"}


def test_first_claim_marker_is_durable_and_reuse_keeps_mcp_session_working(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    paired = _pair(client)
    digest = agent_pairing._digest(paired["pairing_token"])
    path = agent_pairing._record_path(digest)
    assert json.loads(path.read_text(encoding="utf-8"))["claimed_at"] is None

    first = client.post("/mcp", headers={"Authorization": f"Bearer {paired['pairing_token']}"})
    assert first.json() == {"seen_key": "dsg_live_master"}
    first_claim = json.loads(path.read_text(encoding="utf-8"))["claimed_at"]
    assert isinstance(first_claim, float)

    second = client.post("/mcp", headers={"Authorization": f"Bearer {paired['pairing_token']}"})
    assert second.json() == {"seen_key": "dsg_live_master"}
    assert json.loads(path.read_text(encoding="utf-8"))["claimed_at"] == first_claim


def test_tampered_ciphertext_fails_closed_without_master_key_promotion(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    paired = _pair(client)
    digest = agent_pairing._digest(paired["pairing_token"])
    path = agent_pairing._record_path(digest)
    record = json.loads(path.read_text(encoding="utf-8"))

    # Mutate the decoded ciphertext bytes, not merely an unpadded Base64 trailing
    # character whose unused low bits can decode to the exact same byte string.
    encoded = record["api_key_ciphertext"]
    tampered = bytearray(agent_pairing._b64decode(encoded))
    tampered[-1] ^= 0x01
    record["api_key_ciphertext"] = agent_pairing._b64encode(bytes(tampered))
    assert record["api_key_ciphertext"] != encoded
    path.write_text(json.dumps(record), encoding="utf-8")

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {paired['pairing_token']}"},
    )
    assert response.status_code == 200
    assert response.json() == {"seen_key": None}


def test_expired_pairing_token_is_not_promoted_to_master_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    paired = _pair(client)
    digest = agent_pairing._digest(paired["pairing_token"])
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


def test_revoke_removes_durable_pairing_for_all_replicas(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    paired = _pair(client)
    token = paired["pairing_token"]
    revoked = client.post(
        "/remote-browser/agent-pair/revoke",
        headers={"X-DSG-API-Key": "dsg_live_master"},
        json={"pairing_token": token},
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"revoked": True}
    assert agent_pairing.resolve_pairing(token) is None


def test_connect_agent_page_has_show_copy_and_pair_controls(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.get("/remote-browser/connect-agent")
    assert response.status_code == 200
    html = response.text
    assert "Show" in html
    assert "Copy" in html
    assert "Connect Agent" in html
    assert "master DSG key stays in this browser" in html
