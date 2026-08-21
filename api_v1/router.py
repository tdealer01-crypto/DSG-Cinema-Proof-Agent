"""HTTP surface for the DSG ONE v1 verification flow.

Every write route passes through `reject_agent_verdicts` first: a body that
carries `plan_aligned`, `constraints_pass`, `replay_match` or `verified` is
refused with an explanation, because accepting it would turn independent
verification into a self-report.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from marketplace_verification import POLICY_VERSION, RECEIPT_VERSION
from revenue import api as billing

from . import API_VERSION, ENGINE_VERSION
from .errors import AGENT_ASSERTED_VERDICT_REJECTED, ApiError
from .models import (
    ApprovePlanRequest,
    ConstraintsRequest,
    EvidenceSubmission,
    ExecutionCreate,
    ExecutionVerifyRequest,
    PlanAlignmentRequest,
    PlanDocument,
    find_asserted_verdicts,
)
from . import mcp as mcp_surface
from . import service
from .canonical import utc_now

VERIFIED_EXECUTION_SKU = service.VERIFIED_EXECUTION_SKU


async def reject_agent_verdicts(request: Request) -> None:
    if request.method not in {"POST", "PUT", "PATCH"}:
        return
    raw = await request.body()
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return  # malformed JSON is reported by request validation, not here
    found = find_asserted_verdicts(payload)
    if found:
        raise ApiError(
            422,
            AGENT_ASSERTED_VERDICT_REJECTED,
            "DSG computes verification results; they cannot be supplied by the caller",
            asserted_fields=sorted(found),
        )


router = APIRouter(
    prefix="/api/v1",
    tags=["dsg-one-v1"],
    dependencies=[Depends(reject_agent_verdicts)],
)


def _api_key(header_value: Optional[str]) -> Optional[str]:
    return (header_value or "").strip() or None


def _authorize(api_key: Optional[str]) -> Any:
    """Reject an unusable key up front. Returns the authorization, if metered."""
    return billing.authorize_request(api_key, VERIFIED_EXECUTION_SKU)


async def _backend_state() -> dict[str, Any]:
    import cinema_main

    try:
        status_code, body = await cinema_main.z3_request("GET", "/ready")
    except Exception as exc:  # configuration or transport failure, reported as-is
        detail = getattr(exc, "detail", None) or str(exc)
        return {"configured": False, "ready": False, "detail": detail}
    ready = status_code == 200 and isinstance(body, dict) and body.get("status") == "ready"
    return {
        "configured": True,
        "ready": ready,
        "detail": "exact Z3 verifier is ready" if ready else f"verifier responded HTTP {status_code}",
    }


# -------------------------------------------------------------------- status
@router.get("/status")
async def status() -> dict[str, Any]:
    backend = await _backend_state()
    storage = service.store_summary()
    return {
        "service": "dsg-one",
        "status": "READY" if backend["ready"] else "DEGRADED",
        "api_version": API_VERSION,
        "policy_version": POLICY_VERSION,
        "receipt_version": RECEIPT_VERSION,
        "engine_version": ENGINE_VERSION,
        "verification_backend": backend,
        "storage": storage,
        "independent_verification": service.INDEPENDENT_VERIFICATION,
        "flow": service.flow_definition(),
        "mcp": {
            "endpoint": "/api/v1/mcp",
            "transport": "http-json-rpc",
            "protocol_version": mcp_surface.PROTOCOL_VERSION,
            "tools": mcp_surface.tool_names(),
        },
        "checked_at": utc_now(),
    }


# --------------------------------------------------------------------- plans
@router.post("/plans", status_code=201)
async def create_plan(
    document: PlanDocument,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _authorize(_api_key(x_dsg_api_key))
    return service.create_plan(document)


@router.get("/plans/{plan_id}")
async def read_plan(plan_id: str) -> dict[str, Any]:
    return service.read_plan(plan_id)


@router.post("/plans/{plan_id}/approve")
async def approve_plan(
    plan_id: str,
    request: ApprovePlanRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _authorize(_api_key(x_dsg_api_key))
    return service.approve_plan(plan_id, request)


# ---------------------------------------------------------------- verify legs
@router.post("/verify/plan-alignment")
async def verify_plan_alignment(
    request: PlanAlignmentRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _authorize(_api_key(x_dsg_api_key))
    return service.verify_plan_alignment(request)


@router.post("/verify/constraints")
async def verify_constraints(
    request: ConstraintsRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _authorize(_api_key(x_dsg_api_key))
    return await service.verify_constraints(request)


# ---------------------------------------------------------------- executions
@router.post("/executions", status_code=201)
async def create_execution(
    request: ExecutionCreate,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _authorize(_api_key(x_dsg_api_key))
    return service.record_execution(request)


@router.get("/executions/{execution_id}")
async def read_execution(execution_id: str) -> dict[str, Any]:
    return service.read_execution(execution_id)


@router.post("/executions/{execution_id}/evidence", status_code=201)
async def submit_evidence(
    execution_id: str,
    submission: EvidenceSubmission,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _authorize(_api_key(x_dsg_api_key))
    return service.submit_evidence(execution_id, submission)


@router.post("/executions/{execution_id}/verify")
async def verify_execution(
    execution_id: str,
    request: ExecutionVerifyRequest = Body(default_factory=ExecutionVerifyRequest),
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    authorization = _authorize(_api_key(x_dsg_api_key))
    return await service.verify_execution(
        execution_id,
        request,
        authorization=authorization,
        meter=billing.meter,
    )


# -------------------------------------------------------------------- proofs
@router.get("/proofs/{proof_id}")
async def read_proof(proof_id: str) -> dict[str, Any]:
    return service.read_proof(proof_id)


# ----------------------------------------------------------------------- mcp
@router.post("/mcp")
async def mcp_endpoint(
    message: dict[str, Any] = Body(...),
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> JSONResponse:
    return await mcp_surface.handle_message(message, api_key=_api_key(x_dsg_api_key))


@router.get("/mcp")
async def mcp_transport_hint() -> JSONResponse:
    return JSONResponse(
        status_code=405,
        content={
            "error": "MCP_TRANSPORT_IS_POST",
            "message": "This MCP server speaks JSON-RPC over POST. No SSE stream is offered.",
            "example": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            "protocol_version": mcp_surface.PROTOCOL_VERSION,
        },
    )


# ----------------------------------------------------------------- app wiring
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload())


def install(app: FastAPI) -> None:
    """Mount the v1 API and its refusal vocabulary onto a FastAPI app."""
    app.include_router(router)
    app.add_exception_handler(ApiError, api_error_handler)
