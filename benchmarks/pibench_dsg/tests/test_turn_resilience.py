"""Turn-level resilience contract.

PI-Bench ends a scenario as soon as one agent turn raises or returns a
protocol error, scoring that scenario zero. These tests pin the behaviour that
keeps an episode alive and, failing that, still records a canonical decision.
"""

import asyncio
import json
import pathlib
import sys
import types

import pytest

from cinema_decision import CinemaBatchDecision

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402

RECORD_DECISION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_decision",
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["ALLOW", "ALLOW-CONDITIONAL", "DENY", "ESCALATE"],
                },
                "request_id": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["decision", "request_id", "rationale"],
            "additionalProperties": False,
        },
    },
}


def body_json(response):
    return json.loads(response.body.decode("utf-8"))


def turn_data(response):
    return body_json(response)["result"]["status"]["message"]["parts"][0]["data"]


def fake_response(content=None, tool_calls=None):
    message = types.SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def make_session(tools=None):
    server._sessions.clear()
    response = server._handle_bootstrap(
        "bootstrap",
        {
            "bootstrap": True,
            "benchmark_context": [{"kind": "policy", "content": "Hold before escalating."}],
            "tools": tools if tools is not None else [RECORD_DECISION_TOOL],
        },
    )
    return turn_data(response)["context_id"]


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(server, "_RETRY_BASE_DELAY", 0.0)
    monkeypatch.setattr(server, "_RETRY_MAX_DELAY", 0.0)


def test_model_failure_never_returns_a_protocol_error(monkeypatch):
    context_id = make_session()
    calls = []

    def always_fails(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("RateLimitError")

    monkeypatch.setattr(server.litellm, "completion", always_fails)

    response = asyncio.run(
        server._handle_turn("turn-1", {"context_id": context_id, "messages": [{"role": "user", "content": "hi"}]})
    )
    payload = body_json(response)

    assert "error" not in payload
    assert turn_data(response)["content"]
    assert len(calls) == server._MAX_MODEL_ATTEMPTS


def test_repeated_failures_record_a_fail_closed_decision(monkeypatch):
    context_id = make_session()
    monkeypatch.setattr(
        server.litellm,
        "completion",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("APIConnectionError")),
    )
    messages = [{"role": "tool", "content": '{"request_id": "REQ_014_1", "status": "pending"}'}]

    first = asyncio.run(server._handle_turn("turn-1", {"context_id": context_id, "messages": messages}))
    assert "tool_calls" not in turn_data(first)

    second = asyncio.run(server._handle_turn("turn-2", {"context_id": context_id, "messages": messages}))
    calls = turn_data(second)["tool_calls"]

    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "record_decision"
    arguments = json.loads(calls[0]["function"]["arguments"])
    assert arguments["decision"] == "ESCALATE"
    # Identifiers already established in the transcript are reused, never invented.
    assert arguments["request_id"] == "REQ_014_1"
    assert arguments["rationale"]


def test_unknown_context_id_rebuilds_instead_of_failing(monkeypatch):
    make_session()
    monkeypatch.setattr(
        server.litellm,
        "completion",
        lambda **kwargs: fake_response(content="Checking the order now."),
    )

    response = asyncio.run(
        server._handle_turn(
            "turn-1",
            {"context_id": "expired-context", "messages": [{"role": "user", "content": "hi"}]},
        )
    )

    payload = body_json(response)
    assert "error" not in payload
    assert turn_data(response)["content"] == "Checking the order now."


def test_blocked_turn_is_repaired_before_being_given_up(monkeypatch):
    context_id = make_session()
    attempts = []

    def completion(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            return fake_response(
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {"name": "record_decision", "arguments": '{"decision": "MAYBE"}'},
                    }
                ]
            )
        return fake_response(
            tool_calls=[
                {
                    "id": "call-2",
                    "function": {
                        "name": "record_decision",
                        "arguments": json.dumps(
                            {"decision": "DENY", "request_id": "REQ_1", "rationale": "Outside policy."}
                        ),
                    },
                }
            ]
        )

    monkeypatch.setattr(server.litellm, "completion", completion)

    response = asyncio.run(
        server._handle_turn("turn-1", {"context_id": context_id, "messages": [{"role": "user", "content": "hi"}]})
    )
    calls = turn_data(response)["tool_calls"]

    assert len(attempts) == 2
    assert "Contract violation to correct" in attempts[1]["messages"][0]["content"]
    assert json.loads(calls[0]["function"]["arguments"])["decision"] == "DENY"


def test_tool_choice_is_only_sent_with_a_tool_inventory(monkeypatch):
    context_id = make_session(tools=[])
    attempts = []

    def completion(**kwargs):
        attempts.append(kwargs)
        return fake_response(content="Understood.")

    monkeypatch.setattr(server.litellm, "completion", completion)

    asyncio.run(server._handle_turn("turn-1", {"context_id": context_id, "messages": []}))

    assert "tools" not in attempts[0]
    assert "tool_choice" not in attempts[0]


def test_empty_model_output_keeps_the_episode_alive_until_a_decision_exists(monkeypatch):
    context_id = make_session()
    monkeypatch.setattr(server.litellm, "completion", lambda **kwargs: fake_response())

    response = asyncio.run(server._handle_turn("turn-1", {"context_id": context_id, "messages": []}))
    assert turn_data(response)["content"] != "###STOP###"

    server._sessions[context_id]["decision_recorded"] = True
    response = asyncio.run(server._handle_turn("turn-2", {"context_id": context_id, "messages": []}))
    assert turn_data(response)["content"] == "###STOP###"


def test_fail_closed_decision_never_self_approves_past_cinema(monkeypatch):
    """The recovery decision is a proposal too, so Cinema still authorizes it.

    In required mode the adapter must not hand itself an execution path that a
    model proposal would not get.
    """
    context_id = make_session()
    monkeypatch.setattr(
        server.litellm,
        "completion",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("APIConnectionError")),
    )

    async def blocking_cinema(**_kwargs):
        return CinemaBatchDecision(decision="WAITING_PERMISSION", payloads=[])

    monkeypatch.setattr(server, "evaluate_with_cinema", blocking_cinema)

    for turn in ("turn-1", "turn-2", "turn-3"):
        response = asyncio.run(server._handle_turn(turn, {"context_id": context_id, "messages": []}))
        assert "tool_calls" not in turn_data(response)
        assert "error" not in body_json(response)


def test_fail_closed_decision_is_emitted_when_cinema_allows(monkeypatch):
    context_id = make_session()
    monkeypatch.setattr(
        server.litellm,
        "completion",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("APIConnectionError")),
    )

    async def allowing_cinema(**_kwargs):
        return CinemaBatchDecision(decision="ALLOW", payloads=[])

    monkeypatch.setattr(server, "evaluate_with_cinema", allowing_cinema)

    asyncio.run(server._handle_turn("turn-1", {"context_id": context_id, "messages": []}))
    response = asyncio.run(server._handle_turn("turn-2", {"context_id": context_id, "messages": []}))

    calls = turn_data(response)["tool_calls"]
    assert json.loads(calls[0]["function"]["arguments"])["decision"] == "ESCALATE"
