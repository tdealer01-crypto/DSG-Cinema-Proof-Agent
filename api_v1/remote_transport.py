"""Public transport wrapper for the Cinema Remote Browser execution surface.

The implementation lives in :mod:`api_v1.remote_browser` because it reuses the
v1 Decision Core, but these HTTP routes deliberately live outside `/api/v1`.
`openapi/dsg-one-v1.yaml` is the independent verification contract; remote
browser control is an execution transport and should not change that contract.

The live FastAPI `/openapi.json` still exposes these routes for clients.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header

from . import remote_browser

router = APIRouter(prefix="/remote-browser", tags=["remote-browser"])


@router.get("/contract")
async def contract() -> dict[str, Any]:
    return await remote_browser.contract()


@router.post("/sessions", status_code=201)
async def create_session(
    request: remote_browser.RemoteSessionCreate,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    return await remote_browser.create_session(request, x_dsg_api_key)


@router.post("/actions")
async def execute_action(
    request: remote_browser.RemoteActionRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    return await remote_browser.execute_action(request, x_dsg_api_key)


@router.post("/disconnect")
async def disconnect(
    request: remote_browser.RemoteDisconnectRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    return await remote_browser.disconnect(request, x_dsg_api_key)


def install(app) -> None:
    app.include_router(router)


__all__ = ["install", "router"]
