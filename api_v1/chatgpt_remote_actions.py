"""Flat REST bridge for ChatGPT Custom Actions over Cinema Remote Browser.

ChatGPT Custom Actions can lose nested JSON-RPC ``params`` metadata when a
single generic /mcp operation is mounted. This adapter intentionally exposes
one REST operation per Remote Browser tool and converts the flat request into
Cinema's existing MCP handler internally. Governance, managed Browserbase
provisioning, plan binding, evidence, and disconnect semantics therefore stay
single-sourced in ``remote_mcp``.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from . import remote_browser, remote_mcp
from .models import Scalar, Strict

router = APIRouter(prefix="/chatgpt-actions/remote-browser", tags=["chatgpt-actions"])


class ChatGPTRemoteAction(Strict):
    """Flatten ``RemoteActionRequest.action`` for reliable Custom Action schemas."""

    session_token: str = Field(min_length=32, max_length=16384)
    kind: remote_browser.RemoteActionKind
    controller: remote_browser.RemoteController = "agent_executor"
    parameters: dict[str, Scalar] = Field(default_factory=dict)

    def as_remote_request(self) -> remote_browser.RemoteActionRequest:
        return remote_browser.RemoteActionRequest(
            session_token=self.session_token,
            action=remote_browser.RemoteAction(
                kind=self.kind,
                controller=self.controller,
                parameters=self.parameters,
            ),
        )


def _authorization_key(
    x_dsg_api_key: Optional[str], authorization: Optional[str]
) -> Optional[str]:
    return remote_mcp._authorization_key(x_dsg_api_key, authorization)


def _public_origin(request: Request) -> Optional[str]:
    try:
        return remote_mcp._request_public_origin(request)
    except HTTPException:
        return None


async def _invoke(
    request: Request,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    x_dsg_api_key: Optional[str],
    authorization: Optional[str],
) -> JSONResponse:
    """Call the canonical MCP handler and unwrap its tool result for REST clients."""

    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    response = await remote_mcp.handle_message(
        message,
        _authorization_key(x_dsg_api_key, authorization),
        public_origin=_public_origin(request),
    )

    try:
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
    except (UnicodeDecodeError, ValueError):
        return JSONResponse(
            status_code=502,
            content={
                "error": "REMOTE_ACTION_BRIDGE_INVALID_RESPONSE",
                "message": "Cinema MCP returned an unreadable response.",
            },
        )

    if response.status_code >= 400:
        return JSONResponse(status_code=response.status_code, content=payload)

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return JSONResponse(
            status_code=502,
            content={
                "error": "REMOTE_ACTION_BRIDGE_INVALID_RESULT",
                "message": "Cinema MCP returned no tool result.",
            },
        )

    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        structured = {}

    if bool(result.get("isError")):
        raw_status = structured.get("status_code")
        status = raw_status if isinstance(raw_status, int) and 400 <= raw_status <= 599 else 400
        return JSONResponse(status_code=status, content=structured)

    return JSONResponse(status_code=200, content=structured)


@router.get("/status", operation_id="cinemaRemoteStatus")
async def remote_status(
    request: Request,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    return await _invoke(
        request,
        tool_name="remote_status",
        arguments={},
        x_dsg_api_key=x_dsg_api_key,
        authorization=authorization,
    )


@router.post("/connect", operation_id="cinemaRemoteAgentConnect")
async def remote_agent_connect(
    body: remote_mcp.ManagedRemoteSessionCreate,
    request: Request,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    return await _invoke(
        request,
        tool_name="remote_agent_connect",
        arguments=body.model_dump(mode="json"),
        x_dsg_api_key=x_dsg_api_key,
        authorization=authorization,
    )


@router.post("/action", operation_id="cinemaRemoteAction")
async def remote_action(
    body: ChatGPTRemoteAction,
    request: Request,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    remote_request = body.as_remote_request()
    return await _invoke(
        request,
        tool_name="remote_action",
        arguments=remote_request.model_dump(mode="json"),
        x_dsg_api_key=x_dsg_api_key,
        authorization=authorization,
    )


@router.post("/disconnect", operation_id="cinemaRemoteDisconnect")
async def remote_disconnect(
    body: remote_browser.RemoteDisconnectRequest,
    request: Request,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    return await _invoke(
        request,
        tool_name="remote_disconnect",
        arguments=body.model_dump(mode="json"),
        x_dsg_api_key=x_dsg_api_key,
        authorization=authorization,
    )


def install(app) -> None:
    app.include_router(router)


__all__ = ["ChatGPTRemoteAction", "install", "router"]
