"""Public DSG Live transport outside the exact Verification API v1 contract.

DSG Live is a monitor/control transport around the shared Decision Core, not a
new independent-verification operation. Keeping these routes outside `/api/v1`
preserves the exact `openapi/dsg-one-v1.yaml` contract while the existing MCP
transport continues to expose the Live tools through `/api/v1/mcp`.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header

from . import live_monitor

router = APIRouter(prefix="/live/api", tags=["dsg-live"])


@router.get("/contract")
async def live_contract():
    return await live_monitor.live_contract()


@router.post("/sessions")
async def start_live_session(
    request: live_monitor.LiveStartRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
):
    return await live_monitor.start_live_session(request, x_dsg_api_key)


@router.post("/check")
async def live_check(
    request: live_monitor.UnifiedPreflightRequest,
    x_dsg_live_token: str = Header(alias=live_monitor.LIVE_TOKEN_HEADER),
):
    return await live_monitor.live_check(request, x_dsg_live_token)


@router.get("/events")
async def live_events(
    x_dsg_live_token: str = Header(alias=live_monitor.LIVE_TOKEN_HEADER),
    limit: int = 50,
):
    return await live_monitor.live_events(x_dsg_live_token, limit)


@router.post("/mode")
async def live_mode(
    request: live_monitor.LiveModeRequest,
    x_dsg_live_token: str = Header(alias=live_monitor.LIVE_TOKEN_HEADER),
):
    return await live_monitor.live_mode(request, x_dsg_live_token)


def install(app) -> None:
    app.include_router(router)
    live_monitor.install_mcp_tools()


__all__ = ["install", "router"]
