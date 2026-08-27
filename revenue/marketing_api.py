"""Marketing identity and governed revenue-signal endpoints for DSG."""

from __future__ import annotations

from hashlib import sha256
import hmac
import os
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from revenue import api as billing
from .activecampaign_sync import config_from_env
from .marketing_profiles import MarketingProfileStore, store_from_env
from .revenue_pipeline import RevenuePipelineError, get_revenue_pipeline
from .signals import RevenueSignal

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


def _fallback_event_id(*parts: str) -> str:
    material = "\x00".join(parts).encode("utf-8")
    return "client_" + sha256(material).hexdigest()[:40]


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
    event_id: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class LifecycleEventRequest(BaseModel):
    event: Literal[
        "email_click",
        "pricing_visit",
        "demo_requested",
        "trial_started",
        "checkout_started",
        "checkout_abandoned",
    ]
    event_id: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


@router.get("/status")
def marketing_status() -> dict:
    config = config_from_env()
    store = get_store()
    pipeline = get_revenue_pipeline()
    return {
        "activecampaign_configured": config.configured,
        "list_id": config.list_id,
        "account_id_field_id": config.account_id_field_id,
        "profile_store_durable": store.path is not None,
        "profiles": len(store.all()),
        "event_store_durable": bool((os.getenv("DSG_REVENUE_EVENT_STORE") or "").strip()),
        "lifecycle_store_durable": bool(
            (os.getenv("DSG_REVENUE_LIFECYCLE_STORE") or "").strip()
        ),
        "lifecycle_accounts": sum(
            1 for profile in store.all()
            if pipeline.lifecycle.get(profile.account_id) is not None
        ),
        "payment_truth": "signature-verified scoped Stripe invoice.paid evidence only",
        "crm_truth": "downstream projection only; ActiveCampaign cannot grant entitlement",
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
    event_id = request.event_id or _fallback_event_id(
        account.account_id,
        "lead_created",
        request.email.strip().lower(),
        str(bool(request.marketing_consent)),
        profile.source,
    )
    try:
        governed = await get_revenue_pipeline().process_signal(
            account=account,
            profile=profile,
            signal=RevenueSignal.LEAD_CREATED,
            source=profile.source,
            source_event_id=event_id,
            payload={
                "email_hash": sha256(request.email.strip().lower().encode("utf-8")).hexdigest(),
                "marketing_consent": bool(request.marketing_consent),
                "source": profile.source,
            },
            trusted_source=False,
        )
    except RevenuePipelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "profile": profile.public_view(),
        "governed_revenue": governed,
        "marketing_sync": governed.get("marketing_sync"),
    }


@router.post("/event")
async def lifecycle_event(
    request: LifecycleEventRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    account = _require_account(x_dsg_api_key)
    profile = get_store().get(account.account_id)
    source = profile.source if profile else account.channel
    event_id = request.event_id or _fallback_event_id(
        account.account_id,
        request.event,
        source,
    )
    try:
        governed = await get_revenue_pipeline().process_signal(
            account=account,
            profile=profile,
            signal=request.event,
            source=source,
            source_event_id=event_id,
            payload={"signal": request.event},
            trusted_source=False,
        )
    except RevenuePipelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "account_id": account.account_id,
        "governed_revenue": governed,
        "marketing_sync": governed.get("marketing_sync"),
    }


@router.post("/reconcile")
async def reconcile_marketing_projection(
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """Retry downstream CRM projection without promoting lifecycle/payment truth."""

    _require_admin(authorization)
    engine = billing.get_engine()
    store = get_store()
    pipeline = get_revenue_pipeline()
    checked = 0
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

        result = await pipeline.sync_current_projection(
            account=account,
            profile=profile,
            source=profile.source,
        )
        sync = result.get("marketing_sync")
        state = (
            sync.get("sync_state")
            if isinstance(sync, dict)
            else result.get("sync_state", "UNKNOWN")
        )
        if state == "SYNCED":
            synced += 1
        elif state in {
            "PENDING_CONFIGURATION",
            "PENDING_NO_LIFECYCLE",
            "SKIPPED_NO_PROFILE",
            "SKIPPED_NO_CONSENT",
            "SKIPPED_NO_EMAIL",
        }:
            pending += 1
        elif state == "FAILED":
            failed += 1
        results.append(
            {
                "account_id": account.account_id,
                "state": state,
                "lifecycle": result.get("lifecycle"),
            }
        )

    return {
        "checked": checked,
        "synced": synced,
        "pending": pending,
        "failed": failed,
        "results": results,
        "truth_boundary": (
            "reconcile retries ActiveCampaign projection only; "
            "it never creates CUSTOMER or payment proof"
        ),
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
