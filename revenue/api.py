"""HTTP surface for the revenue system and the metering gate used by Cinema.

Default posture is unchanged from the pre-billing service: `/verify/evaluate`
stays publicly callable so the live landing page and marketplace evaluations
keep working. Two things change:

- Presenting an `X-DSG-API-Key` opts a caller into authenticated metering, and
  a bad key is rejected instead of silently served for free.
- Setting `DSG_REVENUE_ENFORCE=1` makes the key mandatory, which is the switch
  that turns evaluation traffic into billable traffic.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .accounts import Account
from .engine import Authorization, RevenueEngine, idempotency_key
from .ledger import ChainError, verify_chain
from .pricing import catalog_snapshot, micros_to_usd_string
from .stripe_sync import (
    SignatureError,
    apply_webhook_event,
    config_from_env,
    push_meter_event,
)

CHECKOUT_STATUS_UNLINKED = "NOT_VERIFIED_NOT_LINKED"
CHECKOUT_STATUS_LINKED = "LINKED"

router = APIRouter(prefix="/billing", tags=["billing"])

_engine: Optional[RevenueEngine] = None


def get_engine() -> RevenueEngine:
    global _engine
    if _engine is None:
        _engine = RevenueEngine.from_env()
    return _engine


def reset_engine(engine: Optional[RevenueEngine] = None) -> RevenueEngine:
    """Replace the process engine. Used by tests and by explicit reconfiguration."""
    global _engine
    _engine = engine if engine is not None else RevenueEngine.from_env()
    return _engine


def _admin_secret() -> str:
    value = (os.getenv("DSG_REVENUE_ADMIN_SECRET") or "").strip()
    if len(value) < 32:
        raise HTTPException(
            status_code=503,
            detail="DSG_REVENUE_ADMIN_SECRET is missing or too short",
        )
    return value


def _require_admin(authorization: Optional[str]) -> None:
    import hmac

    expected = _admin_secret()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid admin token")


def _require_account(api_key: Optional[str]) -> Account:
    account = get_engine().accounts.authenticate(api_key or "")
    if account is None:
        raise HTTPException(status_code=401, detail="a valid X-DSG-API-Key header is required")
    return account


# --------------------------------------------------------------- metering gate
def authorize_request(api_key: Optional[str], sku: str) -> Optional[Authorization]:
    """Authorize a verification request before any solver work is done.

    Returns None when the request is an unmetered public evaluation. Raises
    HTTPException when the caller is denied.
    """
    engine = get_engine()
    presented = (api_key or "").strip()

    if not presented and not engine.enforce:
        return None

    authorization = engine.authorize(presented, sku)
    if not authorization.authorized:
        raise HTTPException(
            status_code=authorization.http_status,
            detail={
                "error": authorization.decision,
                "message": authorization.detail,
                "billing": authorization.summary(),
            },
        )
    return authorization


async def meter(
    authorization: Optional[Authorization],
    *,
    sku: str,
    receipt: dict,
    channel: str = "api",
) -> Optional[dict]:
    """Record a verified receipt as one billable unit.

    Metering never changes the verification outcome: a billing-side failure is
    reported inside the receipt rather than raising over a proof that already
    succeeded.
    """
    if authorization is None or authorization.account is None:
        return None

    engine = get_engine()
    try:
        entry, created = engine.record_usage(
            authorization,
            sku=sku,
            receipt=receipt,
            channel=channel,
        )
    except ValueError as exc:
        return {
            "metered": False,
            "reason": str(exc),
            "account_id": authorization.account.account_id,
            "plan": authorization.account.plan,
            "period": authorization.period,
        }

    config = config_from_env()
    sync = await push_meter_event(
        config,
        stripe_customer_id=authorization.account.stripe_customer_id,
        quantity=entry.quantity,
        identifier=entry.idempotency_key,
    )

    return {
        "metered": True,
        "duplicate": not created,
        "account_id": entry.account_id,
        "plan": authorization.account.plan,
        "period": entry.period,
        "sku": entry.sku,
        "quantity": entry.quantity,
        "unit_price_micros": entry.unit_price_micros,
        "amount_micros": entry.amount_micros,
        "amount_usd": micros_to_usd_string(entry.amount_micros),
        "ledger_sequence": entry.sequence,
        "ledger_entry_hash": entry.entry_hash,
        "stripe_sync": sync,
    }


# -------------------------------------------------------------------- schemas
class IssueAccountRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    plan: str = "free"
    channel: str = "api"
    mode: str = "live"
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255)
    unit_price_micros: Optional[int] = Field(default=None, ge=0, le=10**12)
    hard_cap_units: Optional[int] = Field(default=None, ge=0, le=10**9)


class UpdateAccountRequest(BaseModel):
    plan: Optional[str] = None
    status: Optional[str] = None
    payment_linked: Optional[bool] = None
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255)
    unit_price_micros: Optional[int] = Field(default=None, ge=0, le=10**12)
    hard_cap_units: Optional[int] = Field(default=None, ge=0, le=10**9)


# ------------------------------------------------------------------- endpoints
@router.get("/status")
def billing_status() -> dict:
    """Public, non-secret description of how this deployment can be paid."""
    engine = get_engine()
    config = config_from_env()
    return {
        "billing_version": "dsg-revenue-1.0.0",
        "metering_enabled": True,
        "metering_enforced": engine.enforce,
        "checkout_status": (
            CHECKOUT_STATUS_LINKED if config.linked else CHECKOUT_STATUS_UNLINKED
        ),
        "stripe": config.status(),
        "catalog": catalog_snapshot(),
        "ledger": {
            "entries": engine.ledger.size(),
            "head_hash": engine.ledger.head_hash(),
        },
        "truth_boundary": {
            "supported": [
                "proof-bound metering: only VERIFIED_GLOBAL_OPTIMUM receipts are billable",
                "hash-chained, replayable usage ledger",
                "fail-closed entitlement checks",
            ],
            "not_claimed": [
                "durable multi-replica billing storage",
                "completed Stripe marketplace review",
                "independent financial audit of recognized revenue",
            ],
        },
    }


@router.get("/usage")
def billing_usage(
    period: Optional[str] = None,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    account = _require_account(x_dsg_api_key)
    return get_engine().usage_summary(account, period)


@router.get("/report")
def billing_report(
    period: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_admin(authorization)
    return get_engine().period_report(period)


@router.get("/ledger/verify")
def billing_ledger_verify(authorization: Optional[str] = Header(default=None)) -> dict:
    _require_admin(authorization)
    try:
        return verify_chain(get_engine().ledger.entries())
    except ChainError as exc:
        raise HTTPException(status_code=500, detail=f"ledger chain is broken: {exc}") from exc


@router.post("/accounts", status_code=201)
def create_account(
    request: IssueAccountRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_admin(authorization)
    try:
        account, api_key = get_engine().accounts.issue(
            display_name=request.display_name,
            plan=request.plan,
            channel=request.channel,
            mode=request.mode,
            stripe_customer_id=request.stripe_customer_id,
            unit_price_micros=request.unit_price_micros,
            hard_cap_units=request.hard_cap_units,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "account": account.public_view(),
        "api_key": api_key,
        "notice": "This key is shown once. Store it now; only its hash is retained.",
    }


@router.patch("/accounts/{account_id}")
def update_account(
    account_id: str,
    request: UpdateAccountRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_admin(authorization)
    changes = request.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no updatable fields were supplied")
    try:
        account = get_engine().accounts.update(account_id, **changes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="account not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"account": account.public_view()}


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
) -> dict:
    config = config_from_env()
    payload = await request.body()

    from .stripe_sync import verify_webhook_signature

    try:
        verify_webhook_signature(payload, stripe_signature, config.webhook_secret)
    except SignatureError as exc:
        status = 503 if not config.accepts_webhooks else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    try:
        event: Any = json.loads(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="webhook body is not JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="webhook body is not a JSON object")

    result = apply_webhook_event(event, get_engine().accounts)
    return {"received": True, "event_id": event.get("id"), "result": result}


__all__ = [
    "router",
    "authorize_request",
    "meter",
    "get_engine",
    "reset_engine",
    "idempotency_key",
]
