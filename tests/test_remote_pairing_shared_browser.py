from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_v1 import browserbase_executor, remote_browser, remote_pairing
from api_v1.models import PlanDocument, PlanStep


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DSG_REMOTE_ACTION_KEY", "s" * 64)
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb_test_server_only")
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", "project-test")

    authorization = SimpleNamespace(account=SimpleNamespace(account_id="acct-shared-browser"))
    monkeypatch.setattr(remote_pairing.billing, "authorize_request", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(remote_browser.billing, "authorize_request", lambda *_args, **_kwargs: authorization)

    document = PlanDocument(
        title="Continue in the user's browser",
        agent_identity="agent-a",
        steps=[
            PlanStep(
                step_id="github",
                action="continue_browser_work",
                target="github.com",
                parameters={"browser_allowed_origins": "https://github.com"},
            )
        ],
    )
    record = {"plan_id": "plan-shared", "plan_hash": "a" * 64, "status": "APPROVED"}
    monkeypatch.setattr(remote_browser.service, "get_plan_record", lambda _plan_id: record)
    monkeypatch.setattr(remote_browser.service, "plan_document", lambda _record: document)

    calls: list[tuple[str, str, dict | None]] = []

    async def fake_bb(method: str, path: str, *, payload=None):
        calls.append((method, path, payload))
        if (method, path) == ("POST", "/contexts"):
            assert payload == {"projectId": "project-test"}
            return {"id": "ctx_user"}
        if (method, path) == ("POST", "/sessions"):
            assert payload is not None and payload["projectId"] == "project-test"
            return {"id": "bb_user_browser"}
        if (method, path) == ("GET", "/sessions/bb_user_browser/debug"):
            return {
                "debuggerFullscreenUrl": "https://browserbase.example/live/user",
                "pages": [{"id": "page-1", "url": "https://github.com/", "title": "GitHub"}],
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(browserbase_executor, "_bb_request", fake_bb)

    app = FastAPI()
    app.include_router(remote_pairing.router)
    app.state.bb_calls = calls
    return TestClient(app)


def test_remote_on_agent_join_off_on_keeps_same_user_browser(client: TestClient):
    headers = {"X-DSG-API-Key": "dsg_live_test"}

    enabled = client.post("/remote-browser/enable", headers=headers)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["remote_enabled"] is True
    assert enabled.json()["shared_browser"]["browserbase_session_id"] == "bb_user_browser"
    assert enabled.json()["shared_browser"]["context_persistent"] is True

    connected = client.post(
        "/remote-browser/agent-connect",
        headers=headers,
        json={
            "plan_id": "plan-shared",
            "agent_identity": "agent-a",
            "step_id": "github",
            "remote_endpoint": "https://1.1.1.1/remote-browser/browserbase/action/capability-test",
            "ttl_seconds": 600,
        },
    )
    assert connected.status_code == 201, connected.text
    body = connected.json()
    assert body["browser_continuity"] == "ACCOUNT_SCOPED_PERSISTENT_CONTEXT"
    assert body["shared_browser"]["browserbase_session_id"] == "bb_user_browser"

    binding = browserbase_executor._read_binding(body["session_id"])
    assert binding is not None
    assert binding["browserbase_session_id"] == "bb_user_browser"
    assert binding["context_id"] == "ctx_user"

    disabled = client.post("/remote-browser/disable", headers=headers)
    assert disabled.status_code == 200
    assert disabled.json()["remote_enabled"] is False
    assert disabled.json()["user_browser_session"] == "unchanged"
    assert disabled.json()["shared_browser"]["browserbase_session_id"] == "bb_user_browser"

    reenabled = client.post("/remote-browser/enable", headers=headers)
    assert reenabled.status_code == 200
    assert reenabled.json()["shared_browser"]["browserbase_session_id"] == "bb_user_browser"

    context_creates = [call for call in client.app.state.bb_calls if call[:2] == ("POST", "/contexts")]
    session_creates = [call for call in client.app.state.bb_calls if call[:2] == ("POST", "/sessions")]
    assert len(context_creates) == 1
    assert len(session_creates) == 1
