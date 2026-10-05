from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import browserbase_executor, remote_browser, remote_mcp, remote_pairing
from api_v1.canonical import canonical_hash


def _encode_context(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _context(*, provider_action: str, route_id: str, plan_id: str, agent_id: str, arguments: dict, approval: bool) -> dict:
    value = {
        "schema_version": 1,
        "authority": "dsg_spacetime",
        "provider_action": provider_action,
        "plan_id": plan_id,
        "plan_hash": "a" * 64,
        "route_id": route_id,
        "agent_id": agent_id,
        "principal": "chatgpt:test",
        "decision_hash": "b" * 64,
        "decision_verdict": "ALLOW",
        "arguments_sha256": canonical_hash(arguments),
    }
    if approval:
        value["approval_token_sha256"] = "c" * 64
    return value


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "r" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("DSG_BROWSERBASE_EXECUTOR_BASE_URL", "https://1.1.1.1")

    authorization = SimpleNamespace(account=SimpleNamespace(account_id="acct-spacetime"))
    monkeypatch.setattr(remote_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: authorization)

    async def fake_relay(endpoint: str, payload: dict):
        return 200, {"ok": True, "kind": payload["action"]["kind"]}, "d" * 64

    async def fake_ensure(cinema_session_id: str, *, plan_hash: str, browser_policy: dict):
        return {
            "provider": "browserbase",
            "browserbase_session_id": "bb_spacetime",
            "live_view_url": "https://browserbase.example/live/spacetime",
            "connected": True,
            "pages": [],
        }

    async def fake_live_view(*, x_dsg_api_key=None):
        return {
            "ok": True,
            "provider": "browserbase",
            "browserbase_session_id": "bb_spacetime",
            "live_view_url": "https://browserbase.example/live/spacetime",
            "connected": True,
            "pages": [],
        }

    monkeypatch.setattr(remote_browser, "_relay", fake_relay)
    monkeypatch.setattr(browserbase_executor, "ensure_browser_session", fake_ensure)
    monkeypatch.setattr(browserbase_executor, "live_view", fake_live_view)

    app = FastAPI()
    app.include_router(remote_pairing.router)
    app.include_router(remote_mcp.router)
    return TestClient(app)


def _rpc(client: TestClient, name: str, arguments: dict, context: dict):
    return client.post(
        "/mcp",
        headers={
            "X-DSG-API-Key": "dsg_live_test",
            "X-DSG-Agent-Name": "dsg-spacetime",
            "X-DSG-Spacetime-Context": _encode_context(context),
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def test_spacetime_connect_does_not_require_cinema_plan_store(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        remote_browser.service,
        "get_plan_record",
        lambda _plan_id: (_ for _ in ()).throw(AssertionError("Cinema plan store must not authorize Spacetime execution")),
    )
    assert client.post("/remote-browser/enable", headers={"X-DSG-API-Key": "dsg_live_test"}).status_code == 200

    arguments = {
        "plan_id": "spacetime-plan-connect",
        "agent_identity": "agent-spacetime",
        "step_id": "connect",
        "ttl_seconds": 600,
    }
    context = _context(
        provider_action="browser.remote.connect",
        route_id="route.cinema-remote.connect",
        plan_id=arguments["plan_id"],
        agent_id=arguments["agent_identity"],
        arguments=arguments,
        approval=True,
    )
    response = _rpc(client, "remote_agent_connect", arguments, context)
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False, result
    body = result["structuredContent"]
    assert body["authority_source"] == "dsg_spacetime"
    assert body["plan_hash"] == "a" * 64
    assert body["verified_connected"] is not False if "verified_connected" in body else True


def test_spacetime_context_rejects_changed_arguments(client: TestClient) -> None:
    assert client.post("/remote-browser/enable", headers={"X-DSG-API-Key": "dsg_live_test"}).status_code == 200
    approved = {
        "plan_id": "spacetime-plan-connect",
        "agent_identity": "agent-spacetime",
        "step_id": "connect",
        "ttl_seconds": 600,
    }
    context = _context(
        provider_action="browser.remote.connect",
        route_id="route.cinema-remote.connect",
        plan_id=approved["plan_id"],
        agent_id=approved["agent_identity"],
        arguments=approved,
        approval=True,
    )
    changed = dict(approved)
    changed["ttl_seconds"] = 601
    response = _rpc(client, "remote_agent_connect", changed, context)
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "SPACETIME_ARGUMENTS_SCOPE_MISMATCH"


def test_spacetime_session_token_rejects_action_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "r" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: None)

    async def fake_relay(endpoint: str, payload: dict):
        return 200, {"ok": True}, "e" * 64

    monkeypatch.setattr(remote_browser, "_relay", fake_relay)

    request = remote_browser.RemoteSessionCreate(
        plan_id="spacetime-plan-run",
        agent_identity="agent-spacetime",
        step_id="navigate",
        remote_endpoint="https://1.1.1.1/relay",
        ttl_seconds=600,
    )
    action = remote_browser.RemoteAction(
        kind="browser.navigate",
        controller="agent_executor",
        parameters={"url": "https://example.com"},
    )
    context = {
        "schema_version": 1,
        "authority": "dsg_spacetime",
        "provider_action": "browser.remote.run",
        "plan_id": request.plan_id,
        "plan_hash": "a" * 64,
        "route_id": "route.cinema-remote.execute",
        "agent_id": request.agent_identity,
        "decision_hash": "b" * 64,
        "decision_verdict": "ALLOW",
        "arguments_sha256": "d" * 64,
        "approval_token_sha256": "c" * 64,
    }

    import asyncio

    created = asyncio.run(
        remote_browser.create_spacetime_session(
            request,
            spacetime_context=context,
            bound_action=action,
            x_dsg_api_key="dsg_live_test",
        )
    )

    app = FastAPI()
    app.include_router(remote_browser.router)
    local_client = TestClient(app)
    tampered = local_client.post(
        "/api/v1/remote-browser/actions",
        json={
            "session_token": created["session_token"],
            "action": {
                "kind": "browser.navigate",
                "controller": "agent_executor",
                "parameters": {"url": "https://openai.com"},
            },
        },
    )
    assert tampered.status_code == 403
    assert tampered.json()["detail"]["error"] == "SPACETIME_ACTION_SCOPE_MISMATCH"
