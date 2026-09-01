from __future__ import annotations

from pathlib import Path

import pytest

from api_v1 import browserbase_executor, browserbase_shared_profile


@pytest.fixture()
def shared_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSG_REMOTE_ACTION_STORE", str(tmp_path / "remote-store"))
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb_test_server_only")
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", "project-test")
    browserbase_executor._CONNECTIONS.clear()
    browserbase_executor._MUTATION_LOCKS.clear()
    return tmp_path


@pytest.mark.asyncio
async def test_account_browser_creates_persistent_context_and_reuses_same_live_session(
    shared_env, monkeypatch: pytest.MonkeyPatch
):
    calls: list[tuple[str, str, dict | None]] = []

    async def fake_bb(method: str, path: str, *, payload=None):
        calls.append((method, path, payload))
        if (method, path) == ("POST", "/contexts"):
            return {"id": "ctx_account_1"}
        if (method, path) == ("POST", "/sessions"):
            return {"id": "bb_shared_1"}
        if (method, path) == ("GET", "/sessions/bb_shared_1/debug"):
            return {
                "debuggerFullscreenUrl": "https://browserbase.example/live/shared-1",
                "pages": [
                    {
                        "id": "page-1",
                        "url": "https://github.com/tdealer01-crypto/repo?token=must-not-persist#frag",
                        "title": "Repository",
                    }
                ],
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(browserbase_executor, "_bb_request", fake_bb)

    first = await browserbase_shared_profile.ensure_shared_browser("acct-one")
    second = await browserbase_shared_profile.ensure_shared_browser("acct-one")

    assert first["browserbase_session_id"] == second["browserbase_session_id"] == "bb_shared_1"
    assert first["context_persistent"] is True
    assert first["pages"][0]["url"] == "https://github.com/tdealer01-crypto/repo"

    context_calls = [call for call in calls if call[:2] == ("POST", "/contexts")]
    session_calls = [call for call in calls if call[:2] == ("POST", "/sessions")]
    assert len(context_calls) == 1
    assert len(session_calls) == 1
    payload = session_calls[0][2]
    assert payload is not None
    assert payload["keepAlive"] is True
    assert payload["browserSettings"]["context"] == {"id": "ctx_account_1", "persist": True}
    assert "allowedDomains" not in payload["browserSettings"]
    assert payload["userMetadata"]["dsg_account_hash"] != "acct-one"


@pytest.mark.asyncio
async def test_two_plan_authority_sessions_bind_to_same_user_browser(
    shared_env, monkeypatch: pytest.MonkeyPatch
):
    async def fake_bb(method: str, path: str, *, payload=None):
        if (method, path) == ("POST", "/contexts"):
            return {"id": "ctx_same_user"}
        if (method, path) == ("POST", "/sessions"):
            return {"id": "bb_same_user"}
        if (method, path) == ("GET", "/sessions/bb_same_user/debug"):
            return {
                "debuggerFullscreenUrl": "https://browserbase.example/live/same-user",
                "pages": [],
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(browserbase_executor, "_bb_request", fake_bb)

    first = await browserbase_shared_profile.bind_cinema_session(
        "acct-shared",
        "rbs_plan_1",
        plan_hash="1" * 64,
    )
    second = await browserbase_shared_profile.bind_cinema_session(
        "acct-shared",
        "rbs_plan_2",
        plan_hash="2" * 64,
    )

    assert first["browserbase_session_id"] == second["browserbase_session_id"] == "bb_same_user"
    binding_one = browserbase_executor._read_binding("rbs_plan_1")
    binding_two = browserbase_executor._read_binding("rbs_plan_2")
    assert binding_one is not None and binding_two is not None
    assert binding_one["browserbase_session_id"] == binding_two["browserbase_session_id"] == "bb_same_user"
    assert binding_one["plan_hash"] == "1" * 64
    assert binding_two["plan_hash"] == "2" * 64
    assert binding_one["context_id"] == binding_two["context_id"] == "ctx_same_user"


@pytest.mark.asyncio
async def test_dead_provider_session_restarts_from_same_persistent_context(
    shared_env, monkeypatch: pytest.MonkeyPatch
):
    created_sessions = 0
    dead = False

    async def fake_bb(method: str, path: str, *, payload=None):
        nonlocal created_sessions, dead
        if (method, path) == ("POST", "/contexts"):
            return {"id": "ctx_resume"}
        if (method, path) == ("POST", "/sessions"):
            created_sessions += 1
            return {"id": f"bb_resume_{created_sessions}"}
        if method == "GET" and path.endswith("/debug"):
            if dead and path == "/sessions/bb_resume_1/debug":
                from fastapi import HTTPException

                raise HTTPException(status_code=502, detail="session ended")
            session_id = path.split("/")[2]
            return {
                "debuggerFullscreenUrl": f"https://browserbase.example/live/{session_id}",
                "pages": [],
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(browserbase_executor, "_bb_request", fake_bb)

    first = await browserbase_shared_profile.ensure_shared_browser("acct-resume")
    assert first["browserbase_session_id"] == "bb_resume_1"

    dead = True
    second = await browserbase_shared_profile.ensure_shared_browser("acct-resume")
    assert second["browserbase_session_id"] == "bb_resume_2"
    assert created_sessions == 2

    profile = browserbase_shared_profile._read_profile("acct-resume")
    assert profile["context_id"] == "ctx_resume"
