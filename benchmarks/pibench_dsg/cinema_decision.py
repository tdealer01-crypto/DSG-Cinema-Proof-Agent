from __future__ import annotations

import json
from typing import Any

from cinema_mcp import CinemaMcpError, call_cinema_mcp


class CinemaDecisionError(RuntimeError):
    pass


async def evaluate_with_cinema(
    *,
    benchmark_context: list[dict[str, Any]],
    proposed_tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask production Cinema for an independent preflight decision.

    This does not execute PI-Bench tools. It only maps a model proposal into a
    governance check. Any transport/schema ambiguity fails closed.
    """
    try:
        result = await call_cinema_mcp(
            "tools/call",
            {
                "name": "dsg_preflight_action",
                "arguments": {
                    "source": "pibench-agentbeats",
                    "action": {
                        "benchmark_context": benchmark_context,
                        "proposed_tool_calls": proposed_tool_calls,
                    },
                },
            },
        )
    except CinemaMcpError as exc:
        raise CinemaDecisionError(str(exc)) from exc

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

    decision = str(payload.get("decision") or payload.get("status") or "").upper()
    if decision not in {"ALLOW", "BLOCK", "WAITING_PERMISSION", "DENY", "ESCALATE"}:
        raise CinemaDecisionError(f"Cinema MCP returned unsupported decision: {decision or 'missing'}")

    return payload
