"""Source-level concurrency regression for Cinema's existing input paths.

These tests never create a browser, login, provider permit, or production action.
"""
from __future__ import annotations

import asyncio
import hashlib

import pytest
from fastapi import HTTPException

from api_v1 import shared_input_broker as broker


H = hashlib.sha256(b"owner").hexdigest()
H2 = hashlib.sha256(b"other-account").hexdigest()


@pytest.fixture(autouse=True)
def clear():
    broker._ACCOUNTS.clear()
    yield
    broker._ACCOUNTS.clear()


@pytest.mark.asyncio
async def test_human_priority_and_auto_handoff(monkeypatch):
    monkeypatch.setattr(broker, "_HUMAN_GRACE_SECONDS", 0.03)
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def person():
        async with broker.human_input(H):
            order.append("human-start")
            entered.set()
            await release.wait()
            order.append("human-end")

    async def agent():
        async with broker.agent_input(H):
            order.append("agent")

    h = asyncio.create_task(person())
    await entered.wait()
    a = asyncio.create_task(agent())
    await asyncio.sleep(.01)
    assert order == ["human-start"]
    release.set()
    await asyncio.gather(h, a)
    assert order == ["human-start", "human-end", "agent"]


@pytest.mark.asyncio
async def test_human_waiter_goes_before_queued_agent(monkeypatch):
    monkeypatch.setattr(broker, "_HUMAN_GRACE_SECONDS", 0)
    inside = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def first_agent():
        async with broker.agent_input(H):
            order.append("agent-1")
            inside.set()
            await release.wait()

    async def human():
        async with broker.human_input(H):
            order.append("human")

    async def second_agent():
        async with broker.agent_input(H):
            order.append("agent-2")

    a1 = asyncio.create_task(first_agent())
    await inside.wait()
    a2 = asyncio.create_task(second_agent())
    await asyncio.sleep(0)
    h = asyncio.create_task(human())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(a1, a2, h)
    assert order == ["agent-1", "human", "agent-2"]


@pytest.mark.asyncio
async def test_separate_accounts_do_not_block(monkeypatch):
    monkeypatch.setattr(broker, "_HUMAN_GRACE_SECONDS", 10)
    async with broker.human_input(H):
        async with broker.agent_input(H2):
            pass


@pytest.mark.asyncio
async def test_fail_closed_after_bounded_wait(monkeypatch):
    monkeypatch.setattr(broker, "_AGENT_WAIT_SECONDS", 0.02)
    monkeypatch.setattr(broker, "_HUMAN_GRACE_SECONDS", 10)
    async with broker.human_input(H):
        pass
    with pytest.raises(HTTPException) as exc:
        async with broker.agent_input(H):
            pytest.fail("agent must not run")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "SHARED_BROWSER_USER_ACTIVE"


@pytest.mark.asyncio
async def test_invalid_binding_rejected():
    with pytest.raises(HTTPException):
        async with broker.agent_input("bad"):
            pass


@pytest.mark.asyncio
async def test_human_viewer_and_plan_bound_agent_use_the_same_broker(monkeypatch):
    from api_v1 import azure_local_browser, azure_managed_executor, browserbase_executor

    monkeypatch.setattr(broker, "_HUMAN_GRACE_SECONDS", 0.02)
    entered = asyncio.Event()
    release = asyncio.Event()
    events = []

    async def real_viewer_action(_account_hash, _action):
        events.append("human-start")
        entered.set()
        await release.wait()
        events.append("human-end")
        return {"ok": True}

    async def fake_ensure(*_args, **_kwargs):
        return {"connected": True}

    async def fake_perform(_sid, _payload):
        events.append("agent")
        return 200, {"ok": True}

    async def fake_save(_sid):
        events.append("saved")

    monkeypatch.setattr(azure_local_browser, "_user_action_unlocked", real_viewer_action)
    monkeypatch.setattr(azure_managed_executor, "ensure_browser_session", fake_ensure)
    monkeypatch.setattr(azure_managed_executor, "_perform_action", fake_perform)
    monkeypatch.setattr(azure_local_browser, "save_session", fake_save)
    monkeypatch.setattr(browserbase_executor, "_load_capability", lambda _token: {"plan_hash": "f" * 64})
    monkeypatch.setattr(browserbase_executor, "_validate_envelope", lambda _cap, _payload: "cinema-real")
    monkeypatch.setattr(browserbase_executor, "_read_binding",
                        lambda _sid: {"provider": azure_local_browser.BACKEND_VALUE, "account_hash": H})

    human = asyncio.create_task(azure_local_browser.user_action(H, {"kind": "click"}))
    await entered.wait()
    agent = asyncio.create_task(azure_managed_executor.azure_action(
        "existing-permit", {"action": {"kind": "pointer.click", "parameters": {}}},
    ))
    await asyncio.sleep(.01)
    assert events == ["human-start"]
    release.set()
    assert (await human)["ok"] is True
    assert (await agent)["ok"] is True
    assert events == ["human-start", "human-end", "agent", "saved"]
