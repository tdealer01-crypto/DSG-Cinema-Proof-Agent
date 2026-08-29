from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from cinema_mcp import CinemaMcpError, call_cinema_mcp
from gate import sha256_json


class CinemaDecisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CinemaBatchDecision:
    decision: str
    payloads: list[dict[str, Any]]


def cinema_preflight_mode() -> str:
    mode = os.getenv("CINEMA_PREFLIGHT_MODE", "off").strip().lower() or "off"
    if mode not in {"off", "required"}:
        raise CinemaDecisionError(
            "CINEMA_PREFLIGHT_MODE must be either 'off' or 'required'"
        )
    return mode


def _required_binding(context_hash: str) -> tuple[str, str]:
    plan_id = os.getenv("CINEMA_PIBENCH_PLAN_ID", "").strip()
    bindings_raw = os.getenv("CINEMA_PIBENCH_PLAN_BINDINGS_JSON", "").strip()
    if bindings_raw:
        try:
            bindings = json.loads(bindings_raw)
        except json.JSONDecodeError as exc:
            raise CinemaDecisionError(
                "CINEMA_PIBENCH_PLAN_BINDINGS_JSON is not valid JSON"
            ) from exc
        if not isinstance(bindings, dict):
            raise CinemaDecisionError(
                "CINEMA_PIBENCH_PLAN_BINDINGS_JSON must be an object"
            )
        mapped = bindings.get(context_hash)
        if mapped is not None:
            if not isinstance(mapped, str) or not mapped.strip():
                raise CinemaDecisionError(
                    "Cinema plan binding for this PI-Bench context is invalid"
                )
            plan_id = mapped.strip()

    agent_identity = os.getenv("CINEMA_PIBENCH_AGENT_IDENTITY", "").strip()
    if not plan_id:
        raise CinemaDecisionError(
            "Cinema preflight is required but no approved plan is bound to this PI-Bench context"
        )
    if not agent_identity:
        raise CinemaDecisionError(
            "Cinema preflight is required but CINEMA_PIBENCH_AGENT_IDENTITY is not configured"
        )
    return plan_id, agent_identity


def governed_target(*, context_hash: str, toolset_hash: str) -> str:
    target = f"pibench:{context_hash}:{toolset_hash}"
    if len(target) > 255:
        raise CinemaDecisionError("PI-Bench governed target exceeds Cinema contract limit")
    return target


def governed_step_id(*, context_hash: str, toolset_hash: str, tool_name: str) -> str:
    digest = sha256_json(
        {
            "context_hash": context_hash,
            "tool_name": tool_name,
            "toolset_hash": toolset_hash,
        }
    )
    return f"pib-{digest[:60]}"


def build_observed_action(
    *,
    context_hash: str,
    toolset_hash: str,
    proposed_tool_call: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    function = proposed_tool_call.get("function")
    if not isinstance(function, dict):
        raise CinemaDecisionError("PI-Bench proposal has no function object")

    tool_name = str(function.get("name") or "").strip()
    if not tool_name:
        raise CinemaDecisionError("PI-Bench proposal has no tool name")
    if len(tool_name) > 64:
        raise CinemaDecisionError("PI-Bench tool name exceeds Cinema action limit")

    target = governed_target(context_hash=context_hash, toolset_hash=toolset_hash)
    step_id = governed_step_id(
        context_hash=context_hash,
        toolset_hash=toolset_hash,
        tool_name=tool_name,
    )
    proposal_hash = sha256_json(
        {
            "call_id": str(proposed_tool_call.get("id") or ""),
            "function": function,
        }
    )

    # The approved Cinema plan governs the benchmark context/tool surface. The
    # concrete PI-Bench arguments are deliberately not copied into plan parameters:
    # they are validated by the local deterministic JSON-Schema gate after Cinema
    # authorization. The trace id binds this preflight record to the exact proposal.
    action = {
        "action": tool_name,
        "target": target,
        "step_id": step_id,
        "parameters": {},
        "status": "skipped",
    }
    return action, f"pib-{proposal_hash}"


def _payload_from_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("isError") is True:
        raise CinemaDecisionError("Cinema MCP preflight returned an error result")

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured

    content = result.get("content")
    if not isinstance(content, list) or not content:
        raise CinemaDecisionError("Cinema MCP returned no preflight content")

    text = content[0].get("text") if isinstance(content[0], dict) else None
    if not isinstance(text, str):
        raise CinemaDecisionError("Cinema MCP returned invalid preflight content")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CinemaDecisionError("Cinema MCP preflight content was not JSON") from exc

    if not isinstance(payload, dict):
        raise CinemaDecisionError("Cinema MCP preflight payload was not an object")
    return payload


def _validate_preflight_payload(
    payload: dict[str, Any],
    *,
    plan_id: str,
    action: dict[str, Any],
) -> str:
    decision = str(payload.get("decision") or "").upper()
    if decision not in {"ALLOW", "WAITING_PERMISSION", "BLOCK"}:
        raise CinemaDecisionError(
            f"Cinema MCP returned unsupported decision: {decision or 'missing'}"
        )

    expected = {
        "plan_id": plan_id,
        "step_id": action["step_id"],
        "action": action["action"],
        "target": action["target"],
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CinemaDecisionError(
                f"Cinema MCP preflight response did not preserve {key} binding"
            )

    if decision == "ALLOW":
        if payload.get("allowed") is not True or payload.get("execution_ready") is not True:
            raise CinemaDecisionError("Cinema ALLOW response was not execution-ready")
    elif decision == "WAITING_PERMISSION":
        if payload.get("allowed") is not True or payload.get("execution_ready") is not False:
            raise CinemaDecisionError(
                "Cinema WAITING_PERMISSION response had inconsistent authorization state"
            )
    elif payload.get("allowed") is not False:
        raise CinemaDecisionError("Cinema BLOCK response had inconsistent authorization state")

    return decision


async def evaluate_with_cinema(
    *,
    context_hash: str,
    toolset_hash: str,
    proposed_tool_calls: list[dict[str, Any]],
) -> CinemaBatchDecision:
    """Preflight model proposals against an already-approved Cinema plan.

    This function never creates or approves a plan and never executes PI-Bench tools.
    In required mode, missing bindings, transport errors, schema mismatches, and
    inconsistent decisions all fail closed.
    """
    if cinema_preflight_mode() == "off" or not proposed_tool_calls:
        return CinemaBatchDecision(decision="ALLOW", payloads=[])

    plan_id, agent_identity = _required_binding(context_hash)
    payloads: list[dict[str, Any]] = []

    for proposed in proposed_tool_calls:
        action, trace_id = build_observed_action(
            context_hash=context_hash,
            toolset_hash=toolset_hash,
            proposed_tool_call=proposed,
        )
        arguments = {
            "plan_id": plan_id,
            "agent_identity": agent_identity,
            "action": action,
            "channel": "pibench-agentbeats",
            "trace_id": trace_id,
        }
        try:
            result = await call_cinema_mcp(
                "tools/call",
                {"name": "dsg_preflight_action", "arguments": arguments},
            )
        except CinemaMcpError as exc:
            raise CinemaDecisionError(str(exc)) from exc

        payload = _payload_from_result(result)
        decision = _validate_preflight_payload(payload, plan_id=plan_id, action=action)
        payloads.append(payload)
        if decision != "ALLOW":
            return CinemaBatchDecision(decision=decision, payloads=payloads)

    return CinemaBatchDecision(decision="ALLOW", payloads=payloads)
