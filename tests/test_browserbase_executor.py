from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import browserbase_executor


@pytest.fixture()
def browserbase_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "b" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb_test_server_only")
    browserbase_executor._CONNECTIONS.clear()
    browserbase_executor._MUTATION_LOCKS.clear()
    return tmp_path


@pytest.mark.asyncio
async def test_provisions_recorded_allowed_domain_session_and_returns_live_view(
    browserbase_env, monkeypatch: pytest.MonkeyPatch
):
    calls: list[tuple[str, str, dict | None]] = []

    async def fake_bb(method: str, path: str, *, payload=None):
        calls.append((method, path, payload))
        if method == "POST" and path == "/sessions":
            return {"id": "bb_session_1", "connectUrl": "wss://connect.example/test"}
        if method == "GET" and path == "/sessions/bb_session_1/debug":
            return {
                "debuggerFullscreenUrl": "https://www.browserbase.com/sessions/live/test",
                "pages": [{"id": "page-1"}],
            }
        raise AssertionError((method, path))

    monkeypatch.setattr(browserbase_executor, "_bb_request", fake_bb)

    result = await browserbase_executor.ensure_browser_session(
        "rbs_test_1",
        plan_hash="a" * 64,
        browser_policy={
            "enforced": True,
            "allowed_origins": [
                "https://dashboard.stripe.com",
                "https://marketplace.stripe.com",
            ],
        },
    )

    assert result["browserbase_session_id"] == "bb_session_1"
    assert result["live_view_url"].startswith("https://")
    create = calls[0]
    assert create[:2] == ("POST", "/sessions")
    settings = create[2]["browserSettings"]
    assert settings["recordSession"] is True
    assert settings["logSession"] is True
    assert settings["allowedDomains"] == [
        "dashboard.stripe.com",
        "marketplace.stripe.com",
    ]


def test_capability_is_bound_to_exact_cinema_session_and_context(
    browserbase_env, monkeypatch: pytest.MonkeyPatch
):
    token = browserbase_executor.allocate_capability(
        plan_id="plan-stripe",
        step_id="publish",
        agent_identity="chatgpt",
        ttl_seconds=600,
    )
    browserbase_executor.finalize_capability(
        token,
        session_id="rbs_exact",
        plan_hash="f" * 64,
        browser_policy={
            "enforced": True,
            "allowed_origins": ["https://dashboard.stripe.com"],
        },
    )

    async def fake_ensure(cinema_session_id: str, *, plan_hash: str, browser_policy: dict):
        assert cinema_session_id == "rbs_exact"
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
    app.include_router(browserbase_executor.router)
    client = TestClient(app)

    envelope = {
        "version": "dsg.remote-action.v1",
        "session_id": "rbs_exact",
        "context": {
            "plan_id": "plan-stripe",
            "plan_hash": "f" * 64,
            "agent_identity": "chatgpt",
            "step_id": "publish",
            "actor": "AGENT_EXECUTOR",
            "browser_policy": {
                "enforced": True,
                "allowed_origins": ["https://dashboard.stripe.com"],
                "enforce_current_origin": True,
            },
        },
        "action": {
            "kind": "browser.navigate",
            "controller": "agent_executor",
            "parameters": {"url": "https://dashboard.stripe.com"},
        },
    }

    ok = client.post(f"/remote-browser/browserbase/action/{token}", json=envelope)
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True

    wrong = {**envelope, "context": {**envelope["context"], "plan_hash": "0" * 64}}
    blocked = client.post(f"/remote-browser/browserbase/action/{token}", json=wrong)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "MANAGED_BROWSER_BINDING_MISMATCH"


def test_revoked_or_unknown_capability_cannot_drive_browser(browserbase_env):
    token = browserbase_executor.allocate_capability(
        plan_id="plan",
        step_id="step",
        agent_identity="agent",
        ttl_seconds=600,
    )
    browserbase_executor.finalize_capability(
        token,
        session_id="rbs",
        plan_hash="1" * 64,
        browser_policy={},
    )
    browserbase_executor.revoke_capability(token)

    app = FastAPI()
    app.include_router(browserbase_executor.router)
    client = TestClient(app)

    payload = {
        "version": "dsg.remote-action.v1",
        "session_id": "rbs",
        "context": {
            "plan_id": "plan",
            "plan_hash": "1" * 64,
            "agent_identity": "agent",
            "step_id": "step",
        },
        "action": {"kind": "browser.extract", "controller": "agent_verifier", "parameters": {}},
    }
    response = client.post(f"/remote-browser/browserbase/action/{token}", json=payload)
    assert response.status_code == 401
