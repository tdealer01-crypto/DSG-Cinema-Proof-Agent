from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api_v1 import chatgpt_remote_actions, remote_mcp


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    captured: list[dict[str, Any]] = []

    async def fake_handle_message(message: dict, api_key: str | None, *, public_origin: str | None = None):
        captured.append(
            {
                "message": message,
                "api_key": api_key,
                "public_origin": public_origin,
            }
        )
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "content": [{"type": "text", "text": "{}"}],
                    "structuredContent": {
                        "ok": True,
                        "tool": message["params"]["name"],
                        "arguments": message["params"]["arguments"],
                    },
                    "isError": False,
                },
            }
        )

    monkeypatch.setattr(remote_mcp, "handle_message", fake_handle_message)

    app = FastAPI()
    app.include_router(chatgpt_remote_actions.router)
    app.state.captured = captured
    return TestClient(app)


def test_status_requires_no_nested_jsonrpc_params_from_custom_action(client: TestClient):
    response = client.get(
        "/chatgpt-actions/remote-browser/status",
        headers={"X-DSG-API-Key": "dsg_test_key"},
    )
    assert response.status_code == 200
    assert response.json()["tool"] == "remote_status"

    call = client.app.state.captured[-1]
    assert call["api_key"] == "dsg_test_key"
    assert call["message"] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "remote_status", "arguments": {}},
    }


def test_connect_uses_top_level_custom_action_fields(client: TestClient):
    response = client.post(
        "/chatgpt-actions/remote-browser/connect",
        headers={"Authorization": "Bearer dsg_test_key"},
        json={
            "plan_id": "plan_123",
            "agent_identity": "chatgpt-cinema-agent",
            "step_id": "stripe-marketplace",
            "ttl_seconds": 600,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool"] == "remote_agent_connect"
    assert payload["arguments"]["plan_id"] == "plan_123"
    assert "remote_endpoint" not in payload["arguments"]


def test_action_flattens_kind_controller_and_parameters(client: TestClient):
    token = "t" * 40
    response = client.post(
        "/chatgpt-actions/remote-browser/action",
        headers={"X-DSG-API-Key": "dsg_test_key"},
        json={
            "session_token": token,
            "kind": "browser.extract",
            "controller": "agent_verifier",
            "parameters": {},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool"] == "remote_action"
    assert payload["arguments"] == {
        "session_token": token,
        "action": {
            "kind": "browser.extract",
            "controller": "agent_verifier",
            "parameters": {},
        },
    }


def test_disconnect_is_top_level_session_token(client: TestClient):
    token = "d" * 40
    response = client.post(
        "/chatgpt-actions/remote-browser/disconnect",
        headers={"X-DSG-API-Key": "dsg_test_key"},
        json={"session_token": token},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool"] == "remote_disconnect"
    assert payload["arguments"] == {"session_token": token}


def test_mcp_tool_error_maps_back_to_rest_status(monkeypatch: pytest.MonkeyPatch):
    async def fake_handle_message(message: dict, api_key: str | None, *, public_origin: str | None = None):
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [],
                    "structuredContent": {
                        "error": "BROWSER_ORIGIN_BLOCKED",
                        "status_code": 403,
                        "message": "navigation is outside the approved plan",
                    },
                    "isError": True,
                },
            }
        )

    monkeypatch.setattr(remote_mcp, "handle_message", fake_handle_message)
    app = FastAPI()
    app.include_router(chatgpt_remote_actions.router)
    client = TestClient(app)

    response = client.get(
        "/chatgpt-actions/remote-browser/status",
        headers={"X-DSG-API-Key": "dsg_test_key"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "BROWSER_ORIGIN_BLOCKED"
