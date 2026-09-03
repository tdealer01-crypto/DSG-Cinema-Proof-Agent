from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import agent_pairing, dashboard_chat, remote_pairing, service


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(cinema_main.app)


@pytest.fixture(autouse=True)
def isolated_dashboard(tmp_path, monkeypatch):
    root = tmp_path / "dashboard"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "e" * 64)
    monkeypatch.setattr(dashboard_chat, "_root", lambda: root)
    monkeypatch.setattr(
        agent_pairing,
        "_authenticated_account",
        lambda value: ((value or "test-key"), SimpleNamespace(account_id="acct_unified")),
    )
    yield


def _mcp(name: str, arguments: dict | None = None):
    return client.post(
        "/mcp",
        headers={"X-DSG-API-Key": "test-key"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )


def test_user_has_one_dashboard_for_chat_browser_approval_and_five_monitors():
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text

    assert "AI AGENT CHAT" in html
    assert "SHARED BROWSER" in html
    assert "User + Agent" in html
    assert "One execution · five views" in html
    assert 'id="connectAgentTop"' in html
    assert 'id="chatInput"' in html
    assert 'id="chatSend"' in html
    assert 'id="browserFrame"' in html

    for label in ["01 · ACTION", "02 · PLAN", "03 · PERMISSION", "04 · EVIDENCE", "05 · AUDIT"]:
        assert label in html

    # Normal customer flow stays on /dashboard. The legacy helper/assets remain
    # rollback compatibility only; the canonical shell does not navigate away.
    assert "location.href='/remote-browser/connect-agent" not in html
    assert 'onclick="location.href=' not in html
    assert "Advanced / manual setup" in html


def test_dashboard_javascript_runs_one_page_pairing_chat_and_monitor_flow():
    response = client.get("/app.js")
    assert response.status_code == 200
    script = response.text

    required = [
        'request("/remote-browser/enable"',
        'request("/remote-browser/agent-pair"',
        'request("/dashboard/api/chat/messages',
        'request("/dashboard/api/chat/approval"',
        'request("/dashboard/api/monitor"',
        '$("connectAgentTop").onclick',
        '$("chatSend").onclick',
    ]
    for value in required:
        assert value in script

    # The browser must not call MCP with its own pairing token because that
    # would fabricate an agent contact and auto-claim a remote session.
    assert 'Authorization": "Bearer ' not in script
    assert "method:'tools/call'" not in script
    assert "location.href='/remote-browser/connect-agent" not in script
    assert "localStorage" not in script
    assert "sessionStorage" in script


def test_chat_round_trip_uses_real_paired_mcp_tools():
    posted = client.post(
        "/dashboard/api/chat/messages",
        headers={"X-DSG-API-Key": "test-key"},
        json={"text": "Open the approved site and inspect the current page"},
    )
    assert posted.status_code == 201
    assert posted.json()["delivery"] == "queued_for_paired_agent"

    received = _mcp("dashboard_chat_receive", {"after_seq": 0, "limit": 10})
    assert received.status_code == 200
    tool = received.json()["result"]
    assert tool["isError"] is False
    messages = tool["structuredContent"]["messages"]
    assert messages[-1]["role"] == "user"
    assert "inspect the current page" in messages[-1]["text"]

    replied = _mcp("dashboard_chat_reply", {"text": "I can see your message. I will use the approved browser session."})
    assert replied.status_code == 200
    assert replied.json()["result"]["isError"] is False

    history = client.get(
        "/dashboard/api/chat/messages?after_seq=0&limit=100",
        headers={"X-DSG-API-Key": "test-key"},
    )
    assert history.status_code == 200
    roles = [item["role"] for item in history.json()["messages"]]
    assert roles == ["user", "agent"]


def test_inline_approval_uses_exact_stored_plan_hash(monkeypatch):
    plan_hash = "a" * 64
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        service,
        "get_plan_record",
        lambda plan_id: {"plan_id": plan_id, "plan_hash": plan_hash, "status": service.STATUS_DRAFT},
    )
    monkeypatch.setattr(
        service,
        "approve_plan",
        lambda plan_id, request: calls.append((plan_id, request.plan_hash)) or {
            "plan_id": plan_id,
            "plan_hash": request.plan_hash,
            "status": service.STATUS_APPROVED,
        },
    )
    monkeypatch.setattr(
        service,
        "read_plan",
        lambda plan_id: {"plan_id": plan_id, "plan_hash": plan_hash, "status": service.STATUS_APPROVED},
    )
    monkeypatch.setattr(agent_pairing, "_remember_approved_binding", lambda key, plan_id: None)

    requested = _mcp(
        "dashboard_chat_request_approval",
        {"plan_id": "plan_e2e", "plan_hash": plan_hash, "summary": "Navigate the shared browser to the approved target"},
    )
    assert requested.status_code == 200
    payload = requested.json()["result"]["structuredContent"]
    assert payload["approval_required"] is True
    message_id = payload["message"]["message_id"]

    approved = client.post(
        "/dashboard/api/chat/approval",
        headers={"X-DSG-API-Key": "test-key"},
        json={"message_id": message_id, "decision": "approve"},
    )
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approved"
    assert calls == [("plan_e2e", plan_hash)]


def test_five_panel_monitor_is_truthful_when_remote_waits_for_real_agent(monkeypatch):
    monkeypatch.setattr(
        remote_pairing,
        "_read_state",
        lambda account_id: {
            "account_id": account_id,
            "enabled": True,
            "session_ids": [],
            "last_plan_id": None,
            "updated_at": None,
        },
    )
    monkeypatch.setattr(remote_pairing, "_active_sessions", lambda state: [])

    response = client.get("/dashboard/api/monitor", headers={"X-DSG-API-Key": "test-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["agent_connection"] == "waiting"
    assert list(body["panels"]) == [
        "action",
        "plan_alignment",
        "permission",
        "evidence",
        "execution_audit",
    ]
    assert body["panels"]["action"]["status"] == "WAITING"
    assert body["panels"]["plan_alignment"]["status"] == "PENDING"
    assert body["panels"]["permission"]["status"] == "WAITING_AGENT"
    assert body["panels"]["evidence"]["status"] == "PENDING"
    assert body["panels"]["execution_audit"]["status"] == "WAITING"
