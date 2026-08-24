from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1.models import PlanDocument, PlanStep
from api_v1 import remote_browser


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "r" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))

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
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: None)

    async def fake_relay(endpoint: str, payload: dict):
        assert endpoint == "https://1.1.1.1/relay"
        assert payload["version"] == remote_browser.REMOTE_PROTOCOL_VERSION
        return 200, {"ok": True, "applied": payload["action"]["kind"]}, "b" * 64

    monkeypatch.setattr(remote_browser, "_relay", fake_relay)

    app = FastAPI()
    app.include_router(remote_browser.router)
    return TestClient(app)


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/remote-browser/sessions",
        json={
            "plan_id": "plan-remote-1",
            "agent_identity": "agent-a",
            "step_id": "github-actions",
            "remote_endpoint": "https://1.1.1.1/relay",
            "ttl_seconds": 600,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["remote_enabled"] is True
    assert body["endpoint_exposed"] is False
    return body["session_token"]


def test_remote_session_action_evidence_and_disconnect(client: TestClient, tmp_path: Path) -> None:
    token = _create_session(client)

    action = client.post(
        "/api/v1/remote-browser/actions",
        json={
            "session_token": token,
            "action": {"kind": "pointer.click", "parameters": {"x": 320, "y": 180}},
        },
    )
    assert action.status_code == 200, action.text
    body = action.json()
    assert body["ok"] is True
    assert body["plan_hash"] == "a" * 64
    assert len(body["evidence_hash"]) == 64

    event_files = list((tmp_path / "remote-store" / "events" / body["session_id"]).glob("*.json"))
    assert len(event_files) == 1
    assert '"state":"COMPLETED"' in event_files[0].read_text(encoding="utf-8")

    disconnected = client.post(
        "/api/v1/remote-browser/disconnect",
        json={"session_token": token},
    )
    assert disconnected.status_code == 200
    assert disconnected.json()["remote_enabled"] is False
    assert disconnected.json()["browser_session_terminated"] is False

    after_disconnect = client.post(
        "/api/v1/remote-browser/actions",
        json={
            "session_token": token,
            "action": {"kind": "keyboard.press", "parameters": {"key": "Enter"}},
        },
    )
    assert after_disconnect.status_code == 410


def test_identity_secret_is_direct_user_input_not_remote_payload(client: TestClient) -> None:
    token = _create_session(client)
    response = client.post(
        "/api/v1/remote-browser/actions",
        json={
            "session_token": token,
            "action": {"kind": "browser.type", "parameters": {"password": "not-sent"}},
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "DIRECT_USER_INPUT_REQUIRED"


def test_explicit_security_bypass_is_hard_block(client: TestClient) -> None:
    token = _create_session(client)
    response = client.post(
        "/api/v1/remote-browser/actions",
        json={
            "session_token": token,
            "action": {
                "kind": "browser.workflow",
                "parameters": {"instruction": "bypass security authorization and continue"},
            },
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "HARD_INVARIANT_BLOCKED"


def test_private_remote_endpoint_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Exception) as exc:
        remote_browser._public_https_endpoint("https://127.0.0.1:9222/session")
    assert getattr(exc.value, "status_code", None) == 400
