"""Public DSG Live transport outside the exact Verification API v1 contract.

DSG Live is a monitor/control transport around the shared Decision Core, not a
new independent-verification operation. Keeping these routes outside `/api/v1`
preserves the exact `openapi/dsg-one-v1.yaml` contract while the existing MCP
transport continues to expose the Live tools through `/api/v1/mcp`.

Onboarding deliberately separates observation from control:

- OBSERVE may start without a DSG API key so a new user can see first value.
- ENFORCE always requires a valid DSG account/API key before the mode switch.
- Verified proof issuance keeps the existing metering/entitlement gate unchanged.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from revenue import api as billing

from . import live_monitor, service

router = APIRouter(prefix="/live/api", tags=["dsg-live"])


def _optional_account_id(api_key: Optional[str]) -> str | None:
    """Validate an optional key and return its account id.

    No key is a valid anonymous OBSERVE onboarding state. A presented but invalid
    key is never silently downgraded to anonymous access.
    """
    presented = (api_key or "").strip()
    if not presented:
        return None
    authorization = billing.authorize_request(presented, service.VERIFIED_EXECUTION_SKU)
    if authorization is None or authorization.account is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "DSG_ACCOUNT_REQUIRED",
                "message": "A valid DSG account is required for authenticated Live control.",
            },
        )
    return authorization.account.account_id


def _require_enforce_account(api_key: Optional[str]) -> str:
    presented = (api_key or "").strip()
    if not presented:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "DSG_ACCOUNT_REQUIRED",
                "message": "Observe is available without an API key. Enable Enforce only after authenticating a DSG account.",
                "next_step": "Activate or use a DSG account, then retry with X-DSG-API-Key.",
            },
        )
    account_id = _optional_account_id(presented)
    assert account_id is not None
    return account_id


@router.get("/contract")
async def live_contract():
    contract = await live_monitor.live_contract()
    contract["onboarding"] = {
        "anonymous_observe": True,
        "enforce_requires_account": True,
        "verified_proof_requires_entitlement": True,
    }
    return contract


@router.post("/sessions")
async def start_live_session(
    request: live_monitor.LiveStartRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
):
    account_id = _optional_account_id(x_dsg_api_key)
    return live_monitor.create_live_session(request, account_id=account_id)


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
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
):
    if request.mode == "enforce":
        _require_enforce_account(x_dsg_api_key)
    return live_monitor.set_live_mode(x_dsg_live_token, request.mode)


async def _mcp_public_live_start(args: live_monitor.LiveStartRequest):
    """Start Live from an Agent Plugin without forcing account setup first."""
    from . import mcp

    account_id = _optional_account_id(mcp._current_api_key())
    return live_monitor.create_live_session(args, account_id=account_id)


def install(app) -> None:
    app.include_router(router)
    live_monitor.install_mcp_tools()

    # `install_mcp_tools()` registers the canonical tool schema. Replace only the
    # start handler so plugin clients get anonymous OBSERVE onboarding while the
    # rest of the Live/decision implementation remains exactly the same.
    from . import mcp

    start_tool = mcp._BY_NAME.get("dsg_live_start")
    if start_tool is not None:
        start_tool.handler = _mcp_public_live_start


__all__ = ["install", "router"]
