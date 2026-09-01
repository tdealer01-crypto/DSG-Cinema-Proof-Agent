from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import (
    azure_local_browser,
    azure_managed_executor,
    azure_relay_security,
    browserbase_executor,
    remote_browser,
    remote_mcp,
    remote_pairing,
    remote_relay_security,
    shared_browser,
)
from api_v1.models import PlanDocument, PlanStep


def _authorization(account_id: str = "acct-azure"):
    return SimpleNamespace(account=SimpleNamespace(account_id=account_id))


def _plan() -> PlanDocument:
    return PlanDocument(
        title="Continue in Azure shared browser",
        agent_identity="chatgpt",
        steps=[
            PlanStep(
                step_id="example",
                action="continue_browser_work",
                target="example.com",
                parameters={"browser_allowed_origins": "https://example.com"},
            )
        ],
    )


def test_provider_facade_prefers_azure_without_browserbase_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "azure_local")
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    assert azure_local_browser.configured() is True
    assert shared_browser.configured() is True
    assert shared_browser.provider() == "azure_container_apps"


def test_azure_logical_browser_id_is_stable_and_metadata_is_privacy_minimized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    account_hash = azure_local_browser.account_digest("acct-stable")
    first = azure_local_browser._read_metadata(account_hash)
    azure_local_browser._atomic_json(azure_local_browser._metadata_path(account_hash), first)
    second = azure_local_browser._read_metadata(account_hash)
    assert first["browser_session_id"] == second["browser_session_id"]
    assert first["browser_session_id"].startswith("azure-")
    assert "password" not in second
    assert "form_values" not in second


def test_remote_mcp_uses_azure_managed_endpoint_and_same_account_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "a" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("DSG_BROWSER_PROVIDER", "azure_local")
    monkeypatch.setenv("DSG_PUBLIC_BASE_URL", "https://1.1.1.1")
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)

    authorization = _authorization()
    monkeypatch.setattr(remote_pairing.billing, "authorize_request", lambda *_a, **_k: authorization)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_a, **_k: authorization)
    record = {"plan_id": "plan-azure", "plan_hash": "b" * 64, "status": "APPROVED"}
    monkeypatch.setattr(remote_browser.service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(remote_browser.service, "plan_document", lambda _record: _plan())

    browser_id = "azure-0123456789abcdef01234567"

    async def fake_current(account_id: str, *, create: bool = False):
        assert account_id == "acct-azure"
        return {
            "provider": "azure_container_apps",
            "connected": bool(create),
            "shared_profile": True,
            "context_persistent": True,
            "browser_session_id": browser_id,
            "browserbase_session_id": browser_id,
            "pages": [],
        }

    async def fake_bind(account_id: str, cinema_session_id: str, *, plan_hash: str):
        assert account_id == "acct-azure"
        assert cinema_session_id.startswith("rbs_")
        assert plan_hash == "b" * 64
        browserbase_executor._atomic_json(
            browserbase_executor._session_path(cinema_session_id),
            {
                "cinema_session_id": cinema_session_id,
                "provider": "azure_local",
                "account_hash": azure_local_browser.account_digest(account_id),
                "browser_session_id": browser_id,
                "plan_hash": plan_hash,
            },
        )
        return await fake_current(account_id, create=True)

    async def fake_ensure(cinema_session_id: str, *, plan_hash: str, browser_policy: dict):
        assert cinema_session_id.startswith("rbs_")
        assert plan_hash == "b" * 64
        assert browser_policy["allowed_origins"] == ["https://example.com"]
        return await fake_current("acct-azure", create=True)

    async def fake_live_view(*, x_dsg_api_key=None):
        return {"ok": True, **(await fake_current("acct-azure", create=True))}

    observed: list[str] = []

    async def fake_relay(endpoint: str, payload: dict):
        observed.append(endpoint)
        assert endpoint.startswith("https://1.1.1.1/remote-browser/azure/action/")
        return 200, {"ok": True, "provider": "azure_container_apps"}, "c" * 64

    monkeypatch.setattr(shared_browser, "current_shared_browser", fake_current)
    monkeypatch.setattr(shared_browser, "bind_cinema_session", fake_bind)
    monkeypatch.setattr(azure_managed_executor, "ensure_browser_session", fake_ensure)
    monkeypatch.setattr(azure_managed_executor, "live_view", fake_live_view)
    monkeypatch.setattr(remote_browser, "_relay", fake_relay)

    app = FastAPI()
    app.include_router(remote_pairing.router)
    app.include_router(remote_mcp.router)
    client = TestClient(app)
    headers = {"X-DSG-API-Key": "dsg_live_test"}
    enabled = client.post("/remote-browser/enable", headers=headers)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["shared_browser"]["browser_session_id"] == browser_id

    rpc = client.post(
        "/mcp",
        headers={"Authorization": "Bearer dsg_live_test"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "remote_agent_connect",
                "arguments": {
                    "plan_id": "plan-azure",
                    "agent_identity": "chatgpt",
                    "step_id": "example",
                    "ttl_seconds": 600,
                },
            },
        },
    )
    assert rpc.status_code == 200, rpc.text
    result = rpc.json()["result"]
    assert result["isError"] is False
    created = result["structuredContent"]
    assert created["managed_provider"] == "azure_container_apps"
    assert created["shared_browser"]["browser_session_id"] == browser_id
    token = created["session_token"]

    action = client.post(
        "/mcp",
        headers={"Authorization": "Bearer dsg_live_test"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "remote_action",
                "arguments": {
                    "session_token": token,
                    "action": {"kind": "browser.navigate", "parameters": {"url": "https://example.com"}},
                },
            },
        },
    )
    assert action.status_code == 200
    assert action.json()["result"]["isError"] is False
    assert len(observed) == 1


def test_signed_azure_executor_rejects_unsigned_replay_and_rebound_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "q" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    capability = browserbase_executor.allocate_capability(
        plan_id="plan-azure",
        step_id="example",
        agent_identity="chatgpt",
        ttl_seconds=600,
    )
    browserbase_executor.finalize_capability(
        capability,
        session_id="rbs_azure_exact",
        plan_hash="f" * 64,
        browser_policy={"enforced": True, "allowed_origins": ["https://example.com"]},
    )

    async def fake_ensure(cinema_session_id: str, *, plan_hash: str, browser_policy: dict):
        return {"provider": "azure_container_apps", "connected": True}

    async def fake_perform(cinema_session_id: str, payload: dict):
        return 200, {"ok": True, "kind": payload["action"]["kind"]}

    async def fake_save(cinema_session_id: str):
        return None

    monkeypatch.setattr(azure_managed_executor, "ensure_browser_session", fake_ensure)
    monkeypatch.setattr(azure_managed_executor, "_perform_action", fake_perform)
    monkeypatch.setattr(azure_local_browser, "save_session", fake_save)

    app = FastAPI()
    app.include_router(azure_relay_security.router)
    executor = TestClient(app)
    envelope = {
        "version": "dsg.remote-action.v1",
        "session_id": "rbs_azure_exact",
        "context": {
            "plan_id": "plan-azure",
            "plan_hash": "f" * 64,
            "agent_identity": "chatgpt",
            "step_id": "example",
            "actor": "AGENT_VERIFIER",
            "browser_policy": {
                "enforced": True,
                "allowed_origins": ["https://example.com"],
                "enforce_current_origin": True,
            },
        },
        "action": {"kind": "browser.extract", "controller": "agent_verifier", "parameters": {}},
    }
    signed = remote_relay_security.signed_headers_for_payload(envelope)
    allowed = executor.post(f"/remote-browser/azure/action/{capability}", headers=signed, json=envelope)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["provider"] == "azure_container_apps"

    replay = executor.post(f"/remote-browser/azure/action/{capability}", headers=signed, json=envelope)
    assert replay.status_code == 409
    assert replay.json()["detail"]["error"] == "REMOTE_RELAY_REPLAY_BLOCKED"

    unsigned = executor.post(f"/remote-browser/azure/action/{capability}", json=envelope)
    assert unsigned.status_code == 401

    rebound = {**envelope, "context": {**envelope["context"], "plan_hash": "0" * 64}}
    rebound_headers = remote_relay_security.signed_headers_for_payload(rebound)
    blocked = executor.post(
        f"/remote-browser/azure/action/{capability}",
        headers=rebound_headers,
        json=rebound,
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "MANAGED_BROWSER_BINDING_MISMATCH"
