"""Universal MCP Connect: the same verification flow, spoken as JSON-RPC.

One transport rule and one honesty rule. The transport is plain JSON-RPC 2.0
over POST /api/v1/mcp — no SSE, no session handshake to keep alive. The honesty
rule is the same as the REST surface: every tool takes raw plan, action, and
evidence material, and no tool accepts a verdict. An MCP client cannot reach a
verified receipt except through an exact Z3 proof.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import API_VERSION
from .canonical import canonical_json
from .control import UnifiedPreflightRequest, evaluate_unified_preflight
from .errors import ApiError
from .models import (
    ApprovePlanRequest,
    ConstraintsRequest,
    EvidenceArtifact,
    EvidenceSubmission,
    ExecutionCreate,
    ExecutionVerifyRequest,
    PlanAlignmentRequest,
    PlanDocument,
    Strict,
)
from . import service

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "dsg-one"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class PlanIdArgs(Strict):
    plan_id: str = Field(min_length=1, max_length=64)


class ExecutionIdArgs(Strict):
    execution_id: str = Field(min_length=1, max_length=64)


class ProofIdArgs(Strict):
    proof_id: str = Field(min_length=1, max_length=64)


class ApprovePlanArgs(Strict):
    plan_id: str = Field(min_length=1, max_length=64)
    approver: str = Field(min_length=1, max_length=255)
    plan_hash: str
    approval_note: Optional[str] = Field(default=None, max_length=1024)


class SubmitEvidenceArgs(Strict):
    execution_id: str = Field(min_length=1, max_length=64)
    artifacts: list[EvidenceArtifact] = Field(min_length=1, max_length=256)


class VerifyExecutionArgs(Strict):
    execution_id: str = Field(min_length=1, max_length=64)
    require_content_evidence: bool = True
    note: Optional[str] = Field(default=None, max_length=1024)


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


async def _status(_: Any) -> dict[str, Any]:
    from .router import status as status_route

    return await status_route()


async def _create_plan(args: PlanDocument) -> dict[str, Any]:
    return service.create_plan(args)


async def _read_plan(args: PlanIdArgs) -> dict[str, Any]:
    return service.read_plan(args.plan_id)


async def _approve_plan(args: ApprovePlanArgs) -> dict[str, Any]:
    return service.approve_plan(
        args.plan_id,
        ApprovePlanRequest(
            approver=args.approver,
            plan_hash=args.plan_hash,
            approval_note=args.approval_note,
        ),
    )


async def _preflight_action(args: UnifiedPreflightRequest) -> dict[str, Any]:
    """Use the same decision core as REST/mobile before an MCP executor acts."""
    return evaluate_unified_preflight(args)


async def _plan_alignment(args: PlanAlignmentRequest) -> dict[str, Any]:
    return service.verify_plan_alignment(args)


async def _constraints(args: ConstraintsRequest) -> dict[str, Any]:
    return await service.verify_constraints(args)


async def _record_execution(args: ExecutionCreate) -> dict[str, Any]:
    # This is an audit/evidence operation, not a permission grant. If an executor
    # violated preflight, preserve that raw trace so final verification can prove
    # the violation instead of deleting the evidence.
    return service.record_execution(args)


async def _submit_evidence(args: SubmitEvidenceArgs) -> dict[str, Any]:
    return service.submit_evidence(
        args.execution_id,
        EvidenceSubmission(artifacts=args.artifacts),
    )


async def _verify_execution(args: VerifyExecutionArgs) -> dict[str, Any]:
    from revenue import api as billing

    authorization = billing.authorize_request(_current_api_key(), service.VERIFIED_EXECUTION_SKU)
    return await service.verify_execution(
        args.execution_id,
        ExecutionVerifyRequest(note=args.note, require_content_evidence=args.require_content_evidence),
        authorization=authorization,
        meter=billing.meter,
    )


async def _read_proof(args: ProofIdArgs) -> dict[str, Any]:
    return service.read_proof(args.proof_id)


class _Tool:
    def __init__(
        self,
        name: str,
        description: str,
        model: Optional[type[BaseModel]],
        handler: Callable[[Any], Awaitable[dict[str, Any]]],
    ) -> None:
        self.name = name
        self.description = description
        self.model = model
        self.handler = handler

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": _schema(self.model)
            if self.model is not None
            else {"type": "object", "properties": {}, "additionalProperties": False},
        }


_NO_VERDICTS = (
    " Verdict fields are rejected: submit raw material and read DSG's computed result."
)

TOOLS: tuple[_Tool, ...] = (
    _Tool(
        "dsg_status",
        "Report whether the DSG verification backend and record store are ready. "
        "Call this before any other tool so an outage is never mistaken for a pass.",
        None,
        _status,
    ),
    _Tool(
        "dsg_create_plan",
        "Register the raw plan an agent is asking to run. Returns the plan_id and the "
        "plan_hash DSG computed over the canonical plan." + _NO_VERDICTS,
        PlanDocument,
        _create_plan,
    ),
    _Tool(
        "dsg_read_plan",
        "Read a stored plan, its approval state, and the plan_hash DSG computed.",
        PlanIdArgs,
        _read_plan,
    ),
    _Tool(
        "dsg_approve_plan",
        "Approve and lock a plan. The approver must echo the plan_hash DSG computed, so "
        "an approval always names exactly the text that was reviewed.",
        ApprovePlanArgs,
        _approve_plan,
    ),
    _Tool(
        "dsg_preflight_action",
        "Authorize one exact step through the unified DSG decision core. An approved exact "
        "action is ALLOW; missing server capability is WAITING_PERMISSION without revoking "
        "plan authorization; only work outside the approved plan is BLOCK.",
        UnifiedPreflightRequest,
        _preflight_action,
    ),
    _Tool(
        "dsg_verify_plan_alignment",
        "Compare observed or proposed actions against an approved plan. DSG decides "
        "alignment itself, action by action." + _NO_VERDICTS,
        PlanAlignmentRequest,
        _plan_alignment,
    ),
    _Tool(
        "dsg_verify_constraints",
        "Evaluate policy constraints over observed facts and prove the resulting decision "
        "with exact Z3. Fails closed if the verifier is unreachable." + _NO_VERDICTS,
        ConstraintsRequest,
        _constraints,
    ),
    _Tool(
        "dsg_record_execution",
        "Record the raw observed execution for audit, including violations. Authorization "
        "belongs to dsg_preflight_action before execution; keeping an out-of-plan trace is "
        "required evidence, not permission to perform it." + _NO_VERDICTS,
        ExecutionCreate,
        _record_execution,
    ),
    _Tool(
        "dsg_submit_evidence",
        "Submit evidence artifacts. DSG hashes submitted bytes itself; a declared digest "
        "that disagrees with the content is rejected.",
        SubmitEvidenceArgs,
        _submit_evidence,
    ),
    _Tool(
        "dsg_verify_execution",
        "Recompute alignment, constraints, evidence completeness and replay match from the "
        "stored records, then require an exact Z3 proof before issuing a receipt.",
        VerifyExecutionArgs,
        _verify_execution,
    ),
    _Tool(
        "dsg_get_proof",
        "Read a proof receipt and DSG's recomputation of its receipt_hash.",
        ProofIdArgs,
        _read_proof,
    ),
)

_BY_NAME = {tool.name: tool for tool in TOOLS}

_api_key_var: ContextVar[Optional[str]] = ContextVar("dsg_mcp_api_key", default=None)


def _current_api_key() -> Optional[str]:
    return _api_key_var.get()


def tool_names() -> list[str]:
    return [tool.name for tool in TOOLS]


def _error(message_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def _result(message_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": payload}


def _tool_result(payload: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": canonical_json(payload)}],
        "structuredContent": payload,
        "isError": is_error,
    }


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = _BY_NAME[name]
    if tool.model is None:
        parsed: Any = None
    else:
        try:
            parsed = tool.model.model_validate(arguments)
        except ValidationError as exc:
            return _tool_result(
                {
                    "error": "INVALID_ARGUMENTS",
                    "message": f"arguments for {name} did not match its input schema",
                    "details": exc.errors(include_url=False),
                },
                is_error=True,
            )
    try:
        payload = await tool.handler(parsed)
    except ApiError as exc:
        return _tool_result(exc.payload(), is_error=True)
    return _tool_result(payload)


async def handle_message(message: dict[str, Any], api_key: Optional[str] = None) -> JSONResponse:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return JSONResponse(
            status_code=400,
            content=_error(None, INVALID_REQUEST, "a JSON-RPC 2.0 message is required"),
        )

    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return JSONResponse(
            status_code=400,
            content=_error(message_id, INVALID_PARAMS, "params must be an object"),
        )

    if message_id is None:
        return JSONResponse(status_code=202, content=None)

    if method == "initialize":
        return JSONResponse(
            content=_result(
                message_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": API_VERSION},
                    "instructions": (
                        "Submit raw plans, actions and evidence. Use dsg_preflight_action before "
                        "execution: approved plan work is enabled, missing capability is a provisioning "
                        "state, and only out-of-plan work is blocked. dsg_record_execution preserves "
                        "observed reality for audit even when an executor violated that decision. DSG "
                        "computes verification results and issues a receipt only behind an exact Z3 "
                        "global-optimum proof."
                    ),
                },
            )
        )

    if method == "ping":
        return JSONResponse(content=_result(message_id, {}))

    if method == "tools/list":
        return JSONResponse(
            content=_result(message_id, {"tools": [tool.definition() for tool in TOOLS]})
        )

    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method.startswith("resources") else "prompts"
        return JSONResponse(content=_result(message_id, {key: []}))

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in _BY_NAME:
            return JSONResponse(
                status_code=400,
                content=_error(
                    message_id,
                    INVALID_PARAMS,
                    f"unknown tool '{name}'",
                    {"available_tools": tool_names()},
                ),
            )
        if not isinstance(arguments, dict):
            return JSONResponse(
                status_code=400,
                content=_error(message_id, INVALID_PARAMS, "arguments must be an object"),
            )
        token = _api_key_var.set(api_key)
        try:
            payload = await _call_tool(str(name), arguments)
        finally:
            _api_key_var.reset(token)
        return JSONResponse(content=_result(message_id, payload))

    return JSONResponse(
        status_code=400,
        content=_error(message_id, METHOD_NOT_FOUND, f"unsupported method '{method}'"),
    )
