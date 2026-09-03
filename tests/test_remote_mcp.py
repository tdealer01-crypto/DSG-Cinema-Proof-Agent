from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import (
    browserbase_executor,
    remote_browser,
    remote_mcp,
    remote_pairing,
    remote_relay_security,
)
from api_v1.models import PlanDocument, PlanStep


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "r" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("DSG_BROWSERBASE_EXECUTOR_BASE_URL", "https://1.1.1.1")

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
                parameters={"browser_allowed_origins": "https://github.com"},
            )
        ],
    )
    record = {"plan_id": "plan-mcp-1", "plan_hash": "a" * 64, "status": "APPROVED"}
    monkeypatch.setattr(remote_browser.service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(remote_browser.service, "plan_document", lambda _record: document)

    observed_endpoints: list[str] = []

    async def fake_relay(endpoint: str, payload: dict):
        observed_endpoints.append(endpoint)
        assert endpoint.startswith("https://1.1.1.1/remote-browser/browserbase/action/")
        return 200, {"ok": True, "kind": payload["action"]["kind"]}, "c" * 64

    async def fake_ensure(cinema_session_id: str, *, plan_hash: str, browser_policy: dict):
        assert cinema_session_id.startswith("rbs_")
        assert plan_hash == "a" * 64
        assert browser_policy["allowed_origins"] == ["https://github.com"]
        return {
            "provider": "browserbase",
            "browserbase_session_id": "bb_test",
            "live_view_url": "https://browserbase.example/live/test",
            "connected": True,
            "pages": [],
        }

    async def fake_live_view(*, x_dsg_api_key=None):
        return {
            "ok": True,
            "provider": "browserbase",
            "browserbase_session_id": "bb_test",
            "live_view_url": "https://browserbase.example/live/test",
            "connected": True,
            "pages": [],
        }

    monkeypatch.setattr(remote_browser, "_relay", fake_relay)
    monkeypatch.setattr(browserbase_executor, "ensure_browser_session", fake_ensure)
    monkeypatch.setattr(browserbase_executor, "live_view", fake_live_view)

    app = FastAPI()
    app.include_router(remote_pairing.router)
    app.include_router(remote_mcp.router)
    app.state.observed_endpoints = observed_endpoints
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


def test_mcp_lists_remote_tools_hides_endpoint_and_supports_managed_flow(client: TestClient):
    initialized = _rpc(client, "initialize")
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "dsg-cinema-remote"
    instructions = initialized.json()["result"]["instructions"]
    assert "Never ask the user to copy or enter plan_id, step_id, agent identity" in instructions
    assert "previous approved binding" in instructions

    listed = _rpc(client, "tools/list")
    definitions = {tool["name"]: tool for tool in listed.json()["result"]["tools"]}
    assert set(definitions) == {
        "remote_contract",
        "remote_status",
        "remote_agent_connect",
        "remote_action",
        "remote_disconnect",
        "dashboard_chat_receive",
        "dashboard_chat_reply",
        "dashboard_chat_request_approval",
    }
    connect_schema = definitions["remote_agent_connect"]["inputSchema"]
    assert "remote_endpoint" not in connect_schema["properties"]
    assert set(connect_schema.get("required", [])) == set()
    assert definitions["dashboard_chat_receive"]["annotations"]["readOnlyHint"] is True
    assert definitions["dashboard_chat_reply"]["annotations"]["readOnlyHint"] is False
    assert definitions["dashboard_chat_request_approval"]["annotations"]["readOnlyHint"] is False

    headers = {"X-DSG-API-Key": "dsg_live_test"}
    enabled = client.post("/remote-browser/enable", headers=headers)
    assert enabled.status_code == 200
    assert enabled.json()["agent_connection"] == "waiting"

    status = _tool(client, "remote_status")
    assert status["isError"] is False
    assert status["structuredContent"]["agent_connection"] == "waiting"
    assert status["structuredContent"]["shared_browser"]["provider"] == "browserbase"
    assert status["structuredContent"]["reconnect_available"] is False

    first_without_context = _tool(client, "remote_agent_connect", {})
    assert first_without_context["isError"] is True
    assert first_without_context["structuredContent"]["error"] == "REMOTE_BINDING_CONTEXT_REQUIRED"
    assert "do not ask the user" in first_without_context["structuredContent"]["message"]

    connected = _tool(
        client,
        "remote_agent_connect",
        {
            "plan_id": "plan-mcp-1",
            "agent_identity": "chatgpt",
            "step_id": "github-actions",
            "ttl_seconds": 600,
        },
    )
    assert connected["isError"] is False
    assert connected["structuredContent"]["endpoint_exposed"] is False
    assert connected["structuredContent"]["managed_provider"] == "browserbase"
    assert connected["structuredContent"]["shared_browser"]["browserbase_session_id"] == "bb_test"
    assert connected["structuredContent"]["binding_context_reused"] is False
    token = connected["structuredContent"]["session_token"]

    status_after_connect = _tool(client, "remote_status")
    assert status_after_connect["structuredContent"]["reconnect_available"] is True
    assert status_after_connect["structuredContent"]["previous_binding"] == {
        "plan_id": "plan-mcp-1",
        "step_id": "github-actions",
        "agent_identity": "chatgpt",
    }

    reconnected = _tool(client, "remote_agent_connect", {})
    assert reconnected["isError"] is False
    assert reconnected["structuredContent"]["plan_id"] == "plan-mcp-1"
    assert reconnected["structuredContent"]["step_id"] == "github-actions"
    assert reconnected["structuredContent"]["agent_identity"] == "chatgpt"
    assert reconnected["structuredContent"]["binding_context_reused"] is True

    action = _tool(
        client,
        "remote_action",
        {
            "session_token": token,
            "action": {"kind": "browser.navigate", "parameters": {"url": "https://github.com"}},
        },
    )
    assert action["isError"] is False
    assert action["structuredContent"]["ok"] is True
    assert len(action["structuredContent"]["evidence_hash"]) == 64
    assert len(client.app.state.observed_endpoints) == 1

    disconnected = _tool(client, "remote_disconnect", {"session_token": token})
    assert disconnected["isError"] is False
    assert disconnected["structuredContent"]["browser_session_terminated"] is False


def test_mcp_rejects_client_supplied_remote_endpoint(client: TestClient):
    headers = {"X-DSG-API-Key": "dsg_live_test"}
    assert client.post("/remote-browser/enable", headers=headers).status_code == 200
    result = _tool(
        client,
        "remote_agent_connect",
        {
            "plan_id": "plan-mcp-1",
            "agent_identity": "chatgpt",
            "step_id": "github-actions",
            "remote_endpoint": "https://attacker.example/relay",
            "ttl_seconds": 600,
        },
    )
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "INVALID_ARGUMENTS"


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


def test_required_ci_proves_browserbase_session_is_recorded_and_plan_domain_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "p" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb_server_only_test")
    calls: list[tuple[str, str, dict | None]] = []

    async def fake_bb(method: str, path: str, *, payload=None):
        calls.append((method, path, payload))
        if (method, path) == ("POST", "/sessions"):
            return {"id": "bb_required_ci"}
        if (method, path) == ("GET", "/sessions/bb_required_ci/debug"):
            return {
                "debuggerFullscreenUrl": "https://browserbase.example/live/required-ci",
                "pages": [],
            }
        raise AssertionError((method, path))

    monkeypatch.setattr(browserbase_executor, "_bb_request", fake_bb)
    result = asyncio.run(
        browserbase_executor.ensure_browser_session(
            "rbs_required_ci",
            plan_hash="b" * 64,
            browser_policy={
                "enforced": True,
                "allowed_origins": [
                    "https://dashboard.stripe.com",
                    "https://marketplace.stripe.com",
                ],
            },
        )
    )

    assert result["browserbase_session_id"] == "bb_required_ci"
    assert result["live_view_url"].startswith("https://")
    create_payload = calls[0][2]
    assert create_payload is not None
    settings = create_payload["browserSettings"]
    assert settings["recordSession"] is True
    assert settings["logSession"] is True
    assert settings["allowedDomains"] == [
        "dashboard.stripe.com",
        "marketplace.stripe.com",
    ]


def test_required_ci_proves_signed_executor_binding_and_replay_protection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "q" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    capability = browserbase_executor.allocate_capability(
        plan_id="plan-stripe",
        step_id="publish",
        agent_identity="chatgpt",
        ttl_seconds=600,
    )
    browserbase_executor.finalize_capability(
        capability,
        session_id="rbs_exact",
        plan_hash="f" * 64,
        browser_policy={
            "enforced": True,
            "allowed_origins": ["https://dashboard.stripe.com"],
        },
    )

    async def fake_ensure(cinema_session_id: str, *, plan_hash: str, browser_policy: dict):
        return {
            "provider": "browserbase",
            "browserbase_session_id": "bb_exact",
            "live_view_url": "https://browserbase.example/live/exact",
            "connected": True,
            "pages": [],
        }

    async def fake_perform(cinema_session_id: str, payload: dict):
        return 200, {"ok": True, "kind": payload["action"]["kind"]}

    monkeypatch.setattr(browserbase_executor, "ensure_browser_session", fake_ensure)
    monkeypatch.setattr(browserbase_executor, "_perform_action", fake_perform)

    app = FastAPI()
    app.include_router(remote_relay_security.router)
    executor = TestClient(app)
    envelope = {
        "version": "dsg.remote-action.v1",
        "session_id": "rbs_exact",
        "context": {
            "plan_id": "plan-stripe",
            "plan_hash": "f" * 64,
            "agent_identity": "chatgpt",
            "step_id": "publish",
            "actor": "AGENT_VERIFIER",
            "browser_policy": {
                "enforced": True,
                "allowed_origins": ["https://dashboard.stripe.com"],
                "enforce_current_origin": True,
            },
        },
        "action": {
            "kind": "browser.extract",
            "controller": "agent_verifier",
            "parameters": {},
        },
    }
    signed = remote_relay_security.signed_headers_for_payload(envelope)
    allowed = executor.post(
        f"/remote-browser/browserbase/action/{capability}",
        headers=signed,
        json=envelope,
    )
    assert allowed.status_code == 200, allowed.text

    replay = executor.post(
        f"/remote-browser/browserbase/action/{capability}",
        headers=signed,
        json=envelope,
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["error"] == "REMOTE_RELAY_REPLAY_BLOCKED"

    unsigned = executor.post(
        f"/remote-browser/browserbase/action/{capability}",
        json=envelope,
    )
    assert unsigned.status_code == 401

    rebound = {
        **envelope,
        "context": {**envelope["context"], "plan_hash": "0" * 64},
    }
    rebound_headers = remote_relay_security.signed_headers_for_payload(rebound)
    blocked = executor.post(
        f"/remote-browser/browserbase/action/{capability}",
        headers=rebound_headers,
        json=rebound,
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "MANAGED_BROWSER_BINDING_MISMATCH"
