from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import remote_browser, remote_pairing, remote_transport
from api_v1.models import PlanDocument, PlanStep


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "r" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))

    authorization = SimpleNamespace(account=SimpleNamespace(account_id="acct-test"))
    monkeypatch.setattr(remote_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: authorization)

    document = PlanDocument(
        title="Configure GitHub Actions",
        agent_identity="agent-a",
        steps=[
            PlanStep(
                step_id="github-actions",
                action="configure_github_actions",
                target="github.com",
                parameters={},
            )
        ],
    )
    record = {
        "plan_id": "plan-remote-1",
        "plan_hash": "a" * 64,
        "status": "APPROVED",
    }
    monkeypatch.setattr(remote_browser.service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(remote_browser.service, "plan_document", lambda _record: document)

    async def fake_relay(endpoint: str, payload: dict):
        assert endpoint == "https://1.1.1.1/relay"
        return 200, {"ok": True, "applied": payload["action"]["kind"]}, "b" * 64

    monkeypatch.setattr(remote_browser, "_relay", fake_relay)

    app = FastAPI()
    app.include_router(remote_transport.router)
    app.include_router(remote_pairing.router)
    return TestClient(app)


def _agent_connect(client: TestClient):
    return client.post(
        "/remote-browser/agent-connect",
        headers={"X-DSG-API-Key": "dsg_live_test"},
        json={
            "plan_id": "plan-remote-1",
            "agent_identity": "agent-a",
            "step_id": "github-actions",
            "remote_endpoint": "https://1.1.1.1/relay",
            "ttl_seconds": 600,
        },
    )


def test_user_arms_agent_connects_records_evidence_and_user_disables(client: TestClient):
    headers = {"X-DSG-API-Key": "dsg_live_test"}

    initial = client.get("/remote-browser/status", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["remote_enabled"] is False
    assert initial.json()["agent_connection"] == "off"

    before_enable = _agent_connect(client)
    assert before_enable.status_code == 409
    assert before_enable.json()["detail"]["error"] == "REMOTE_NOT_ENABLED_BY_USER"

    enabled = client.post("/remote-browser/enable", headers=headers)
    assert enabled.status_code == 200
    assert enabled.json()["remote_enabled"] is True
    assert enabled.json()["agent_connection"] == "waiting"

    connected = _agent_connect(client)
    assert connected.status_code == 201, connected.text
    body = connected.json()
    assert body["remote_enabled"] is True
    token = body["session_token"]

    status = client.get("/remote-browser/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["remote_enabled"] is True
    assert status.json()["agent_connection"] == "connected"
    assert status.json()["active_sessions"] == 1

    action = client.post(
        "/remote-browser/actions",
        headers=headers,
        json={
            "session_token": token,
            "action": {"kind": "pointer.click", "parameters": {"x": 320, "y": 180}},
        },
    )
    assert action.status_code == 200, action.text
    assert len(action.json()["evidence_hash"]) == 64

    evidenced = client.get("/remote-browser/status", headers=headers)
    latest = evidenced.json()["latest_evidence"]
    assert latest["action_kind"] == "pointer.click"
    assert latest["evidence_hash"] == action.json()["evidence_hash"]

    disabled = client.post("/remote-browser/disable", headers=headers)
    assert disabled.status_code == 200
    assert disabled.json()["remote_enabled"] is False
    assert disabled.json()["revoked_sessions"] == 1
    assert disabled.json()["user_browser_session"] == "unchanged"

    after_disable = client.post(
        "/remote-browser/actions",
        headers=headers,
        json={
            "session_token": token,
            "action": {"kind": "keyboard.press", "parameters": {"key": "Enter"}},
        },
    )
    assert after_disable.status_code == 410


def test_enable_is_idempotent_and_does_not_require_plan_fields(client: TestClient):
    headers = {"X-DSG-API-Key": "dsg_live_test"}
    first = client.post("/remote-browser/enable", headers=headers)
    second = client.post("/remote-browser/enable", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["remote_enabled"] is True
    assert second.json()["remote_enabled"] is True
