"""Regression tests for governed Cinema sequential form batches.

Fake transport only; tests prove no unapproved retry or submit after an
uncertain action. The real provider remains the only authority in production.
"""
from __future__ import annotations

import asyncio

from fastapi import HTTPException

from api_v1 import remote_mcp


class FakeExecutor:
    def __init__(self):
        self.allocated = []
        self.revoked = []

    def allocate_capability(self, *, step_id, **kwargs):
        self.allocated.append(step_id)
        return step_id + "-cap"

    def finalize_capability(self, *args, **kwargs):
        return None

    async def ensure_browser_session(self, *args, **kwargs):
        return None

    def revoke_capability(self, value):
        self.revoked.append(value)


def _setup(monkeypatch, outcomes):
    executor = FakeExecutor()
    calls = []
    monkeypatch.setattr(remote_mcp.agent_pairing, "_authenticated_account",
                        lambda key: ("valid-cinema-account", None))
    monkeypatch.setattr(remote_mcp, "_current_api_key", lambda: "credential-not-output")
    monkeypatch.setattr(remote_mcp, "_validate_spacetime_context",
                        lambda **kwargs: {"provider_action": "browser.remote.run"})
    monkeypatch.setattr(remote_mcp, "_public_origin_var",
                        type("Origin", (), {"get": lambda self: "https://cinema.example"})())
    monkeypatch.setattr(remote_mcp, "_managed_executor", lambda: executor)
    monkeypatch.setattr(remote_mcp, "_managed_path", lambda: "self-hosted")

    async def connect(request, **kwargs):
        return {"session_id": request.step_id + "-session",
                "session_token": request.step_id + "-token",
                "plan_hash": "a" * 64, "browser_policy": {"allowed_origins": ["https://example.com"]}}

    async def action(request):
        kind = request.action.kind
        calls.append(kind)
        outcome = outcomes[kind]
        if isinstance(outcome, Exception):
            raise outcome
        return {"ok": outcome, "step_id": kind, "response": {"ok": outcome}}

    monkeypatch.setattr(remote_mcp.remote_pairing, "spacetime_agent_connect", connect)
    monkeypatch.setattr(remote_mcp, "_remote_action", action)
    return executor, calls


def _request(*actions, sequential=True):
    return remote_mcp.AutonomousRunRequest(
        plan_id="governed-plan",
        agent_identity="governed-agent",
        stop_on_success=not sequential,
        steps=[
            remote_mcp.AutonomousRunStep(
                step_id="s" + str(i),
                action={"kind": kind, "controller": "agent_executor",
                        "parameters": {"browser_allowed_origins": "https://example.com"}},
            )
            for i, kind in enumerate(actions, start=1)
        ],
    )


def test_sequential_batch_stops_before_submit_after_a_rejected_mutation(monkeypatch):
    executor, calls = _setup(monkeypatch, {
        "browser.navigate": True,
        "browser.type": HTTPException(status_code=403, detail={"error": "BROWSER_ORIGIN_BLOCKED"}),
        "browser.click": True,
    })
    result = asyncio.run(remote_mcp._remote_agent_run_plan(
        _request("browser.navigate", "browser.type", "browser.click")
    ))
    assert calls == ["browser.navigate", "browser.type"]
    assert result["ok"] is False
    assert result["all_steps_succeeded"] is False
    assert result["completed_all_steps"] is False
    assert result["failed_step_id"] == "s2"
    assert result["steps_attempted"] == 2
    assert "browser.click" not in calls
    assert executor.allocated == ["s1", "s2"]


def test_sequential_batch_requires_every_step_success(monkeypatch):
    _, calls = _setup(monkeypatch, {
        "browser.navigate": True, "browser.type": True, "browser.click": True,
    })
    result = asyncio.run(remote_mcp._remote_agent_run_plan(
        _request("browser.navigate", "browser.type", "browser.click")
    ))
    assert calls == ["browser.navigate", "browser.type", "browser.click"]
    assert result["ok"] is True
    assert result["all_steps_succeeded"] is True
    assert result["completed_all_steps"] is True
    assert result["failed_step_id"] is None
    assert result["steps_attempted"] == 3


def test_choice_mode_preserves_first_success_semantics(monkeypatch):
    _, calls = _setup(monkeypatch, {
        "browser.navigate": True, "browser.type": True,
    })
    result = asyncio.run(remote_mcp._remote_agent_run_plan(
        _request("browser.navigate", "browser.type", sequential=False)
    ))
    assert calls == ["browser.navigate"]
    assert result["ok"] is True
    assert result["all_steps_succeeded"] is False
    assert result["completed_all_steps"] is False
    assert result["failed_step_id"] is None
