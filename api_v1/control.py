"""Transport-neutral REST adapter for the unified DSG decision core."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header
from pydantic import Field

from revenue import api as billing

from . import service
from .decision_core import CapabilityNeed, CorePreflightRequest, evaluate_plan_authorization
from .models import ObservedAction, Strict

router = APIRouter(prefix="/api/v1/control", tags=["dsg-decision-core"])


class UnifiedPreflightRequest(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    agent_identity: str = Field(min_length=1, max_length=255)
    action: ObservedAction
    capability_needs: list[CapabilityNeed] = Field(default_factory=list, max_length=32)
    channel: str = Field(default="api", min_length=1, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)


def evaluate_unified_preflight(request: UnifiedPreflightRequest) -> dict:
    plan_record = service._require_approved_plan(request.plan_id)
    document = service.plan_document(plan_record)
    core_request = CorePreflightRequest(
        plan_id=plan_record["plan_id"],
        plan_hash=plan_record["plan_hash"],
        plan_status=plan_record["status"],
        approved_agent_identity=document.agent_identity,
        agent_identity=request.agent_identity,
        action=request.action,
        capability_needs=request.capability_needs,
        channel=request.channel,
        trace_id=request.trace_id,
    )
    return evaluate_plan_authorization(request=core_request, plan_document=document)


@router.get("/contract")
async def control_contract() -> dict:
    return {
        "core": "dsg-decision-core",
        "preflight": "POST /api/v1/control/preflight",
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
        "post_execution": ["record_execution", "submit_evidence", "verify", "proof"],
    }


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


__all__ = ["UnifiedPreflightRequest", "evaluate_unified_preflight", "install", "router"]
