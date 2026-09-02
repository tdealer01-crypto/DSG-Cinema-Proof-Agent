from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import (
    agent_pairing,
    browserbase_executor,
    remote_browser,
    remote_mcp,
    remote_pairing,
    service,
)
from api_v1.models import PlanDocument, PlanStep


def test_paired_agent_auto_claims_approved_waiting_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "a" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("DSG_PUBLIC_BASE_URL", "https://cinema.example")
    monkeypatch.setenv("DSG_BROWSERBASE_EXECUTOR_BASE_URL", "https://1.1.1.1")
    monkeypatch.setattr(remote_mcp.azure_local_browser, "configured", lambda: False)
    monkeypatch.setattr(remote_pairing.shared_browser, "configured", lambda: False)

    authorization = SimpleNamespace(account=SimpleNamespace(account_id="acct-auto-claim"))
    monkeypatch.setattr(agent_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(remote_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: authorization)

    document = PlanDocument(
        title="Automatic remote claim",
        agent_identity="chatgpt",
        steps=[
            PlanStep(
                step_id="approved-first-step",
                action="continue_browser_work",
                target="github.com",
                parameters={"browser_allowed_origins": "https://github.com"},
            ),
            PlanStep(
                step_id="approved-second-step",
                action="verify_browser_work",
                target="github.com",
                parameters={"browser_allowed_origins": "https://github.com"},
            ),
        ],
    )
    record = {
        "plan_id": "plan-auto-claim",
        "plan_hash": "b" * 64,
        "status": service.STATUS_APPROVED,
        "document": document.model_dump(mode="json"),
    }
    monkeypatch.setattr(service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(service, "plan_document", lambda _record: document)

    async def fake_shared(_account_id: str, *, create: bool):
        return {
            "ok": True,
            "provider": "browserbase",
            "connected": create,
            "shared_profile": True,
            "context_persistent": True,
            "pages": [],
        }

    async def fake_ensure(cinema_session_id: str, *, plan_hash: str, browser_policy: dict):
        assert cinema_session_id.startswith("rbs_")
        assert plan_hash == "b" * 64
        assert browser_policy["allowed_origins"] == ["https://github.com"]
        return {
            "ok": True,
            "provider": "browserbase",
            "browserbase_session_id": "bb_auto_claim",
            "live_view_url": "https://browserbase.example/live/auto-claim",
            "connected": True,
            "pages": [],
        }

    async def fake_live_view(*, x_dsg_api_key=None):
        return {
            "ok": True,
            "provider": "browserbase",
            "browserbase_session_id": "bb_auto_claim",
            "live_view_url": "https://browserbase.example/live/auto-claim",
            "connected": True,
            "pages": [],
        }

    monkeypatch.setattr(remote_pairing, "_shared_browser", fake_shared)
    monkeypatch.setattr(browserbase_executor, "ensure_browser_session", fake_ensure)
    monkeypatch.setattr(browserbase_executor, "live_view", fake_live_view)

    with agent_pairing._lock:
        agent_pairing._pairings.clear()

    app = FastAPI()
    app.include_router(remote_pairing.router)
    app.include_router(agent_pairing.router)
    app.include_router(remote_mcp.router)

    @app.post("/api/v1/plans/{plan_id}/approve")
    async def fake_approve(plan_id: str):
        assert plan_id == "plan-auto-claim"
        return {"plan_id": plan_id, "status": "APPROVED"}

    app.add_middleware(agent_pairing.AgentPairingMiddleware)
    client = TestClient(app)
    headers = {"X-DSG-API-Key": "dsg_test_key"}

    enabled = client.post("/remote-browser/enable", headers=headers)
    assert enabled.status_code == 200
    assert enabled.json()["agent_connection"] == "waiting"

    paired = client.post(
        "/remote-browser/agent-pair",
        headers=headers,
        json={"agent_name": "chat-agent", "ttl_seconds": 600},
    )
    assert paired.status_code == 201
    token = paired.json()["pairing_token"]
    assert paired.json()["agent_name"] == "chat-agent"

    approved = client.post("/api/v1/plans/plan-auto-claim/approve", headers=headers)
    assert approved.status_code == 200

    aligned_pairing = agent_pairing.resolve_pairing(token)
    assert aligned_pairing is not None
    assert aligned_pairing.agent_name == "chatgpt"

    state = remote_pairing._read_state("acct-auto-claim")
    assert state["last_plan_id"] == "plan-auto-claim"
    assert state["last_step_id"] == "approved-first-step"
    assert state["last_agent_identity"] == "chatgpt"
    assert state["approved_step_queue"] == ["approved-first-step", "approved-second-step"]

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "remote_status", "arguments": {}},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False
    status = result["structuredContent"]
    assert status["remote_enabled"] is True
    assert status["agent_connection"] == "connected"
    assert status["active_sessions"] == 1
    assert status["paired_agent_identity"] == "chatgpt"
    assert status["shared_browser"]["connected"] is True

    final_state = remote_pairing._read_state("acct-auto-claim")
    assert len(final_state["session_ids"]) == 1
    assert final_state["last_plan_id"] == "plan-auto-claim"
    assert final_state["last_step_id"] == "approved-first-step"
    assert final_state["last_agent_identity"] == "chatgpt"
    assert "last_auto_connect_error" not in final_state
