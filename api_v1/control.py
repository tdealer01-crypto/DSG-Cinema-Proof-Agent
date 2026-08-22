"""Transport-neutral adapter for the unified DSG decision core."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header
from pydantic import Field

from revenue import api as billing

from . import service
from .capability_broker import (
    CapabilityRequirement,
    capability_status,
    known_capabilities,
    resolve_capabilities,
)
from .decision_core import (
    CorePreflightRequest,
    evaluate_execution_trace,
    evaluate_plan_authorization,
)
from .errors import ApiError
from .models import ExecutionCreate, ObservedAction, Strict

router = APIRouter(prefix="/api/v1/control", tags=["dsg-decision-core"])


class UnifiedPreflightRequest(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    agent_identity: str = Field(min_length=1, max_length=255)
    action: ObservedAction
    required_capabilities: list[CapabilityRequirement] = Field(default_factory=list, max_length=32)
    channel: str = Field(default="api", min_length=1, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)


def evaluate_unified_preflight(request: UnifiedPreflightRequest) -> dict:
    # Read the stored plan without pre-emptively denying draft state. The shared
    # decision core owns the canonical PLAN_NOT_APPROVED -> BLOCK decision.
    plan_record = service.get_plan_record(request.plan_id)
    document = service.plan_document(plan_record)
    resolved = resolve_capabilities(request.required_capabilities)
    core_request = CorePreflightRequest(
        plan_id=plan_record["plan_id"],
        plan_hash=plan_record["plan_hash"],
        plan_status=plan_record["status"],
        approved_agent_identity=document.agent_identity,
        agent_identity=request.agent_identity,
        action=request.action,
        capability_needs=resolved,
        channel=request.channel,
        trace_id=request.trace_id,
    )
    result = evaluate_plan_authorization(request=core_request, plan_document=document)
    result["capability_resolution"] = {
        "source": "server-side-dsg-capability-broker",
        "requested": [item.capability for item in request.required_capabilities],
        "caller_can_assert_availability": False,
        "secrets_exposed": False,
    }
    return result


def record_execution_if_authorized(request: ExecutionCreate) -> dict:
    """Persist an execution only when its observed trace stays inside the plan.

    Both REST and MCP call this boundary. This prevents a client from skipping
    preflight and persisting an out-of-plan trace for later verification.
    """
    plan_record = service.get_plan_record(request.plan_id)
    document = service.plan_document(plan_record)
    control = evaluate_execution_trace(
        plan_id=plan_record["plan_id"],
        plan_hash=plan_record["plan_hash"],
        plan_status=plan_record["status"],
        approved_agent_identity=document.agent_identity,
        agent_identity=request.agent_identity,
        actions=request.actions,
        plan_document=document,
        trace_id=request.trace_id,
    )
    if control["decision"] == "BLOCK":
        raise ApiError(
            409,
            control["code"],
            control.get("reason") or "execution trace is outside the approved plan",
            decision="BLOCK",
            control_hash=control["control_hash"],
            findings=control.get("findings", []),
            plan_id=request.plan_id,
        )

    result = service.record_execution(request)
    result["authorization_control"] = {
        "decision": control["decision"],
        "code": control["code"],
        "control_hash": control["control_hash"],
        "computed_by": control["computed_by"],
    }
    return result


@router.get("/contract")
async def control_contract() -> dict:
    return {
        "core": "dsg-decision-core",
        "preflight": "POST /api/v1/control/preflight",
        "capabilities": {
            "resolver": "server-side-dsg-capability-broker",
            "known": known_capabilities(),
            "caller_declares_requirement_only": True,
            "caller_can_assert_availability": False,
            "status": "/api/v1/control/capabilities",
        },
        "decisions": {
            "ALLOW": "approved exact action; capability is granted and execution may proceed",
            "WAITING_PERMISSION": (
                "approved exact action; policy remains allowed while server-side capability/credential "
                "provisioning is completed"
            ),
            "BLOCK": "action, target, parameter, agent, or plan state is outside the approved plan",
        },
        "invariant": (
            "DSG must not block plan-authorized execution. Missing tools or credentials are provisioning "
            "states, not policy denials."
        ),
        "execution_boundary": (
            "REST and MCP execution recording revalidate the complete observed trace with the same core "
            "before persistence, so preflight cannot be bypassed."
        ),
        "post_execution": ["record_execution", "submit_evidence", "verify", "proof"],
    }


@router.get("/capabilities")
async def capabilities() -> dict:
    return capability_status()


@router.post("/preflight")
async def unified_preflight(
    request: UnifiedPreflightRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    # Transport/account authentication is separate from plan-policy semantics.
    # If paid enforcement is enabled, this validates entitlement; it never turns
    # an approved exact action into an out-of-plan BLOCK.
    billing.authorize_request((x_dsg_api_key or "").strip() or None, service.VERIFIED_EXECUTION_SKU)
    return evaluate_unified_preflight(request)


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "UnifiedPreflightRequest",
    "evaluate_unified_preflight",
    "record_execution_if_authorized",
    "install",
    "router",
]
