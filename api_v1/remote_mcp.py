"""MCP action surface for Cinema Remote Browser.

The MCP exposes the plan-bound Remote Browser runtime. For the normal managed
path the client supplies only plan/agent/step intent; Cinema allocates an
ephemeral executor capability and derives its own public executor endpoint. The
managed provider can be Azure-native Chromium or Browserbase and no provider
credential/endpoint is exposed to the user or model.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import API_VERSION
from . import (
    azure_local_browser,
    azure_managed_executor,
    browserbase_executor,
    remote_browser,
    remote_pairing,
    shared_browser,
)
from .canonical import canonical_json
from .models import Strict

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "dsg-cinema-remote"

INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

router = APIRouter(tags=["remote-mcp"])
_api_key_var: ContextVar[Optional[str]] = ContextVar("dsg_remote_mcp_api_key", default=None)
_public_origin_var: ContextVar[Optional[str]] = ContextVar("dsg_remote_mcp_public_origin", default=None)
_agent_name_var: ContextVar[Optional[str]] = ContextVar("dsg_remote_mcp_agent_name", default=None)


class ManagedRemoteSessionCreate(Strict):
    plan_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    agent_identity: Optional[str] = Field(default=None, min_length=1, max_length=255)
    step_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


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


def _current_agent_name() -> Optional[str]:
    return (_agent_name_var.get() or "").strip() or None


def _saved_binding_context() -> dict[str, str]:
    key = _current_api_key()
    if not key:
        return {}
    try:
        account_id = remote_pairing._account_id(key)
        state = remote_pairing._read_state(account_id)
    except HTTPException:
        return {}
    context = {
        "plan_id": str(state.get("last_plan_id") or "").strip(),
        "step_id": str(state.get("last_step_id") or "").strip(),
        "agent_identity": str(state.get("last_agent_identity") or "").strip(),
    }
    return {key: value for key, value in context.items() if value}


def _resolve_binding(args: ManagedRemoteSessionCreate) -> tuple[str, str, str]:
    saved = _saved_binding_context()
    plan_id = (args.plan_id or saved.get("plan_id") or "").strip()
    step_id = (args.step_id or saved.get("step_id") or "").strip()
    agent_identity = (
        args.agent_identity
        or _current_agent_name()
        or saved.get("agent_identity")
        or ""
    ).strip()
    missing = [
        name
        for name, value in (
            ("plan_id", plan_id),
            ("step_id", step_id),
            ("agent_identity", agent_identity),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "REMOTE_BINDING_CONTEXT_REQUIRED",
                "message": (
                    "Cinema automatically reuses a previous approved binding when available. "
                    "For the first bind, the MCP client must use the approved plan context already "
                    "present in the current workflow; do not ask the user to enter plan IDs, step IDs, "
                    "agent names, or executor endpoints."
                ),
                "missing": missing,
            },
        )
    return plan_id, step_id, agent_identity


def _managed_executor():
    if azure_local_browser.configured():
        return azure_managed_executor
    return browserbase_executor


def _managed_path() -> str:
    return "azure" if azure_local_browser.configured() else "browserbase"


def _normalize_public_origin(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="managed browser public origin is invalid") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "MANAGED_BROWSER_PUBLIC_ORIGIN_UNAVAILABLE",
                "message": "Cinema needs a public HTTPS origin for its managed browser executor.",
            },
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=503, detail="managed browser public origin must be a clean HTTPS origin")
    port = parsed.port
    host = parsed.hostname.rstrip(".").lower()
    netloc = host if port in {None, 443} else f"{host}:{port}"
    return f"https://{netloc}"


def _request_public_origin(request: Request) -> str:
    configured = (
        os.getenv("DSG_MANAGED_BROWSER_EXECUTOR_BASE_URL")
        or os.getenv("DSG_BROWSERBASE_EXECUTOR_BASE_URL")
        or os.getenv("DSG_PUBLIC_BASE_URL")
        or ""
    ).strip()
    if configured:
        return _normalize_public_origin(configured)

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    if forwarded_host:
        return _normalize_public_origin(f"{forwarded_proto or 'https'}://{forwarded_host}")

    host = (request.headers.get("host") or request.url.netloc or "").strip()
    if request.url.scheme.lower() == "https" and host:
        return _normalize_public_origin(f"https://{host}")

    raise HTTPException(
        status_code=503,
        detail={
            "error": "MANAGED_BROWSER_PUBLIC_ORIGIN_UNAVAILABLE",
            "message": "Set DSG_PUBLIC_BASE_URL to the public HTTPS Cinema origin.",
        },
    )


async def _remote_contract(_: Any) -> dict[str, Any]:
    value = await remote_browser.contract()
    value["managed_provider"] = {
        "provider": shared_browser.provider(),
        "endpoint_managed_by_cinema": True,
        "user_live_view": True,
        "provider_secret_exposed": False,
        "account_scoped_browser": True,
    }
    value["connection_convenience"] = {
        "pairing_identity_attached": True,
        "previous_binding_reused": True,
        "user_enters_internal_ids": False,
    }
    return value


async def _remote_status(_: Any) -> dict[str, Any]:
    status = await remote_pairing.remote_status(x_dsg_api_key=_current_api_key())
    executor = _managed_executor()
    try:
        shared = await executor.live_view(x_dsg_api_key=_current_api_key())
    except HTTPException:
        shared = {
            "ok": False,
            "provider": shared_browser.provider(),
            "connected": False,
            "live_view_url": None,
        }
    status["shared_browser"] = shared
    paired_agent = _current_agent_name()
    if paired_agent:
        status["paired_agent_identity"] = paired_agent
    previous = _saved_binding_context()
    status["reconnect_available"] = bool(previous.get("plan_id") and previous.get("step_id"))
    if previous:
        status["previous_binding"] = previous
    return status


async def _remote_agent_connect(args: ManagedRemoteSessionCreate) -> dict[str, Any]:
    public_origin = _public_origin_var.get()
    if not public_origin:
        raise HTTPException(status_code=503, detail="managed browser public origin is unavailable")

    plan_id, step_id, agent_identity = _resolve_binding(args)
    executor = _managed_executor()
    capability = executor.allocate_capability(
        plan_id=plan_id,
        step_id=step_id,
        agent_identity=agent_identity,
        ttl_seconds=args.ttl_seconds,
    )
    endpoint = f"{public_origin}/remote-browser/{_managed_path()}/action/{capability}"
    request = remote_browser.RemoteSessionCreate(
        plan_id=plan_id,
        agent_identity=agent_identity,
        step_id=step_id,
        remote_endpoint=endpoint,
        ttl_seconds=args.ttl_seconds,
    )

    created: dict[str, Any] | None = None
    try:
        created = await remote_pairing.agent_connect(request, x_dsg_api_key=_current_api_key())
        executor.finalize_capability(
            capability,
            session_id=str(created["session_id"]),
            plan_hash=str(created["plan_hash"]),
            browser_policy=dict(created.get("browser_policy") or {}),
        )
        shared = await executor.ensure_browser_session(
            str(created["session_id"]),
            plan_hash=str(created["plan_hash"]),
            browser_policy=dict(created.get("browser_policy") or {}),
        )
        created["shared_browser"] = shared
        created["managed_provider"] = str(shared.get("provider") or shared_browser.provider())
        created["endpoint_exposed"] = False
        created["binding_context_reused"] = args.plan_id is None or args.step_id is None or args.agent_identity is None
        return created
    except Exception:
        executor.revoke_capability(capability)
        if created and created.get("session_id"):
            remote_browser._revoke(str(created["session_id"]))
        raise


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
        "Inspect the shared Remote Browser protocol, controller roles, managed provider, concurrency semantics, and plan-bound user-controller delegation rules.",
        None,
        _remote_contract,
        read_only=True,
        idempotent=True,
        open_world=False,
    ),
    _Tool(
        "remote_status",
        "Check whether Remote is armed, whether an agent session is connected, which paired agent identity Cinema already knows, and whether a previous approved binding can be reused automatically.",
        None,
        _remote_status,
        read_only=True,
        idempotent=True,
        open_world=False,
    ),
    _Tool(
        "remote_agent_connect",
        "Bind an already-approved Cinema plan step to the user's managed shared browser. Cinema supplies the paired agent identity and automatically reuses the previous approved plan/step binding when available. For a first bind, use plan_id and step_id from the approved plan context already present in the agent workflow; never ask the user to copy internal IDs, agent names, or endpoints.",
        ManagedRemoteSessionCreate,
        _remote_agent_connect,
        read_only=False,
        idempotent=False,
    ),
    _Tool(
        "remote_action",
        "Execute one action in the approved shared browser session. Use controller=agent_executor for plan-bound mutations, agent_verifier only for extract/screenshot, and user_delegated only for identity operations explicitly delegated by the approved plan. Never send plaintext passwords, OTP values, CAPTCHA responses, passkeys, API keys, or other identity secrets.",
        remote_browser.RemoteActionRequest,
        _remote_action,
        read_only=False,
        idempotent=False,
    ),
    _Tool(
        "remote_disconnect",
        "Revoke all agent remote authority, including delegated user-controller authority, without terminating the user's shared browser context.",
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


async def handle_message(
    message: dict[str, Any],
    api_key: Optional[str],
    *,
    public_origin: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> JSONResponse:
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
                        "Never ask the user to copy or enter plan_id, step_id, agent identity, pairing internals, or executor endpoints. "
                        "Pairing supplies the agent identity automatically, and Cinema reuses the previous approved binding on reconnect. "
                        "For the first bind, use plan_id and step_id from the approved plan context already present in the current agent workflow. "
                        "Cinema provisions the account shared browser and endpoint automatically. Then use remote_action without a per-click approval cycle while remaining inside the approved plan. "
                        "The user, executor, and read-only verifier share one browser. Never send plaintext password/OTP/CAPTCHA/passkey/API-key values through tools."
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
        api_token = _api_key_var.set(api_key)
        origin_token = _public_origin_var.set(public_origin)
        agent_token = _agent_name_var.set((agent_name or "").strip() or None)
        try:
            payload = await _call_tool(str(name), arguments)
        finally:
            _agent_name_var.reset(agent_token)
            _public_origin_var.reset(origin_token)
            _api_key_var.reset(api_token)
        return JSONResponse(content=_result(message_id, payload))

    return JSONResponse(status_code=400, content=_error(message_id, METHOD_NOT_FOUND, f"unsupported method '{method}'"))


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_dsg_agent_name: Optional[str] = Header(default=None, alias="X-DSG-Agent-Name"),
) -> JSONResponse:
    try:
        message = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=_error(None, INVALID_REQUEST, "request body must be JSON"))
    api_key = _authorization_key(x_dsg_api_key, authorization)
    try:
        public_origin = _request_public_origin(request)
    except HTTPException:
        public_origin = None
    return await handle_message(
        message,
        api_key,
        public_origin=public_origin,
        agent_name=x_dsg_agent_name,
    )


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "ManagedRemoteSessionCreate",
    "PROTOCOL_VERSION",
    "handle_message",
    "install",
    "router",
    "tool_names",
]