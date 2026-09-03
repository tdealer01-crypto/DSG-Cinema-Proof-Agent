from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import agent_pairing, dashboard_chat, remote_mcp, remote_pairing, service, store, universal_runtime


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "u" * 64)
    monkeypatch.setenv("DSG_UNIVERSAL_LOCAL_EXECUTOR", "1")
    store.reset_store(store.RecordStore(str(tmp_path / "v1-records.json")))

    authorization = SimpleNamespace(account=SimpleNamespace(account_id="acct-universal"))
    monkeypatch.setattr(agent_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(remote_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)

    app = FastAPI()
    app.include_router(remote_mcp.router)
    app.include_router(dashboard_chat.router)
    dashboard_chat.install_mcp_tools()
    universal_runtime.install(app)
    return TestClient(app)


def _rpc(client: TestClient, method: str, params: dict | None = None, message_id: int = 1):
    return client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer dsg_live_test",
            "X-DSG-Agent-Name": "sandbox-agent",
        },
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


def test_chat_plan_user_approval_then_universal_execution_e2e(client: TestClient):
    listed = _rpc(client, "tools/list", message_id=1).json()["result"]["tools"]
    names = {tool["name"] for tool in listed}
    assert {"dashboard_chat_create_plan", "universal_runtime_status", "universal_execute_step", "universal_evidence_verify"} <= names
    assert "plan_approve" not in names

    proposed = _tool(
        client,
        "dashboard_chat_create_plan",
        {
            "plan": {
                "title": "Universal governed sandbox E2E",
                "agent_identity": "sandbox-agent",
                "channel": "mcp",
                "steps": [
                    {
                        "step_id": "write",
                        "action": "fs.write",
                        "target": "result.txt",
                        "parameters": {"path": "result.txt", "content": "DSG UNIVERSAL E2E"},
                    },
                    {
                        "step_id": "python",
                        "action": "python.run",
                        "target": "python",
                        "parameters": {"code": "print(6*7)"},
                    },
                    {
                        "step_id": "shell",
                        "action": "shell.exec",
                        "target": "cat result.txt",
                        "parameters": {"command": "cat result.txt"},
                    },
                ],
            },
            "summary": "Write a governed file, execute Python, then verify the file through a sandbox command",
        },
        message_id=2,
    )
    assert proposed["isError"] is False
    payload = proposed["structuredContent"]
    plan_id = payload["plan"]["plan_id"]
    message_id = payload["message"]["message_id"]
    plan_hash = payload["plan"]["plan_hash"]

    blocked = _tool(client, "universal_execute_step", {"plan_id": plan_id, "step_id": "write"}, message_id=3)
    assert blocked["isError"] is True
    assert blocked["structuredContent"]["error"] == "PLAN_NOT_APPROVED"

    approved = client.post(
        "/dashboard/api/chat/approval",
        headers={"X-DSG-API-Key": "dsg_live_test"},
        json={"message_id": message_id, "decision": "approve"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval"]["status"] == "approved"
    assert approved.json()["approval"]["plan_hash"] == plan_hash
    assert service.read_plan(plan_id)["plan_hash_verified"] is True

    write = _tool(client, "universal_execute_step", {"plan_id": plan_id, "step_id": "write"}, message_id=4)
    python = _tool(client, "universal_execute_step", {"plan_id": plan_id, "step_id": "python"}, message_id=5)
    shell = _tool(client, "universal_execute_step", {"plan_id": plan_id, "step_id": "shell"}, message_id=6)

    assert write["isError"] is False
    assert write["structuredContent"]["output"]["sha256"]
    assert python["structuredContent"]["output"]["returncode"] == 0
    assert python["structuredContent"]["output"]["stdout"].strip() == "42"
    assert shell["structuredContent"]["output"]["returncode"] == 0
    assert shell["structuredContent"]["output"]["stdout"].strip() == "DSG UNIVERSAL E2E"

    workspace = universal_runtime._workspace("acct-universal")
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "DSG UNIVERSAL E2E"

    verified = _tool(client, "universal_evidence_verify", message_id=7)
    assert verified["isError"] is False
    assert verified["structuredContent"]["ok"] is True
    assert verified["structuredContent"]["records"] == 3
    assert len(verified["structuredContent"]["head"]) == 64

    latest = universal_runtime.latest_event("acct-universal")
    assert latest is not None
    assert latest["step_id"] == "shell"
    assert latest["state"] == "COMPLETED"
    assert latest["actor"] == "AGENT"
    assert len(latest["evidence_hash"]) == 64


def test_universal_executor_is_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.delenv("DSG_UNIVERSAL_LOCAL_EXECUTOR", raising=False)
    workspace = universal_runtime._workspace("acct-disabled")
    with pytest.raises(Exception) as exc:
        universal_runtime._run_process(["python", "-c", "print('no')"], workspace)
    assert getattr(exc.value, "status_code", None) == 503
    assert exc.value.detail["error"] == "UNIVERSAL_SANDBOX_EXECUTOR_REQUIRED"
