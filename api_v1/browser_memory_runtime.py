"""Runtime integration for privacy-minimized Browser Memory.

This layer observes only sanitized browser location metadata after successful
shared-browser actions. It never stores request parameters, form values,
keystrokes, passwords, OTPs, cookies or authorization headers.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Header
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from . import (
    azure_local_browser,
    browser_memory_store as browser_memory,
    browserbase_executor,
    remote_browser,
    remote_pairing,
)
from .models import Strict

router = APIRouter(prefix="/remote-browser/memory", tags=["remote-browser-memory"])


class BrowserMemoryContextRequest(Strict):
    query: str = Field(default="", max_length=1000)
    project_id: Optional[str] = Field(default=None, max_length=100)
    origin: Optional[str] = Field(default=None, max_length=500)
    token_budget: int = Field(default=browser_memory.DEFAULT_ACTIVE_TOKEN_BUDGET, ge=1000, le=browser_memory.MAX_ACTIVE_TOKEN_BUDGET)
    limit: int = Field(default=100, ge=1, le=500)


def _account_hash_from_key(value: Optional[str]) -> str:
    key = remote_pairing._api_key(value)
    account_id = remote_pairing._account_id(key)
    return azure_local_browser.account_digest(account_id)


def _memory_result(account_hash: str, request: BrowserMemoryContextRequest) -> dict[str, Any]:
    return browser_memory.search_context(
        account_hash=account_hash,
        query=request.query,
        project_id=request.project_id,
        origin=request.origin,
        token_budget=request.token_budget,
        limit=request.limit,
    )


@router.post("/context")
async def browser_memory_context(
    request: BrowserMemoryContextRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    account_hash = _account_hash_from_key(x_dsg_api_key)
    return await asyncio.to_thread(_memory_result, account_hash, request)


@router.get("/status")
async def browser_memory_status(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    account_hash = _account_hash_from_key(x_dsg_api_key)
    result = await asyncio.to_thread(
        browser_memory.search_context,
        account_hash=account_hash,
        token_budget=1000,
        limit=1,
    )
    return {
        "available": result.get("available", False),
        "backend": result.get("backend", browser_memory.backend()),
        "stored_memory_count": result.get("stored_memory_count", 0),
        "stored_token_estimate": result.get("stored_token_estimate", 0),
        "active_token_budget_default": browser_memory.DEFAULT_ACTIVE_TOKEN_BUDGET,
        "active_token_budget_max": browser_memory.MAX_ACTIVE_TOKEN_BUDGET,
        "logical_context_target": "supports 1M+ stored tokens; active retrieval remains bounded",
        "privacy": "URL/title/action/provenance only; no raw form values, credentials, cookies or OTPs",
        "truth_boundary": "memory is context, not current authorization or proof",
    }


def _agent_descriptor(session_token: Any, action: Any) -> Optional[dict[str, Any]]:
    if not isinstance(session_token, str) or not isinstance(action, dict):
        return None
    try:
        session = remote_browser._open(session_token)
    except Exception:
        return None
    session_id = str(session.get("sid") or "")
    if not session_id or remote_browser._is_revoked(session_id):
        return None
    binding = browserbase_executor._read_binding(session_id)
    if not binding or binding.get("provider") != azure_local_browser.BACKEND_VALUE:
        return None
    account_hash = binding.get("account_hash")
    if not isinstance(account_hash, str) or not account_hash:
        return None
    kind = str(action.get("kind") or "")[:100]
    controller = str(action.get("controller") or "agent_executor")[:100]
    return {
        "account_hash": account_hash,
        "source": "AGENT_OBSERVED",
        "actor": controller.upper(),
        "action": kind or "browser.action",
        "plan_id": session.get("plan_id"),
        "step_id": session.get("step_id"),
        "project_id": None,
        "importance": 65 if kind == "browser.navigate" else 50,
    }


def _capture_descriptor(path: str, body: Any) -> Optional[dict[str, Any]]:
    if not isinstance(body, dict):
        return None

    # Direct user control. We intentionally skip keystroke/type/scroll events so
    # no user-entered field value can be persisted and the event stream stays
    # operational rather than becoming a surveillance log.
    if path.startswith("/remote-browser/azure/view/") and path.endswith("/action"):
        kind = str(body.get("kind") or "")
        if kind not in {"navigate", "click", "back", "forward", "reload"}:
            return None
        parts = path.split("/")
        if len(parts) < 6:
            return None
        try:
            from . import browserbase_live_ui

            viewer = browserbase_live_ui._load_viewer(parts[4])
        except Exception:
            return None
        account_hash = viewer.get("account_hash")
        if viewer.get("provider") != azure_local_browser.PROVIDER or not isinstance(account_hash, str):
            return None
        return {
            "account_hash": account_hash,
            "source": "USER_OBSERVED",
            "actor": "USER",
            "action": f"user.{kind}",
            "plan_id": None,
            "step_id": None,
            "project_id": None,
            "importance": 60 if kind == "navigate" else 45,
        }

    if path == "/remote-browser/actions":
        return _agent_descriptor(body.get("session_token"), body.get("action"))

    # ChatGPT/MCP path. Inspect only the tool name, sealed session token and action
    # kind. The parameters object is deliberately never copied into memory.
    if path == "/mcp":
        params = body.get("params") or {}
        if not isinstance(params, dict) or params.get("name") != "remote_action":
            return None
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return None
        return _agent_descriptor(arguments.get("session_token"), arguments.get("action"))
    return None


def _latest_page(account_hash: str) -> Optional[dict[str, str]]:
    try:
        metadata = azure_local_browser._read_metadata(account_hash)
    except Exception:
        return None
    pages = metadata.get("last_pages") or []
    if not isinstance(pages, list) or not pages:
        return None
    page = pages[-1]
    if not isinstance(page, dict) or not isinstance(page.get("url"), str):
        return None
    return {
        "url": str(page["url"]),
        "title": str(page.get("title") or "")[:500],
        "logical_browser_id": str(metadata.get("browser_session_id") or f"azure-{account_hash[:24]}"),
    }


def _persist_descriptor(descriptor: dict[str, Any]) -> None:
    page = _latest_page(str(descriptor["account_hash"]))
    if not page:
        return
    browser_memory.record_observation(
        account_hash=str(descriptor["account_hash"]),
        provider=azure_local_browser.PROVIDER,
        logical_browser_id=page["logical_browser_id"],
        url=page["url"],
        title=page["title"],
        source=str(descriptor["source"]),
        actor=str(descriptor["actor"]),
        action=str(descriptor["action"]),
        project_id=descriptor.get("project_id"),
        plan_id=descriptor.get("plan_id"),
        step_id=descriptor.get("step_id"),
        importance=int(descriptor.get("importance", 50)),
    )


class BrowserMemoryCaptureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        descriptor: Optional[dict[str, Any]] = None
        path = request.url.path
        if (
            path == "/remote-browser/actions"
            or path == "/mcp"
            or (path.startswith("/remote-browser/azure/view/") and path.endswith("/action"))
        ):
            try:
                body = await request.json()
                descriptor = _capture_descriptor(path, body)
            except Exception:
                descriptor = None

        response = await call_next(request)
        if descriptor is not None and response.status_code < 400 and browser_memory.configured():
            try:
                await asyncio.to_thread(_persist_descriptor, descriptor)
            except Exception:
                # Long-term memory is intentionally non-authoritative and must
                # never turn an otherwise valid browser action into a failure.
                pass
        return response


async def _mcp_context(args: BrowserMemoryContextRequest) -> dict[str, Any]:
    from . import remote_mcp

    account_hash = _account_hash_from_key(remote_mcp._current_api_key())
    return await asyncio.to_thread(_memory_result, account_hash, args)


async def _mcp_status(_: Any) -> dict[str, Any]:
    from . import remote_mcp

    account_hash = _account_hash_from_key(remote_mcp._current_api_key())
    result = await asyncio.to_thread(browser_memory.search_context, account_hash=account_hash, token_budget=1000, limit=1)
    return {
        "available": result.get("available", False),
        "backend": result.get("backend", browser_memory.backend()),
        "stored_memory_count": result.get("stored_memory_count", 0),
        "stored_token_estimate": result.get("stored_token_estimate", 0),
        "active_token_budget_default": browser_memory.DEFAULT_ACTIVE_TOKEN_BUDGET,
        "active_token_budget_max": browser_memory.MAX_ACTIVE_TOKEN_BUDGET,
        "truth_boundary": "memory is context, not current authorization or proof",
    }


def install_mcp_tools() -> None:
    from . import remote_mcp

    definitions = (
        remote_mcp._Tool(
            "browser_memory_context",
            "Retrieve privacy-minimized long-term shared-browser context. Stored context may exceed 1M tokens, but this tool returns only the relevant bounded token budget. Re-verify live state before high-impact actions.",
            BrowserMemoryContextRequest,
            _mcp_context,
            read_only=True,
            idempotent=True,
            open_world=False,
        ),
        remote_mcp._Tool(
            "browser_memory_status",
            "Inspect Browser Memory availability and approximate stored logical-context size without returning the memories themselves.",
            None,
            _mcp_status,
            read_only=True,
            idempotent=True,
            open_world=False,
        ),
    )
    existing = set(remote_mcp._BY_NAME)
    additions = tuple(tool for tool in definitions if tool.name not in existing)
    if not additions:
        return
    remote_mcp.TOOLS = (*remote_mcp.TOOLS, *additions)
    remote_mcp._BY_NAME.update({tool.name: tool for tool in additions})


def install(app) -> None:
    app.add_middleware(BrowserMemoryCaptureMiddleware)
    app.include_router(router)
    if browser_memory.configured():
        install_mcp_tools()


__all__ = [
    "BrowserMemoryCaptureMiddleware",
    "BrowserMemoryContextRequest",
    "install",
    "install_mcp_tools",
    "router",
]
