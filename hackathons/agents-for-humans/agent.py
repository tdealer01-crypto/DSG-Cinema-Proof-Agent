from __future__ import annotations

import json
from typing import Any

from strands import Agent, tool

from dsg_client import VerificationError, verify_execution as call_dsg


@tool
def verify_bounded_execution(
    execution_id: str,
    trace_id: str,
    agent_identity: str,
    approved_plan_hash: str,
    proposed_action_hash: str,
    authorized: bool,
    plan_aligned: bool,
    constraints_pass: bool,
    execution_succeeded: bool,
    replay_match: bool,
    evidence_complete: bool,
    cost_microunits: int = 0,
) -> str:
    """Verify a bounded professional-agent action with DSG and return its proof receipt.

    Only call this tool when the input facts come from observed evidence. Never invent
    missing evidence. A failed verification is returned as an explicit failure and must
    never be treated as ALLOW.
    """
    payload: dict[str, Any] = {
        "execution_id": execution_id,
        "trace_id": trace_id,
        "channel": "devpost_strands",
        "agent_identity": agent_identity,
        "approved_plan_hash": approved_plan_hash,
        "proposed_action_hash": proposed_action_hash,
        "authorized": authorized,
        "plan_aligned": plan_aligned,
        "constraints_pass": constraints_pass,
        "execution_succeeded": execution_succeeded,
        "replay_match": replay_match,
        "evidence_complete": evidence_complete,
        "cost_microunits": max(0, cost_microunits),
    }
    try:
        receipt = call_dsg(payload)
    except VerificationError as exc:
        return json.dumps({"status": "VERIFICATION_FAILED", "error": str(exc)})

    return json.dumps(
        {
            "status": "VERIFIED",
            "decision": receipt["decision"],
            "verification": receipt["verification"],
            "proof_hash": receipt["proof_hash"],
            "request_hash": receipt["request_hash"],
            "context_hash": receipt["context_hash"],
        },
        sort_keys=True,
    )


def build_agent() -> Agent:
    return Agent(tools=[verify_bounded_execution])


def main() -> None:
    agent = build_agent()
    agent(
        "You are a professional automation agent. Before reporting a bounded action as "
        "verified, use verify_bounded_execution with evidence-backed facts. If verification "
        "fails or returns BLOCK, state that clearly and do not claim success."
    )


if __name__ == "__main__":
    main()
