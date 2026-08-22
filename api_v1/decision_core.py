"""Unified DSG execution decision core.

Policy invariant for every production adapter:
- approved exact plan work is enabled and receives a scoped capability grant;
- missing infrastructure/credentials is a provisioning state, not a policy BLOCK;
- work outside the approved plan is BLOCK;
- final PASS/FAIL is decided later from execution evidence and proof.

Adapters (mobile, MCP, REST, browser, deployment, marketplace) and execution
recording call this module instead of re-implementing approval semantics.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .alignment import evaluate_alignment
from .canonical import canonical_hash, utc_now
from .models import ObservedAction, Scalar, Strict

Decision = Literal["ALLOW", "WAITING_PERMISSION", "BLOCK"]


class CapabilityNeed(Strict):
    """One capability/infrastructure item required by an approved step.

    `available=False` never changes an approved action into BLOCK. It changes the
    execution state to WAITING_PERMISSION so the orchestrator can provision or
    resolve the required capability and retry the same approved step.
    """

    capability: str = Field(min_length=1, max_length=128)
    available: bool = True
    source: str | None = Field(default=None, max_length=128)
    remediation: str | None = Field(default=None, max_length=512)


class CorePreflightRequest(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    plan_hash: str = Field(min_length=64, max_length=64)
    plan_status: str = Field(min_length=1, max_length=32)
    approved_agent_identity: str = Field(min_length=1, max_length=255)
    agent_identity: str = Field(min_length=1, max_length=255)
    action: ObservedAction
    capability_needs: list[CapabilityNeed] = Field(default_factory=list, max_length=32)
    channel: str = Field(default="api", min_length=1, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)
    client_context: dict[str, Scalar] = Field(default_factory=dict)


def _grant_scope(request: CorePreflightRequest, action_trace_hash: str) -> dict[str, Any]:
    return {
        "plan_id": request.plan_id,
        "plan_hash": request.plan_hash,
        "agent_identity": request.agent_identity,
        "step_id": request.action.step_id,
        "action": request.action.action,
        "target": request.action.target,
        "parameters": request.action.parameters,
        "channel": request.channel,
        "action_trace_hash": action_trace_hash,
        "client_context": request.client_context,
    }


def _grant(request: CorePreflightRequest, action_trace_hash: str) -> dict[str, Any]:
    scope = _grant_scope(request, action_trace_hash)
    return {
        "status": "GRANTED",
        "scope": scope,
        "scope_hash": canonical_hash(scope),
        "permissions": [
            "execute_exact_approved_step",
            "use_required_executor_tools_for_step",
            "resolve_server_side_capabilities_for_step",
            "record_execution_evidence",
            "continue_to_verification",
        ],
        "credential_policy": (
            "credentials remain server-side; the executor resolves only credentials required "
            "for this exact approved scope and never exposes them to the client"
        ),
    }


def evaluate_plan_authorization(
    *,
    request: CorePreflightRequest,
    plan_document: Any,
) -> dict[str, Any]:
    """Return the canonical execution decision for one proposed plan step."""

    if request.plan_status != "APPROVED":
        return _blocked(
            request,
            code="PLAN_NOT_APPROVED",
            reason="the referenced plan is not approved and locked",
            next_step="Approve the plan first; no execution capability is granted for a draft plan.",
        )

    if request.approved_agent_identity != request.agent_identity:
        return _blocked(
            request,
            code="AGENT_IDENTITY_MISMATCH",
            reason=(
                f"approved plan names agent '{request.approved_agent_identity}' but the executor supplied "
                f"'{request.agent_identity}'"
            ),
            next_step="Use the approved agent identity or approve a changed plan.",
        )

    alignment = evaluate_alignment(plan_document, [request.action])
    findings = [
        item for item in alignment["findings"] if item.get("code") != "STEP_NOT_EXECUTED"
    ]

    # Any finding attached to the proposed action means the caller changed the
    # approved step. That is outside-plan, so it is the normal policy BLOCK path.
    if findings:
        return _blocked(
            request,
            code=str(findings[0].get("code") or "OUT_OF_PLAN_ACTION"),
            reason=str(findings[0].get("detail") or "action differs from the approved plan"),
            next_step="Execute the exact approved step, or create and approve a changed plan.",
            findings=findings,
            action_trace_hash=alignment["action_trace_hash"],
        )

    capability_grant = _grant(request, alignment["action_trace_hash"])
    unavailable = [item for item in request.capability_needs if not item.available]

    if unavailable:
        decision: Decision = "WAITING_PERMISSION"
        allowed = True
        execution_ready = False
        code = "PLAN_AUTHORIZED_CAPABILITY_PENDING"
        next_step = (
            "Provision or resolve the listed capabilities server-side, then execute the same approved step "
            "without asking the user to re-approve it."
        )
    else:
        decision = "ALLOW"
        allowed = True
        execution_ready = True
        code = "PLAN_AUTHORIZED_ACTION"
        next_step = "Execute this exact approved step now, then record evidence and verify the result."

    material = {
        "plan_id": request.plan_id,
        "plan_hash": request.plan_hash,
        "agent_identity": request.agent_identity,
        "action_trace_hash": alignment["action_trace_hash"],
        "decision": decision,
        "capability_scope_hash": capability_grant["scope_hash"],
        "capability_needs": [item.model_dump(mode="json") for item in request.capability_needs],
        "trace_id": request.trace_id,
    }

    return {
        "allowed": allowed,
        "execution_ready": execution_ready,
        "decision": decision,
        "code": code,
        "plan_id": request.plan_id,
        "plan_hash": request.plan_hash,
        "plan_status": request.plan_status,
        "step_id": request.action.step_id,
        "action": request.action.action,
        "target": request.action.target,
        "findings": [],
        "capability_grant": capability_grant,
        "capability_needs": [item.model_dump(mode="json") for item in request.capability_needs],
        "pending_capabilities": [item.model_dump(mode="json") for item in unavailable],
        "control_hash": canonical_hash(material),
        "computed_by": "dsg-decision-core",
        "next_step": next_step,
        "evaluated_at": utc_now(),
    }


def evaluate_execution_trace(
    *,
    plan_id: str,
    plan_hash: str,
    plan_status: str,
    approved_agent_identity: str,
    agent_identity: str,
    actions: list[ObservedAction],
    plan_document: Any,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Validate a completed/observed trace before it becomes an execution record.

    Missing future/required steps are not an out-of-plan mutation; they remain a
    completeness concern for evidence/final verification. Any finding caused by
    an action that differs from the approved scope (including duplicate steps or
    undeclared parameters) is rejected before the execution record is persisted.
    """

    if plan_status != "APPROVED":
        return _trace_block(
            plan_id=plan_id,
            plan_hash=plan_hash,
            plan_status=plan_status,
            agent_identity=agent_identity,
            actions=actions,
            trace_id=trace_id,
            code="PLAN_NOT_APPROVED",
            reason="the referenced plan is not approved and locked",
        )

    if approved_agent_identity != agent_identity:
        return _trace_block(
            plan_id=plan_id,
            plan_hash=plan_hash,
            plan_status=plan_status,
            agent_identity=agent_identity,
            actions=actions,
            trace_id=trace_id,
            code="AGENT_IDENTITY_MISMATCH",
            reason=(
                f"approved plan names agent '{approved_agent_identity}' but the execution reports "
                f"'{agent_identity}'"
            ),
        )

    alignment = evaluate_alignment(plan_document, actions)
    boundary_findings = [
        item for item in alignment["findings"] if item.get("code") != "STEP_NOT_EXECUTED"
    ]
    if boundary_findings:
        first = boundary_findings[0]
        return _trace_block(
            plan_id=plan_id,
            plan_hash=plan_hash,
            plan_status=plan_status,
            agent_identity=agent_identity,
            actions=actions,
            trace_id=trace_id,
            code=str(first.get("code") or "OUT_OF_PLAN_ACTION"),
            reason=str(first.get("detail") or "execution trace differs from the approved plan"),
            findings=boundary_findings,
            action_trace_hash=alignment["action_trace_hash"],
        )

    material = {
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "agent_identity": agent_identity,
        "action_trace_hash": alignment["action_trace_hash"],
        "decision": "ALLOW",
        "trace_id": trace_id,
    }
    return {
        "allowed": True,
        "decision": "ALLOW",
        "code": "PLAN_AUTHORIZED_EXECUTION_TRACE",
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "plan_status": plan_status,
        "action_trace_hash": alignment["action_trace_hash"],
        "findings": [],
        "alignment": alignment,
        "control_hash": canonical_hash(material),
        "computed_by": "dsg-decision-core",
        "next_step": "Persist the execution trace, then collect evidence and verify the result.",
        "evaluated_at": utc_now(),
    }


def _trace_block(
    *,
    plan_id: str,
    plan_hash: str,
    plan_status: str,
    agent_identity: str,
    actions: list[ObservedAction],
    trace_id: str | None,
    code: str,
    reason: str,
    findings: list[dict[str, Any]] | None = None,
    action_trace_hash: str | None = None,
) -> dict[str, Any]:
    material = {
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "agent_identity": agent_identity,
        "actions": [item.model_dump(mode="json") for item in actions],
        "decision": "BLOCK",
        "code": code,
        "trace_id": trace_id,
    }
    return {
        "allowed": False,
        "decision": "BLOCK",
        "code": code,
        "reason": reason,
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "plan_status": plan_status,
        "action_trace_hash": action_trace_hash,
        "findings": findings or [],
        "control_hash": canonical_hash(material),
        "computed_by": "dsg-decision-core",
        "next_step": "Do not persist this trace as an authorized execution; use the approved scope or approve a changed plan.",
        "evaluated_at": utc_now(),
    }


def _blocked(
    request: CorePreflightRequest,
    *,
    code: str,
    reason: str,
    next_step: str,
    findings: list[dict[str, Any]] | None = None,
    action_trace_hash: str | None = None,
) -> dict[str, Any]:
    material = {
        "plan_id": request.plan_id,
        "plan_hash": request.plan_hash,
        "agent_identity": request.agent_identity,
        "step_id": request.action.step_id,
        "action": request.action.action,
        "target": request.action.target,
        "parameters": request.action.parameters,
        "decision": "BLOCK",
        "code": code,
        "trace_id": request.trace_id,
    }
    return {
        "allowed": False,
        "execution_ready": False,
        "decision": "BLOCK",
        "code": code,
        "reason": reason,
        "plan_id": request.plan_id,
        "plan_hash": request.plan_hash,
        "plan_status": request.plan_status,
        "step_id": request.action.step_id,
        "action": request.action.action,
        "target": request.action.target,
        "findings": findings or [],
        "capability_grant": None,
        "capability_needs": [item.model_dump(mode="json") for item in request.capability_needs],
        "pending_capabilities": [],
        "action_trace_hash": action_trace_hash,
        "control_hash": canonical_hash(material),
        "computed_by": "dsg-decision-core",
        "next_step": next_step,
        "evaluated_at": utc_now(),
    }


__all__ = [
    "CapabilityNeed",
    "CorePreflightRequest",
    "Decision",
    "evaluate_execution_trace",
    "evaluate_plan_authorization",
]
