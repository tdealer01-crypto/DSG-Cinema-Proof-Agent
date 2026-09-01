"""Signed relay route for the Azure-native managed browser executor."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header

from . import azure_managed_executor, remote_relay_security

router = APIRouter(tags=["remote-browser"])


@router.post("/remote-browser/azure/action/{capability_id}")
async def authenticated_azure_action(
    capability_id: str,
    payload: dict[str, Any],
    x_dsg_remote_timestamp: Optional[str] = Header(default=None, alias="X-DSG-Remote-Timestamp"),
    x_dsg_remote_nonce: Optional[str] = Header(default=None, alias="X-DSG-Remote-Nonce"),
    x_dsg_remote_body_sha256: Optional[str] = Header(default=None, alias="X-DSG-Remote-Body-SHA256"),
    x_dsg_remote_signature: Optional[str] = Header(default=None, alias="X-DSG-Remote-Signature"),
) -> dict[str, Any]:
    remote_relay_security._verify_signature(
        payload,
        timestamp=x_dsg_remote_timestamp,
        nonce=x_dsg_remote_nonce,
        body_sha256=x_dsg_remote_body_sha256,
        signature=x_dsg_remote_signature,
    )
    return await azure_managed_executor.azure_action(capability_id, payload)


def install(app) -> None:
    app.include_router(router)


__all__ = ["authenticated_azure_action", "install", "router"]
