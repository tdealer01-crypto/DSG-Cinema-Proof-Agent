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

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .accounts import Account
from .activation import ActivationService, activation_ref
from .engine import (
    Authorization,
    EntitlementChangedError,
    RevenueEngine,
    idempotency_key,
)
from .ledger import ChainError, QuotaExceededError, verify_chain
from .pricing import catalog_snapshot, get_plan, micros_to_usd_string
from .remediation import (
    ACCOUNT_SUSPENDED,
    BACKEND_UNAVAILABLE,
    BILLING_STORAGE_NOT_READY,
    CONFIGURATION_INCOMPLETE,
    METERING_REFUSED,
    PAYMENT_NOT_LINKED,
    QUOTA_EXCEEDED,
    UNKNOWN_KEY,
    VERIFICATION_NOT_PROVED,
    remediation_for,
)
from .stripe_sync import (
    SignatureError,
    apply_webhook_event,
    config_from_env,
    push_meter_event,
    verify_operational_link,
)

CHECKOUT_STATUS_UNLINKED = "NOT_VERIFIED_NOT_LINKED"
CHECKOUT_STATUS_LINKED = "LINKED"

router = APIRouter(prefix="/billing", tags=["billing"])

_engine: Optional[RevenueEngine] = None
_activation: Optional[ActivationService] = None


def get_engine() -> RevenueEngine:
    global _engine
    if _engine is None:
        _engine = RevenueEngine.from_env()
    return _engine


def get_activation() -> ActivationService:
    global _activation
    engine = get_engine()
    if _activation is None or _activation.accounts is not engine.accounts:
        _activation = ActivationService.from_env(engine.accounts)
    return _activation


def reset_engine(engine: Optional[RevenueEngine] = None) -> RevenueEngine:
    """Replace the process engine. Used by tests and by explicit reconfiguration."""
    global _engine, _activation
    _engine = engine if engine is not None else RevenueEngine.from_env()
    _activation = None
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

    if engine.enforcement_requested and not engine.enforcement_ready:
        raise HTTPException(
            status_code=503,
            detail={
                "error": BILLING_STORAGE_NOT_READY,
                "message": "paid enforcement was requested without safe durable storage",
                "blockers": list(engine.enforcement_blockers),
                "remediation": remediation_for(BILLING_STORAGE_NOT_READY).to_dict(),
            },
        )

    if not presented and not engine.enforce:
        return None

    authorization = engine.authorize(presented, sku)
    if not authorization.authorized:
        raise HTTPException(
            status_code=authorization.http_status,
            detail={
                "error": authorization.decision,
                "message": authorization.detail,
                "remediation": authorization.remediation.to_dict(),
                "billing": authorization.summary(),
            },
        )
    return authorization


def authorize_account(account_id: str, sku: str) -> Authorization:
    """Authorize an account whose Stripe App request was already verified.

    A signed Stripe request identifies an install without exposing a DSG API
    key to the sandboxed UI. Storage readiness and every entitlement condition
    remain identical to the API-key path.
    """
    engine = get_engine()
    if engine.enforcement_requested and not engine.enforcement_ready:
        raise HTTPException(
            status_code=503,
            detail={
                "error": BILLING_STORAGE_NOT_READY,
                "message": "paid enforcement was requested without safe durable storage",
                "blockers": list(engine.enforcement_blockers),
                "remediation": remediation_for(BILLING_STORAGE_NOT_READY).to_dict(),
            },
        )

    authorization = engine.authorize_account(account_id, sku)
    if not authorization.authorized:
        raise HTTPException(
            status_code=authorization.http_status,
            detail={
                "error": authorization.decision,
                "message": authorization.detail,
                "remediation": authorization.remediation.to_dict(),
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

    A proof is released only after its local billing record is durable for this
    process. If entitlement changes during solver work, fail closed instead of
    returning an authenticated proof for free.
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
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "QUOTA_EXCEEDED",
                "message": str(exc),
                "remediation": remediation_for(QUOTA_EXCEEDED).to_dict(),
                "billing": authorization.summary(),
            },
        ) from exc
    except EntitlementChangedError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={
                "error": exc.decision,
                "message": str(exc),
                "remediation": remediation_for(exc.decision).to_dict(),
                "billing": authorization.summary(),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": METERING_REFUSED,
                "message": str(exc),
                "remediation": remediation_for(METERING_REFUSED).to_dict(),
                "billing": authorization.summary(),
            },
        ) from exc

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


def diagnose_entitlement(api_key: Optional[str], sku: str) -> dict:
    """Report a caller's identity and entitlement as support checks.

    Returns the checks, the blocking code if any, and a non-secret billing
    summary. A missing key is not an error here: when enforcement is off, an
    anonymous caller is genuinely entitled to unmetered public evaluation.
    """
    engine = get_engine()
    presented = (api_key or "").strip()
    checks: list[dict] = []

    if engine.enforcement_requested and not engine.enforcement_ready:
        checks.append(
            {
                "check": "billing_storage",
                "status": "fail",
                "detail": "; ".join(engine.enforcement_blockers),
            }
        )
        return {
            "checks": checks,
            "blocking": BILLING_STORAGE_NOT_READY,
            "billing": None,
        }

    if not presented:
        if engine.enforce:
            checks.append(
                {
                    "check": "api_key",
                    "status": "fail",
                    "detail": "This deployment requires an API key and none was presented",
                }
            )
            return {"checks": checks, "blocking": UNKNOWN_KEY, "billing": None}
        checks.append(
            {
                "check": "api_key",
                "status": "skip",
                "detail": "No key presented; public evaluation is unmetered on this deployment",
            }
        )
        checks.append(
            {
                "check": "entitlement",
                "status": "pass",
                "detail": "Anonymous public evaluation is currently allowed",
            }
        )
        return {"checks": checks, "blocking": None, "billing": None}

    authorization = engine.authorize(presented, sku)
    if authorization.decision == UNKNOWN_KEY:
        checks.append(
            {
                "check": "api_key",
                "status": "fail",
                "detail": "The presented key is malformed or does not match an account",
            }
        )
        return {"checks": checks, "blocking": UNKNOWN_KEY, "billing": None}

    checks.append(
        {"check": "api_key", "status": "pass", "detail": "Key matches an account"}
    )

    account = authorization.account
    assert account is not None
    summary = authorization.summary()

    if authorization.decision == ACCOUNT_SUSPENDED:
        checks.append(
            {"check": "account_status", "status": "fail", "detail": "Account is not active"}
        )
        return {"checks": checks, "blocking": ACCOUNT_SUSPENDED, "billing": summary}

    checks.append(
        {"check": "account_status", "status": "pass", "detail": f"Account is {account.status}"}
    )

    if authorization.decision == QUOTA_EXCEEDED:
        checks.append(
            {
                "check": "quota",
                "status": "fail",
                "detail": (
                    f"{authorization.units_used} units used in {authorization.period}; "
                    "the plan cap is reached"
                ),
            }
        )
        return {"checks": checks, "blocking": QUOTA_EXCEEDED, "billing": summary}

    remaining = (
        "uncapped"
        if authorization.units_remaining is None
        else f"{authorization.units_remaining} remaining"
    )
    checks.append(
        {
            "check": "quota",
            "status": "pass",
            "detail": f"{authorization.units_used} used in {authorization.period}, {remaining}",
        }
    )

    if authorization.decision == PAYMENT_NOT_LINKED:
        checks.append(
            {
                "check": "paid_entitlement",
                "status": "fail",
                "detail": (
                    "The plan requires a linked payment method and, where it has "
                    "a base price, a scoped paid invoice for the current period"
                ),
            }
        )
        return {"checks": checks, "blocking": PAYMENT_NOT_LINKED, "billing": summary}

    checks.append(
        {
            "check": "paid_entitlement",
            "status": "pass" if account.payment_linked else "skip",
            "detail": (
                "Current paid entitlement is confirmed"
                if account.payment_linked
                else "No payment method needed while included units remain"
            ),
        }
    )
    return {"checks": checks, "blocking": None, "billing": summary}


# -------------------------------------------------------------------- schemas
class IssueAccountRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    plan: str = "free"
    channel: str = "api"
    mode: str = "live"
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255)
    unit_price_micros: Optional[int] = Field(default=None, ge=0, le=10**12)
    hard_cap_units: Optional[int] = Field(default=None, ge=0, le=10**9)


class ActivateRequest(BaseModel):
    """Self-serve activation: the only way to get a key without an operator."""

    channel: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    activation_id: str = Field(min_length=3, max_length=200)
    display_name: str = Field(min_length=1, max_length=255)


class UpdateAccountRequest(BaseModel):
    plan: Optional[str] = None
    status: Optional[str] = None
    payment_linked: Optional[bool] = None
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255)
    unit_price_micros: Optional[int] = Field(default=None, ge=0, le=10**12)
    hard_cap_units: Optional[int] = Field(default=None, ge=0, le=10**9)


# ------------------------------------------------------------------- endpoints
@router.get("/status")
async def billing_status() -> dict:
    """Public, non-secret description of how this deployment can be paid."""
    engine = get_engine()
    config = config_from_env()
    operational = await verify_operational_link(config)
    stripe_status = config.status(operational)
    return {
        "billing_version": "dsg-revenue-1.1.0",
        "metering_enabled": True,
        "metering_enforced": engine.enforce,
        "enforcement_requested": engine.enforcement_requested,
        "enforcement_ready": engine.enforcement_ready,
        "enforcement_blockers": list(engine.enforcement_blockers),
        "checkout_status": (
            CHECKOUT_STATUS_LINKED
            if stripe_status["charges_enabled"]
            else CHECKOUT_STATUS_UNLINKED
        ),
        "stripe": stripe_status,
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


@router.get("/subscription")
def billing_subscription(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    account = _require_account(x_dsg_api_key)
    github_billed = account.channel == "github_marketplace"
    billing_channel = "github_marketplace" if github_billed else "stripe"
    can_manage = (
        not github_billed
        and account.mode == "live"
        and account.stripe_customer_id is not None
    )
    return {
        "account_id": account.account_id,
        "plan": account.plan,
        "billing_channel": billing_channel,
        "payment_linked": account.payment_linked,
        "subscription_active": (
            account.plan not in {"github_free"}
            and account.status == "active"
            if github_billed
            else account.status == "active"
            and account.payment_linked
            and account.stripe_subscription_id is not None
        ),
        "can_manage_in_portal": can_manage,
        "portal_endpoint": "/billing/portal/session" if can_manage else None,
    }


@router.get("/usage/history/{sequence}")
def billing_usage_history_detail(
    sequence: int,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    account = _require_account(x_dsg_api_key)
    entry = get_engine().ledger.find_account_entry(account.account_id, sequence)
    if entry is None:
        raise HTTPException(status_code=404, detail="proof usage entry not found")
    return {
        "sequence": entry.sequence,
        "period": entry.period,
        "channel": entry.channel,
        "sku": entry.sku,
        "quantity": entry.quantity,
        "amount_micros": entry.amount_micros,
        "proof_hash": entry.proof_hash,
        "context_hash": entry.context_hash,
        "recorded_at": entry.recorded_at,
        "entry_hash": entry.entry_hash,
    }


@router.get("/usage/history")
def billing_usage_history(
    limit: int = Query(default=20, ge=1, le=100),
    before_sequence: Optional[int] = Query(default=None, ge=1),
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict:
    account = _require_account(x_dsg_api_key)
    entries = get_engine().ledger.account_entries_before(
        account.account_id,
        before_sequence=before_sequence,
        limit=limit + 1,
    )
    has_more = len(entries) > limit
    selected = entries[:limit]
    return {
        "account_id": account.account_id,
        "count": len(selected),
        "has_more": has_more,
        "next_before_sequence": selected[-1].sequence if has_more and selected else None,
        "items": [
            {
                "sequence": entry.sequence,
                "period": entry.period,
                "channel": entry.channel,
                "sku": entry.sku,
                "quantity": entry.quantity,
                "amount_micros": entry.amount_micros,
                "proof_hash": entry.proof_hash,
                "context_hash": entry.context_hash,
                "recorded_at": entry.recorded_at,
                "entry_hash": entry.entry_hash,
            }
            for entry in selected
        ],
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


@router.post("/activate")
def activate(request: ActivateRequest, response: Response) -> dict:
    """Issue a free-tier API key for a channel, with no operator in the loop.

    Activation is idempotent per (channel, activation_id) and rate limited, and
    it can only ever grant the free plan — a paid entitlement still requires
    Stripe, so this route cannot hand out billable capacity.
    """
    result = get_activation().activate(
        channel=request.channel,
        activation_id=request.activation_id,
        display_name=request.display_name,
    )
    response.status_code = result.http_status

    body: dict[str, Any] = {
        "decision": result.decision,
        "activated": result.activated,
        "remediation": result.remediation.to_dict(),
    }
    if result.retry_after_seconds is not None:
        body["retry_after_seconds"] = result.retry_after_seconds
        response.headers["Retry-After"] = str(result.retry_after_seconds)
    if result.account is not None:
        body["account"] = result.account.public_view()
        plan = get_plan(result.account.plan)
        body["plan"] = {
            "plan": plan.plan,
            "included_units": plan.included_units,
            "hard_cap_units": plan.hard_cap_units,
            "base_price_micros": plan.base_price_micros,
        }
    if result.api_key is not None:
        body["api_key"] = result.api_key
        body["notice"] = (
            "This key is shown once. Store it now; only its hash is retained."
        )
        body["next_call"] = {
            "method": "POST",
            "path": "/verify/evaluate",
            "header": "X-DSG-API-Key",
        }
    return body


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
        status = 503 if not config.webhook_secret else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    try:
        event: Any = json.loads(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="webhook body is not JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="webhook body is not a JSON object")

    result = apply_webhook_event(event, get_engine().accounts, config)
    return {"received": True, "event_id": event.get("id"), "result": result}


__all__ = [
    "router",
    "authorize_request",
    "meter",
    "diagnose_entitlement",
    "get_engine",
    "get_activation",
    "reset_engine",
    "idempotency_key",
    "activation_ref",
    "remediation_for",
    "BACKEND_UNAVAILABLE",
    "BILLING_STORAGE_NOT_READY",
    "CONFIGURATION_INCOMPLETE",
    "METERING_REFUSED",
    "VERIFICATION_NOT_PROVED",
]
