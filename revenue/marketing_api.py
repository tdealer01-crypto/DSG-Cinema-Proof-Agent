"""Marketing identity and lifecycle endpoints for DSG revenue.

These routes never grant entitlement. Payment/customer transitions are emitted
only by reconciliation against billing accounts that contain signed Stripe
invoice evidence.
"""

from __future__ import annotations

import hmac
import os
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from revenue import api as billing
from .activecampaign_sync import (
    EVENT_CHECKOUT_ABANDONED,
    EVENT_CHECKOUT_STARTED,
    EVENT_DEMO_REQUESTED,
    EVENT_LEAD,
    EVENT_PAYMENT_CONFIRMED,
    EVENT_TRIAL_STARTED,
    config_from_env,
    sync_account_event,
)
from .marketing_profiles import MarketingProfileStore, store_from_env

router = APIRouter(prefix="/billing/marketing", tags=["billing", "marketing"])

_store: Optional[MarketingProfileStore] = None
_store_path: Optional[str] = None


def get_store() -> MarketingProfileStore:
    global _store, _store_path
    path = (os.getenv("DSG_MARKETING_PROFILE_STORE") or "").strip() or None
    if _store is None or _store_path != path:
        _store = store_from_env()
        _store_path = path
    return _store


def reset_store(store: Optional[MarketingProfileStore] = None) -> MarketingProfileStore:
    global _store, _store_path
    _store = store if store is not None else store_from_env()
    _store_path = _store.path
    return _store


def _require_account(api_key: Optional[str]):
    account = billing.get_engine().accounts.authenticate((api_key or "").strip())
    if account is None:
        raise HTTPException(
            status_code=401,
            detail="a valid X-DSG-API-Key header is required",
        )
    return account


def _require_admin(authorization: Optional[str]) -> None:
    expected = (os.getenv("DSG_REVENUE_ADMIN_SECRET") or "").strip()
    if len(expected) < 32:
        raise HTTPException(
            status_code=503,
            detail="DSG_REVENUE_ADMIN_SECRET is missing or too short",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid admin token")


class IdentifyRequest(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    marketing_consent: bool = False
    source: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]*$",
    )


class LifecycleEventRequest(BaseModel):
    event: Literal[
        "demo_requested",
        "trial_started",
        "checkout_started",
        "checkout_abandoned",
    ]


@router.get("/status")
def marketing_status() -> dict:
    config = config_from_env()
    store = get_store()
    return {
        "activecampaign_configured": config.configured,
        "list_id": config.list_id,
        "account_id_field_id": config.account_id_field_id,
        "profile_store_durable": store.path is not None,
        "profiles": len(store.all()),
        "payment_truth": "signed Stripe invoice evidence only",
    }


@router.post("/identify")
async def identify(
    request: IdentifyRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    account = _require_account(x_dsg_api_key)
    profile = get_store().upsert(
        account_id=account.account_id,
        email=request.email,
        marketing_consent=request.marketing_consent,
        source=request.source or account.channel,
    )
    sync = await sync_account_event(
        account,
        profile,
        event=EVENT_LEAD,
        source=profile.source,
    )
    return {
        "profile": profile.public_view(),
        "marketing_sync": sync,
    }


@router.post("/event")
async def lifecycle_event(
    request: LifecycleEventRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    account = _require_account(x_dsg_api_key)
    profile = get_store().get(account.account_id)
    sync = await sync_account_event(
        account,
        profile,
        event=request.event,
        source=profile.source if profile else account.channel,
    )
    return {
        "account_id": account.account_id,
        "marketing_sync": sync,
    }


@router.post("/reconcile")
async def reconcile_paid_customers(
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """Promote marketing lifecycle only from recorded signed Stripe invoices.

    ``payment_linked`` alone is insufficient because a trialing subscription can
    be linked without paid revenue. At least one scoped ``invoice.paid`` id must
    already exist on the DSG account before customer/onboarding tags are emitted.
    """
    _require_admin(authorization)
    engine = billing.get_engine()
    store = get_store()
    checked = 0
    eligible = 0
    synced = 0
    pending = 0
    failed = 0
    results: list[dict] = []

    for profile in store.all():
        checked += 1
        account = engine.accounts.get(profile.account_id)
        if account is None:
            results.append(
                {
                    "account_id": profile.account_id,
                    "state": "ORPHANED_PROFILE",
                }
            )
            continue
        if not account.stripe_paid_invoice_ids:
            continue
        eligible += 1
        sync = await sync_account_event(
            account,
            profile,
            event=EVENT_PAYMENT_CONFIRMED,
            source=profile.source,
        )
        state = sync.get("sync_state")
        if state == "SYNCED":
            synced += 1
        elif state in {"PENDING_CONFIGURATION", "SKIPPED_NO_PROFILE"}:
            pending += 1
        elif state == "FAILED":
            failed += 1
        results.append(
            {
                "account_id": account.account_id,
                "state": state,
            }
        )

    return {
        "checked": checked,
        "eligible_from_paid_invoice": eligible,
        "synced": synced,
        "pending": pending,
        "failed": failed,
        "results": results,
    }


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "router",
    "install",
    "get_store",
    "reset_store",
    "IdentifyRequest",
    "LifecycleEventRequest",
]
