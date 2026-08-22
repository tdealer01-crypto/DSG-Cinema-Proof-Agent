"""Self-serve paid checkout for DSG verified execution.

The existing revenue engine already owns entitlement, proof-bound metering,
and signed Stripe webhook handling.  This module closes the missing step between
free activation and a paid entitlement: it creates a Stripe-hosted Checkout
Session for the configured *metered* recurring Price.

Creating a Checkout Session does **not** grant entitlement.  The account remains
on its current DSG plan until the existing signature-verified Stripe webhook
path observes the scoped subscription event and updates the account.  This keeps
browser redirects and client-provided state outside the trust boundary.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from revenue import api as billing
from .accounts import Account
from .stripe_sync import (
    STRIPE_API_BASE,
    StripeConfig,
    config_from_env,
    verify_operational_link,
)

router = APIRouter(prefix="/billing", tags=["billing"])

CHECKOUT_STATE_CREATED = "CHECKOUT_CREATED_NOT_ENTITLED"
DEFAULT_CHECKOUT_RETURN_URL = "https://dsgoneverifiedweb.z1.web.core.windows.net/"


class CheckoutSessionRequest(BaseModel):
    """A stable caller id makes retries idempotent without trusting a redirect."""

    plan: Literal["metered"] = "metered"
    checkout_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


def _configuration_error(message: str, *, checks: Optional[dict] = None) -> HTTPException:
    detail: dict[str, Any] = {
        "error": billing.CONFIGURATION_INCOMPLETE,
        "message": message,
        "remediation": billing.remediation_for(
            billing.CONFIGURATION_INCOMPLETE
        ).to_dict(),
    }
    if checks:
        detail["checks"] = checks
    return HTTPException(status_code=503, detail=detail)


def _require_live_account(api_key: Optional[str]) -> Account:
    account = billing.get_engine().accounts.authenticate((api_key or "").strip())
    if account is None:
        raise HTTPException(
            status_code=401,
            detail="a valid X-DSG-API-Key header is required",
        )
    if account.mode != "live":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "CHECKOUT_LIVE_KEY_REQUIRED",
                "message": "paid checkout is available only to a live DSG API key",
            },
        )
    if account.plan.startswith("github_"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "EXTERNAL_BILLING_CHANNEL",
                "message": "this account is billed by GitHub Marketplace and must not be billed again by Stripe",
            },
        )
    if account.plan in {"team", "enterprise"}:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "PLAN_NOT_SELF_SERVE_METERED",
                "message": "this entitlement is not eligible for the metered self-serve checkout path",
            },
        )
    if account.plan == "metered" and account.payment_linked:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ALREADY_ENTITLED",
                "message": "this account already has an active metered entitlement",
            },
        )
    return account


def _require_stripe_portal_account(api_key: Optional[str]) -> Account:
    account = billing.get_engine().accounts.authenticate((api_key or "").strip())
    if account is None:
        raise HTTPException(
            status_code=401,
            detail="a valid X-DSG-API-Key header is required",
        )
    if account.mode != "live":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "PORTAL_LIVE_KEY_REQUIRED",
                "message": "the billing portal is available only to a live DSG API key",
            },
        )
    if account.plan.startswith("github_"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "EXTERNAL_BILLING_CHANNEL",
                "message": "this account is billed by GitHub Marketplace and has no Stripe portal",
            },
        )
    return account


def _return_url(outcome: str, *, include_session_id: bool) -> str:
    """Build a trusted return URL; callers cannot supply an arbitrary redirect."""
    base = (os.getenv("DSG_CHECKOUT_RETURN_URL") or DEFAULT_CHECKOUT_RETURN_URL).strip()
    parts = urlsplit(base)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
    ):
        raise _configuration_error("DSG_CHECKOUT_RETURN_URL must be an absolute HTTPS URL")

    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("checkout", outcome))
    if include_session_id:
        # Stripe replaces this literal placeholder after Checkout completes.
        query.append(("session_id", "{CHECKOUT_SESSION_ID}"))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _portal_return_url() -> str:
    base = (os.getenv("DSG_CHECKOUT_RETURN_URL") or DEFAULT_CHECKOUT_RETURN_URL).strip()
    parts = urlsplit(base)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
    ):
        raise _configuration_error("DSG_CHECKOUT_RETURN_URL must be an absolute HTTPS URL")
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("portal", "return"))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _idempotency_key(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"dsg-{digest}"


async def _stripe_post(
    config: StripeConfig,
    path: str,
    *,
    data: dict[str, str],
    idempotency_key: str,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    if not config.secret_key:
        raise _configuration_error("Stripe secret key is not configured")

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{STRIPE_API_BASE}{path}",
                data=data,
                headers={
                    "Authorization": f"Bearer {config.secret_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Idempotency-Key": idempotency_key,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "STRIPE_CHECKOUT_UNAVAILABLE",
                "message": f"Stripe request failed: {type(exc).__name__}",
            },
        ) from exc

    if response.status_code not in {200, 201}:
        # Do not reflect Stripe's body: it can contain implementation details.
        raise HTTPException(
            status_code=502,
            detail={
                "error": "STRIPE_CHECKOUT_REJECTED",
                "message": f"Stripe returned HTTP {response.status_code}",
            },
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "STRIPE_CHECKOUT_INVALID_RESPONSE",
                "message": "Stripe returned non-JSON checkout data",
            },
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "error": "STRIPE_CHECKOUT_INVALID_RESPONSE",
                "message": "Stripe returned an invalid checkout object",
            },
        )
    return body


async def _require_verified_live_catalog(config: StripeConfig) -> None:
    """A configured key is not evidence that this deployment can charge."""
    if config.livemode is not True:
        raise _configuration_error("Stripe live mode is not configured for paid checkout")
    if not config.product_id or not config.price_id:
        raise _configuration_error("Stripe product and price scope are not configured")

    operational = await verify_operational_link(config)
    if operational.get("verified") is not True or operational.get("livemode") is not True:
        raise _configuration_error(
            "Stripe product, price, meter, and webhook have not all been verified in live mode",
            checks=operational.get("checks") if isinstance(operational, dict) else None,
        )


async def _ensure_stripe_customer(account: Account, config: StripeConfig) -> Account:
    if account.stripe_customer_id:
        return account

    body = await _stripe_post(
        config,
        "/v1/customers",
        data={
            "name": account.display_name,
            "metadata[dsg_account_id]": account.account_id,
            "metadata[dsg_channel]": account.channel,
        },
        idempotency_key=_idempotency_key("customer", account.account_id),
    )
    customer_id = body.get("id")
    if not isinstance(customer_id, str) or not customer_id.startswith("cus_"):
        raise HTTPException(
            status_code=502,
            detail={
                "error": "STRIPE_CUSTOMER_INVALID",
                "message": "Stripe did not return a valid customer id",
            },
        )

    # Persist the mapping before creating Checkout so signed webhooks can resolve
    # the Stripe customer to the exact DSG account even if they arrive quickly.
    return billing.get_engine().accounts.update(
        account.account_id,
        stripe_customer_id=customer_id,
    )


@router.post("/checkout/session", status_code=201)
async def create_checkout_session(
    request: CheckoutSessionRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    """Create Stripe-hosted metered checkout without granting entitlement."""
    account = _require_live_account(x_dsg_api_key)
    config = config_from_env()
    await _require_verified_live_catalog(config)
    account = await _ensure_stripe_customer(account, config)

    assert config.product_id is not None
    assert config.price_id is not None
    assert account.stripe_customer_id is not None

    session = await _stripe_post(
        config,
        "/v1/checkout/sessions",
        data={
            "mode": "subscription",
            "customer": account.stripe_customer_id,
            "client_reference_id": account.account_id,
            "success_url": _return_url("success", include_session_id=True),
            "cancel_url": _return_url("cancelled", include_session_id=False),
            # Quantity is intentionally omitted for a metered recurring Price.
            "line_items[0][price]": config.price_id,
            # Session metadata is checked by checkout.session.completed.
            "metadata[dsg_account_id]": account.account_id,
            "metadata[dsg_product_id]": config.product_id,
            "metadata[dsg_price_id]": config.price_id,
            "metadata[dsg_plan]": request.plan,
            # Subscription metadata is what subscription.created/updated uses
            # to promote the account from free to the metered entitlement.
            "subscription_data[metadata][dsg_account_id]": account.account_id,
            "subscription_data[metadata][dsg_plan]": request.plan,
        },
        idempotency_key=_idempotency_key(
            "checkout",
            account.account_id,
            request.plan,
            request.checkout_id,
        ),
    )

    session_id = session.get("id")
    checkout_url = session.get("url")
    if (
        not isinstance(session_id, str)
        or not session_id.startswith("cs_")
        or not isinstance(checkout_url, str)
        or not checkout_url.startswith("https://")
    ):
        raise HTTPException(
            status_code=502,
            detail={
                "error": "STRIPE_CHECKOUT_INVALID_RESPONSE",
                "message": "Stripe did not return a valid Checkout Session URL",
            },
        )

    # Deliberately re-read the account and report its *current* entitlement.
    # Checkout creation is not payment evidence and must never flip these fields.
    current = billing.get_engine().accounts.get(account.account_id)
    assert current is not None
    return {
        "state": CHECKOUT_STATE_CREATED,
        "entitled": False,
        "session_id": session_id,
        "checkout_url": checkout_url,
        "requested_plan": request.plan,
        "account": current.public_view(),
        "next_step": (
            "Complete Stripe Checkout. DSG keeps the current entitlement until "
            "a valid signed Stripe webhook confirms the scoped subscription."
        ),
    }


@router.post("/portal/session", status_code=201)
async def create_billing_portal_session(
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    account = _require_stripe_portal_account(x_dsg_api_key)
    if not account.stripe_customer_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "STRIPE_CUSTOMER_REQUIRED",
                "message": "complete Stripe checkout before opening the billing portal",
            },
        )

    config = config_from_env()
    session = await _stripe_post(
        config,
        "/v1/billing_portal/sessions",
        data={
            "customer": account.stripe_customer_id,
            "return_url": _portal_return_url(),
        },
        idempotency_key=_idempotency_key(
            "portal", account.account_id, secrets.token_hex(16)
        ),
    )
    session_id = session.get("id")
    portal_url = session.get("url")
    parsed_portal_url = urlsplit(portal_url) if isinstance(portal_url, str) else None
    if (
        not isinstance(session_id, str)
        or not session_id.startswith("bps_")
        or parsed_portal_url is None
        or parsed_portal_url.scheme != "https"
        or parsed_portal_url.hostname != "billing.stripe.com"
        or parsed_portal_url.username is not None
        or parsed_portal_url.password is not None
    ):
        raise HTTPException(
            status_code=502,
            detail={
                "error": "STRIPE_PORTAL_INVALID_RESPONSE",
                "message": "Stripe did not return a trusted billing portal URL",
            },
        )
    return {
        "state": "BILLING_PORTAL_CREATED",
        "portal_url": portal_url,
        "account": account.public_view(),
    }


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "router",
    "install",
    "CheckoutSessionRequest",
    "CHECKOUT_STATE_CREATED",
]
