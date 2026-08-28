from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError
from jsonschema.validators import validator_for

_ALLOWED_DECISIONS = {"ALLOW", "ALLOW-CONDITIONAL", "DENY", "ESCALATE"}
_RECEIPT_VERSION = "dsg-pibench-proof/v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GateResult:
    status: str
    tool_calls: list[dict[str, Any]]
    reason_codes: list[str]
    receipt: dict[str, Any]


def _tool_registry(tools: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    registry: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for index, raw in enumerate(tools):
        if not isinstance(raw, dict):
            errors.append(f"INVALID_TOOL_SCHEMA:{index}")
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
        name = str(function.get("name", "")).strip() if isinstance(function, dict) else ""
        parameters = function.get("parameters", {"type": "object"}) if isinstance(function, dict) else None
        if not name or not isinstance(parameters, dict):
            errors.append(f"INVALID_TOOL_SCHEMA:{index}")
            continue
        if name in registry:
            errors.append(f"DUPLICATE_TOOL_SCHEMA:{name}")
            continue
        try:
            validator_cls = validator_for(parameters)
            validator_cls.check_schema(parameters)
        except Exception:
            errors.append(f"INVALID_TOOL_SCHEMA:{name}")
            continue
        registry[name] = parameters
    return registry, errors


def gate_tool_calls(
    proposed_tool_calls: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    content: str | None,
    context_hash: str,
    toolset_hash: str,
    turn_index: int,
    previous_receipt_hash: str | None = None,
) -> GateResult:
    """Validate and deterministically shape model-proposed benchmark tool calls.

    This gate verifies the execution contract, not the semantic correctness of the
    underlying policy decision. PI-Bench remains the independent semantic/state
    evaluator. Any malformed/unknown tool request is fail-closed and no tool call
    is emitted for that turn.
    """

    registry, reasons = _tool_registry(tools)
    accepted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(proposed_tool_calls):
        if not isinstance(raw, dict):
            reasons.append(f"INVALID_TOOL_CALL:{index}")
            continue

        call_id = str(raw.get("id", "")).strip()
        function = raw.get("function")
        if not call_id or not isinstance(function, dict):
            reasons.append(f"INVALID_TOOL_CALL:{index}")
            continue
        if call_id in seen_ids:
            reasons.append(f"DUPLICATE_TOOL_CALL_ID:{call_id}")
            continue
        seen_ids.add(call_id)

        name = str(function.get("name", "")).strip()
        if name not in registry:
            reasons.append(f"UNKNOWN_TOOL:{name or index}")
            continue

        raw_arguments = function.get("arguments", "{}")
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                reasons.append(f"INVALID_JSON_ARGUMENTS:{name}")
                continue
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            reasons.append(f"INVALID_ARGUMENT_TYPE:{name}")
            continue

        if not isinstance(arguments, dict):
            reasons.append(f"INVALID_ARGUMENT_TYPE:{name}")
            continue

        schema = registry[name]
        try:
            validator_for(schema)(schema).validate(arguments)
        except ValidationError:
            reasons.append(f"SCHEMA_VALIDATION_FAILED:{name}")
            continue
        except Exception:
            reasons.append(f"SCHEMA_VALIDATION_FAILED:{name}")
            continue

        if name == "record_decision":
            decision = arguments.get("decision")
            if decision not in _ALLOWED_DECISIONS:
                reasons.append("INVALID_DECISION_VALUE")
                continue

        accepted.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": canonical_json(arguments),
                },
            }
        )

    proposed_hash = sha256_json(proposed_tool_calls)
    content_hash = hashlib.sha256((content or "").encode("utf-8")).hexdigest()

    if reasons:
        status = "BLOCKED"
        emitted: list[dict[str, Any]] = []
        shaped = False
    else:
        # PI-Bench treats record_decision as the canonical terminal decision. Keep
        # all non-decision calls in model order and deterministically place decision
        # calls last so no operational action is emitted after the decision.
        non_decisions = [c for c in accepted if c["function"]["name"] != "record_decision"]
        decisions = [c for c in accepted if c["function"]["name"] == "record_decision"]
        emitted = [*non_decisions, *decisions]
        shaped = emitted != accepted
        status = "PASSED"

    receipt_core = {
        "version": _RECEIPT_VERSION,
        "status": status,
        "reasonCodes": sorted(set(reasons)),
        "turnIndex": int(turn_index),
        "contextHash": context_hash,
        "toolsetHash": toolset_hash,
        "contentHash": content_hash,
        "proposedToolCallsHash": proposed_hash,
        "emittedToolCallsHash": sha256_json(emitted),
        "deterministicallyShaped": shaped,
        "previousReceiptHash": previous_receipt_hash,
    }
    receipt = {**receipt_core, "receiptHash": sha256_json(receipt_core)}

    return GateResult(
        status=status,
        tool_calls=emitted,
        reason_codes=sorted(set(reasons)),
        receipt=receipt,
    )
