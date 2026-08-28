import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gate import gate_tool_calls, sha256_json  # noqa: E402


def tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_account",
                "description": "Read account state",
                "parameters": {
                    "type": "object",
                    "properties": {"account_id": {"type": "string"}},
                    "required": ["account_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "record_decision",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": ["ALLOW", "ALLOW-CONDITIONAL", "DENY", "ESCALATE"],
                        }
                    },
                    "required": ["decision"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def run(proposed, previous=None, turn=0):
    inventory = tools()
    return gate_tool_calls(
        proposed,
        inventory,
        content="ok",
        context_hash=sha256_json([{"kind": "policy", "content": "test"}]),
        toolset_hash=sha256_json(inventory),
        turn_index=turn,
        previous_receipt_hash=previous,
    )


def test_valid_call_passes_and_arguments_are_canonicalized():
    result = run(
        [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "lookup_account",
                    "arguments": '{"account_id": "abc"}',
                },
            }
        ]
    )
    assert result.status == "PASSED"
    assert result.reason_codes == []
    assert result.tool_calls[0]["function"]["arguments"] == '{"account_id":"abc"}'
    assert result.receipt["version"] == "dsg-pibench-proof/v2"
    assert len(result.receipt["receiptHash"]) == 64


def test_unknown_tool_fails_closed_and_emits_nothing():
    result = run(
        [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "delete_everything", "arguments": "{}"},
            }
        ]
    )
    assert result.status == "BLOCKED"
    assert result.tool_calls == []
    assert "UNKNOWN_TOOL:delete_everything" in result.reason_codes


def test_schema_violation_fails_closed():
    result = run(
        [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup_account", "arguments": "{}"},
            }
        ]
    )
    assert result.status == "BLOCKED"
    assert result.tool_calls == []
    assert "SCHEMA_VALIDATION_FAILED:lookup_account" in result.reason_codes


def test_invalid_decision_fails_closed():
    result = run(
        [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "record_decision",
                    "arguments": json.dumps({"decision": "MAYBE"}),
                },
            }
        ]
    )
    assert result.status == "BLOCKED"
    assert result.tool_calls == []


def test_action_after_final_decision_fails_closed_instead_of_reordering():
    result = run(
        [
            {
                "id": "decision",
                "type": "function",
                "function": {
                    "name": "record_decision",
                    "arguments": '{"decision":"ALLOW"}',
                },
            },
            {
                "id": "lookup",
                "type": "function",
                "function": {
                    "name": "lookup_account",
                    "arguments": '{"account_id":"abc"}',
                },
            },
        ]
    )
    assert result.status == "BLOCKED"
    assert result.tool_calls == []
    assert "ACTION_AFTER_FINAL_DECISION" in result.reason_codes


def test_valid_final_decision_last_preserves_order():
    result = run(
        [
            {
                "id": "lookup",
                "type": "function",
                "function": {
                    "name": "lookup_account",
                    "arguments": '{"account_id":"abc"}',
                },
            },
            {
                "id": "decision",
                "type": "function",
                "function": {
                    "name": "record_decision",
                    "arguments": '{"decision":"ALLOW"}',
                },
            },
        ]
    )
    assert result.status == "PASSED"
    assert [c["function"]["name"] for c in result.tool_calls] == [
        "lookup_account",
        "record_decision",
    ]


def test_multiple_final_decisions_fail_closed():
    result = run(
        [
            {
                "id": "decision-1",
                "type": "function",
                "function": {
                    "name": "record_decision",
                    "arguments": '{"decision":"ALLOW"}',
                },
            },
            {
                "id": "decision-2",
                "type": "function",
                "function": {
                    "name": "record_decision",
                    "arguments": '{"decision":"DENY"}',
                },
            },
        ]
    )
    assert result.status == "BLOCKED"
    assert result.tool_calls == []
    assert "MULTIPLE_FINAL_DECISIONS" in result.reason_codes


def test_duplicate_call_id_fails_closed():
    proposed = [
        {
            "id": "same",
            "type": "function",
            "function": {"name": "lookup_account", "arguments": '{"account_id":"a"}'},
        },
        {
            "id": "same",
            "type": "function",
            "function": {"name": "lookup_account", "arguments": '{"account_id":"b"}'},
        },
    ]
    result = run(proposed)
    assert result.status == "BLOCKED"
    assert result.tool_calls == []
    assert "DUPLICATE_TOOL_CALL_ID:same" in result.reason_codes


def test_receipt_is_deterministic_for_same_inputs():
    proposed = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup_account", "arguments": '{"account_id":"abc"}'},
        }
    ]
    assert run(proposed).receipt == run(proposed).receipt


def test_receipts_chain_between_turns():
    first = run([], turn=0)
    second = run([], previous=first.receipt["receiptHash"], turn=1)
    assert second.receipt["previousReceiptHash"] == first.receipt["receiptHash"]
    assert second.receipt["receiptHash"] != first.receipt["receiptHash"]
