from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import remote_browser, remote_mcp, remote_pairing
from api_v1.models import PlanDocument, PlanStep


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "r" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))

    authorization = SimpleNamespace(account=SimpleNamespace(account_id="acct-mcp"))
    monkeypatch.setattr(remote_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: authorization)

    document = PlanDocument(
        title="Configure GitHub Actions",
        agent_identity="chatgpt",
        steps=[
            PlanStep(
                step_id="github-actions",
                action="configure_github_actions",
                target="github.com",
                parameters={},
            )
        ],
    )
    record = {"plan_id": "plan-mcp-1", "plan_hash": "a" * 64, "status": "APPROVED"}
    monkeypatch.setattr(remote_browser.service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(remote_browser.service, "plan_document", lambda _record: document)

    async def fake_relay(endpoint: str, payload: dict):
        assert endpoint == "https://1.1.1.1/relay"
        return 200, {"ok": True, "kind": payload["action"]["kind"]}, "c" * 64

    monkeypatch.setattr(remote_browser, "_relay", fake_relay)

    app = FastAPI()
    app.include_router(remote_pairing.router)
    app.include_router(remote_mcp.router)
    return TestClient(app)


def _rpc(client: TestClient, method: str, params: dict | None = None, message_id: int = 1):
    return client.post(
        "/mcp",
        headers={"Authorization": "Bearer dsg_live_test"},
        json={"jsonrpc": "2.0", "id": message_id, "method": method, "params": params or {}},
    )


def _tool(client: TestClient, name: str, arguments: dict | None = None, message_id: int = 1):
    response = _rpc(
        client,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
        message_id=message_id,
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_mcp_lists_remote_tools_and_supports_chat_driven_flow(client: TestClient):
    initialized = _rpc(client, "initialize")
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "dsg-cinema-remote"

    listed = _rpc(client, "tools/list")
    names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert names == {
        "remote_contract",
        "remote_status",
        "remote_agent_connect",
        "remote_action",
        "remote_disconnect",
    }

    headers = {"X-DSG-API-Key": "dsg_live_test"}
    enabled = client.post("/remote-browser/enable", headers=headers)
    assert enabled.status_code == 200
    assert enabled.json()["agent_connection"] == "waiting"

    status = _tool(client, "remote_status")
    assert status["isError"] is False
    assert status["structuredContent"]["agent_connection"] == "waiting"

    connected = _tool(
        client,
        "remote_agent_connect",
        {
            "plan_id": "plan-mcp-1",
            "agent_identity": "chatgpt",
            "step_id": "github-actions",
            "remote_endpoint": "https://1.1.1.1/relay",
            "ttl_seconds": 600,
        },
    )
    assert connected["isError"] is False
    token = connected["structuredContent"]["session_token"]

    action = _tool(
        client,
        "remote_action",
        {
            "session_token": token,
            "action": {"kind": "pointer.click", "parameters": {"x": 12, "y": 34}},
        },
    )
    assert action["isError"] is False
    assert action["structuredContent"]["ok"] is True
    assert len(action["structuredContent"]["evidence_hash"]) == 64

    disconnected = _tool(client, "remote_disconnect", {"session_token": token})
    assert disconnected["isError"] is False
    assert disconnected["structuredContent"]["browser_session_terminated"] is False


def test_mcp_rejects_identity_input_without_dropping_remote_connection(client: TestClient):
    headers = {"X-DSG-API-Key": "dsg_live_test"}
    assert client.post("/remote-browser/enable", headers=headers).status_code == 200
    connected = _tool(
        client,
        "remote_agent_connect",
        {
            "plan_id": "plan-mcp-1",
            "agent_identity": "chatgpt",
            "step_id": "github-actions",
            "remote_endpoint": "https://1.1.1.1/relay",
            "ttl_seconds": 600,
        },
    )
    token = connected["structuredContent"]["session_token"]

    result = _tool(
        client,
        "remote_action",
        {
            "session_token": token,
            "action": {"kind": "browser.type", "parameters": {"password": "never-send-this"}},
        },
    )
    assert result["isError"] is True
    assert result["structuredContent"]["status_code"] == 409

    status = _tool(client, "remote_status")
    assert status["structuredContent"]["agent_connection"] == "connected"
