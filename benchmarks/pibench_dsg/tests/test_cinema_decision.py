from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cinema_decision  # noqa: E402


CONTEXT_HASH = "c" * 64
TOOLSET_HASH = "t" * 64


def proposal(name="lookup_account", arguments='{"account_id":"abc"}'):
    return {
        "id": "call-1",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def bind_env(monkeypatch):
    monkeypatch.setenv("CINEMA_PREFLIGHT_MODE", "required")
    monkeypatch.setenv("CINEMA_PIBENCH_PLAN_ID", "plan-approved-1")
    monkeypatch.setenv("CINEMA_PIBENCH_AGENT_IDENTITY", "dsg-pibench-agent")
    monkeypatch.delenv("CINEMA_PIBENCH_PLAN_BINDINGS_JSON", raising=False)


def test_governed_action_is_real_observed_action_without_agent_verdicts():
    action, trace_id = cinema_decision.build_observed_action(
        context_hash=CONTEXT_HASH,
        toolset_hash=TOOLSET_HASH,
        proposed_tool_call=proposal(),
    )

    assert action["action"] == "lookup_account"
    assert action["target"] == f"pibench:{CONTEXT_HASH}:{TOOLSET_HASH}"
    assert action["step_id"].startswith("pib-")
    assert len(action["step_id"]) == 64
    assert action["parameters"] == {}
    assert action["status"] == "skipped"
    assert trace_id.startswith("pib-")
    assert "decision" not in action
    assert "verified" not in action


def test_preflight_uses_production_contract_and_never_self_approves(monkeypatch):
    bind_env(monkeypatch)
    seen = []

    async def fake(method, params=None):
        seen.append((method, params))
        args = params["arguments"]
        action = args["action"]
        return {
            "isError": False,
            "structuredContent": {
                "allowed": True,
                "execution_ready": True,
                "decision": "ALLOW",
                "plan_id": args["plan_id"],
                "step_id": action["step_id"],
                "action": action["action"],
                "target": action["target"],
            },
        }

    monkeypatch.setattr(cinema_decision, "call_cinema_mcp", fake)
    result = asyncio.run(
        cinema_decision.evaluate_with_cinema(
            context_hash=CONTEXT_HASH,
            toolset_hash=TOOLSET_HASH,
            proposed_tool_calls=[proposal(arguments='{"nested":{"x":1}}')],
        )
    )

    assert result.decision == "ALLOW"
    assert len(result.payloads) == 1
    method, params = seen[0]
    assert method == "tools/call"
    assert params["name"] == "dsg_preflight_action"
    args = params["arguments"]
    assert set(args) == {"plan_id", "agent_identity", "action", "channel", "trace_id"}
    assert args["plan_id"] == "plan-approved-1"
    assert args["agent_identity"] == "dsg-pibench-agent"
    assert args["action"]["parameters"] == {}
    assert "source" not in args
    assert all(item[1]["name"] not in {"dsg_create_plan", "dsg_approve_plan"} for item in seen)


def test_context_specific_plan_binding_overrides_single_plan(monkeypatch):
    bind_env(monkeypatch)
    monkeypatch.setenv(
        "CINEMA_PIBENCH_PLAN_BINDINGS_JSON",
        '{"' + CONTEXT_HASH + '":"plan-context-specific"}',
    )
    captured = {}

    async def fake(_method, params=None):
        args = params["arguments"]
        captured.update(args)
        action = args["action"]
        return {
            "structuredContent": {
                "allowed": True,
                "execution_ready": True,
                "decision": "ALLOW",
                "plan_id": args["plan_id"],
                "step_id": action["step_id"],
                "action": action["action"],
                "target": action["target"],
            }
        }

    monkeypatch.setattr(cinema_decision, "call_cinema_mcp", fake)
    asyncio.run(
        cinema_decision.evaluate_with_cinema(
            context_hash=CONTEXT_HASH,
            toolset_hash=TOOLSET_HASH,
            proposed_tool_calls=[proposal()],
        )
    )
    assert captured["plan_id"] == "plan-context-specific"


def test_waiting_permission_stops_batch_before_later_tool_calls(monkeypatch):
    bind_env(monkeypatch)
    calls = []

    async def fake(_method, params=None):
        calls.append(params)
        args = params["arguments"]
        action = args["action"]
        return {
            "structuredContent": {
                "allowed": True,
                "execution_ready": False,
                "decision": "WAITING_PERMISSION",
                "plan_id": args["plan_id"],
                "step_id": action["step_id"],
                "action": action["action"],
                "target": action["target"],
            }
        }

    monkeypatch.setattr(cinema_decision, "call_cinema_mcp", fake)
    result = asyncio.run(
        cinema_decision.evaluate_with_cinema(
            context_hash=CONTEXT_HASH,
            toolset_hash=TOOLSET_HASH,
            proposed_tool_calls=[proposal(), proposal(name="record_decision")],
        )
    )
    assert result.decision == "WAITING_PERMISSION"
    assert len(calls) == 1


def test_required_mode_without_approved_plan_binding_fails_closed(monkeypatch):
    monkeypatch.setenv("CINEMA_PREFLIGHT_MODE", "required")
    monkeypatch.delenv("CINEMA_PIBENCH_PLAN_ID", raising=False)
    monkeypatch.delenv("CINEMA_PIBENCH_PLAN_BINDINGS_JSON", raising=False)
    monkeypatch.setenv("CINEMA_PIBENCH_AGENT_IDENTITY", "dsg-pibench-agent")

    with pytest.raises(cinema_decision.CinemaDecisionError, match="no approved plan"):
        asyncio.run(
            cinema_decision.evaluate_with_cinema(
                context_hash=CONTEXT_HASH,
                toolset_hash=TOOLSET_HASH,
                proposed_tool_calls=[proposal()],
            )
        )


def test_inconsistent_allow_response_fails_closed(monkeypatch):
    bind_env(monkeypatch)

    async def fake(_method, params=None):
        args = params["arguments"]
        action = args["action"]
        return {
            "structuredContent": {
                "allowed": True,
                "execution_ready": False,
                "decision": "ALLOW",
                "plan_id": args["plan_id"],
                "step_id": action["step_id"],
                "action": action["action"],
                "target": action["target"],
            }
        }

    monkeypatch.setattr(cinema_decision, "call_cinema_mcp", fake)
    with pytest.raises(cinema_decision.CinemaDecisionError, match="not execution-ready"):
        asyncio.run(
            cinema_decision.evaluate_with_cinema(
                context_hash=CONTEXT_HASH,
                toolset_hash=TOOLSET_HASH,
                proposed_tool_calls=[proposal()],
            )
        )
