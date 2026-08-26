"""MCP action surface for Cinema Remote Browser.

This transport intentionally lives at /mcp, outside the independent verification
/api/v1 contract. It exposes the already-proven chat-driven pairing and remote
action runtime as MCP tools so ChatGPT-compatible MCP clients can use the user's
armed shared Remote Browser as an execution surface.

The MCP never accepts plaintext identity secrets. If the approved plan delegates
the user's controller, the agent may request narrowly-scoped identity operations
using opaque secret/OTP references that the trusted remote executor resolves.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from fastapi import HTTPException

from . import API_VERSION
from . import remote_browser, remote_pairing
from .canonical import canonical_json

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "dsg-cinema-remote"

INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

router = APIRouter(tags=["remote-mcp"])
_api_key_var: ContextVar[Optional[str]] = ContextVar("dsg_remote_mcp_api_key", default=None)


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    value = model.model_json_schema()
    value.pop("title", None)
    return value


def _authorization_key(x_dsg_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    direct = (x_dsg_api_key or "").strip()
    if direct:
        return direct
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip() or None
    return None


def _current_api_key() -> Optional[str]:
    return _api_key_var.get()


async def _remote_contract(_: Any) -> dict[str, Any]:
    return await remote_browser.contract()


async def _remote_status(_: Any) -> dict[str, Any]:
    return await remote_pairing.remote_status(x_dsg_api_key=_current_api_key())


async def _remote_agent_connect(args: remote_browser.RemoteSessionCreate) -> dict[str, Any]:
    return await remote_pairing.agent_connect(args, x_dsg_api_key=_current_api_key())


async def _remote_action(args: remote_browser.RemoteActionRequest) -> dict[str, Any]:
    return await remote_browser.execute_action(args, x_dsg_api_key=_current_api_key())


async def _remote_disconnect(args: remote_browser.RemoteDisconnectRequest) -> dict[str, Any]:
    return await remote_browser.disconnect(args, x_dsg_api_key=_current_api_key())


class _Tool:
    def __init__(
        self,
        name: str,
        description: str,
        model: Optional[type[BaseModel]],
        handler,
        *,
        read_only: bool,
        destructive: bool = False,
        idempotent: bool = False,
        open_world: bool = True,
    ) -> None:
        self.name = name
        self.description = description
        self.model = model
        self.handler = handler
        self.annotations = {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": idempotent,
            "openWorldHint": open_world,
        }

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": _schema(self.model)
            if self.model is not None
            else {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": self.annotations,
        }


TOOLS: tuple[_Tool, ...] = (
    _Tool(
        "remote_contract",
        "Use this when you need to inspect the shared Remote Browser protocol, controller roles, concurrency semantics, and plan-bound user-controller delegation rules.",
        None,
        _remote_contract,
        read_only=True,
        idempotent=True,
        open_world=False,
    ),
    _Tool(
        "remote_status",
        "Use this when you need to check whether the user has armed Remote and whether an agent session is connected.",
        None,
        _remote_status,
        read_only=True,
        idempotent=True,
        open_world=False,
    ),
    _Tool(
        "remote_agent_connect",
        "Use this when the user has already turned Remote ON and the agent needs to bind an approved Cinema plan step to one live shared browser endpoint. Any user-controller delegation is derived from that approved plan step; do not invent or widen it at connection time.",
        remote_browser.RemoteSessionCreate,
        _remote_agent_connect,
        read_only=False,
        idempotent=False,
    ),
    _Tool(
        "remote_action",
        "Execute one action in the approved shared browser session. Use controller=agent_executor for plan-bound mutations, agent_verifier only for extract/screenshot, and user_delegated only for identity operations explicitly delegated by the approved plan. Never send plaintext passwords, OTP values, CAPTCHA responses, passkeys, API keys, or other identity secrets; delegated identity actions use opaque secret_ref/otp_ref handles.",
        remote_browser.RemoteActionRequest,
        _remote_action,
        read_only=False,
        idempotent=False,
    ),
    _Tool(
        "remote_disconnect",
        "Use this when all agent remote authority, including delegated user-controller authority, must be revoked without terminating the user's browser session.",
        remote_browser.RemoteDisconnectRequest,
        _remote_disconnect,
        read_only=False,
        destructive=True,
        idempotent=True,
        open_world=False,
    ),
)

_BY_NAME = {tool.name: tool for tool in TOOLS}


def tool_names() -> list[str]:
    return [tool.name for tool in TOOLS]


def _error(message_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": payload}


def _result(message_id: Any, payload: Any) -> dict[str, Any]:
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
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return _tool_result(
            {"error": "REMOTE_TOOL_FAILED", "status_code": exc.status_code, **detail},
            is_error=True,
        )
    return _tool_result(payload)


async def handle_message(message: dict[str, Any], api_key: Optional[str]) -> JSONResponse:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return JSONResponse(status_code=400, content=_error(None, INVALID_REQUEST, "a JSON-RPC 2.0 message is required"))

    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return JSONResponse(status_code=400, content=_error(message_id, INVALID_PARAMS, "params must be an object"))
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
                        "The user controls Remote ON/OFF in Cinema. Check remote_status first. "
                        "When Remote is armed, bind an approved plan step with remote_agent_connect, "
                        "then use remote_action without a per-click approval cycle while remaining inside "
                        "the approved plan. The user, executor, and read-only verifier share one live browser. "
                        "Never send plaintext password/OTP/CAPTCHA/passkey/API-key values through tools. "
                        "Only when the approved plan explicitly shares the user controller may the agent use "
                        "user_delegated identity actions with opaque secret_ref/otp_ref handles."
                    ),
                },
            )
        )
    if method == "ping":
        return JSONResponse(content=_result(message_id, {}))
    if method == "tools/list":
        return JSONResponse(content=_result(message_id, {"tools": [tool.definition() for tool in TOOLS]}))
    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method.startswith("resources") else "prompts"
        return JSONResponse(content=_result(message_id, {key: []}))
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in _BY_NAME:
            return JSONResponse(
                status_code=400,
                content=_error(message_id, INVALID_PARAMS, f"unknown tool '{name}'", {"available_tools": tool_names()}),
            )
        if not isinstance(arguments, dict):
            return JSONResponse(status_code=400, content=_error(message_id, INVALID_PARAMS, "arguments must be an object"))
        token = _api_key_var.set(api_key)
        try:
            payload = await _call_tool(str(name), arguments)
        finally:
            _api_key_var.reset(token)
        return JSONResponse(content=_result(message_id, payload))

    return JSONResponse(status_code=400, content=_error(message_id, METHOD_NOT_FOUND, f"unsupported method '{method}'"))


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    try:
        message = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=_error(None, INVALID_REQUEST, "request body must be JSON"))
    api_key = _authorization_key(x_dsg_api_key, authorization)
    return await handle_message(message, api_key)


def install(app) -> None:
    app.include_router(router)


__all__ = ["PROTOCOL_VERSION", "install", "router", "tool_names", "handle_message"]
