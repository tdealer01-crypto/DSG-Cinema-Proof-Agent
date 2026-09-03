from __future__ import annotations

import asyncio

from api_v1 import dashboard_chat
from api_v1.models import PlanDocument, PlanStep


def test_mcp_receive_includes_agent_replies(monkeypatch):
    monkeypatch.setattr(
        dashboard_chat,
        "_mcp_account",
        lambda: ("dsg_live_test", "acct-chat", "chat-agent"),
    )
    monkeypatch.setattr(
        dashboard_chat,
        "_read",
        lambda _account_id: {
            "seq": 3,
            "messages": [
                {"seq": 1, "role": "user", "text": "hello"},
                {"seq": 2, "role": "agent", "text": "reply"},
                {"seq": 3, "role": "system", "text": "status"},
            ],
        },
    )

    result = asyncio.run(dashboard_chat._mcp_receive(dashboard_chat.ChatReceiveArgs(after_seq=0, limit=30)))

    assert [item["role"] for item in result["messages"]] == ["user", "agent", "system"]
    assert result["last_seq"] == 3


def test_mcp_receive_respects_after_seq_for_agent_replies(monkeypatch):
    monkeypatch.setattr(
        dashboard_chat,
        "_mcp_account",
        lambda: ("dsg_live_test", "acct-chat", "chat-agent"),
    )
    monkeypatch.setattr(
        dashboard_chat,
        "_read",
        lambda _account_id: {
            "seq": 2,
            "messages": [
                {"seq": 1, "role": "user", "text": "hello"},
                {"seq": 2, "role": "agent", "text": "reply"},
            ],
        },
    )

    result = asyncio.run(dashboard_chat._mcp_receive(dashboard_chat.ChatReceiveArgs(after_seq=1, limit=30)))

    assert result["messages"] == [{"seq": 2, "role": "agent", "text": "reply"}]
    assert result["last_seq"] == 2


def test_agent_can_propose_plan_but_only_user_approval_binds_it(monkeypatch):
    monkeypatch.setattr(
        dashboard_chat,
        "_mcp_account",
        lambda: ("dsg_live_test", "acct-chat", "chat-agent"),
    )
    monkeypatch.setattr(
        dashboard_chat.service,
        "create_plan",
        lambda _plan: {"plan_id": "plan-chat-1", "plan_hash": "a" * 64, "status": "DRAFT"},
    )
    captured = {}

    def fake_append(account_id, **kwargs):
        captured["account_id"] = account_id
        captured.update(kwargs)
        return {"message_id": "chat-approval-1", **kwargs}

    monkeypatch.setattr(dashboard_chat, "_append_message", fake_append)
    plan = PlanDocument(
        title="Find legal movie availability",
        agent_identity="chat-agent",
        steps=[PlanStep(step_id="search", action="browser_workflow", target="justwatch.com")],
    )

    result = asyncio.run(
        dashboard_chat._mcp_create_plan(
            dashboard_chat.ChatPlanArgs(plan=plan, summary="Search legal availability")
        )
    )

    assert result["requires_user_approval"] is True
    assert captured["role"] == "agent"
    assert captured["approval"]["status"] == "pending"
    assert captured["approval"]["plan_id"] == "plan-chat-1"
