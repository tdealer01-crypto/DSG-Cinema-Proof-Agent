"""Stripe billing link with verified readiness and scoped webhooks.

Credential presence is configuration, not proof that money can move. Public
status becomes ``LINKED_VERIFIED`` only after Stripe confirms the configured
product, price, payment link, meter, and webhook endpoint. Webhooks are signature checked,
catalog scoped, subscription scoped, idempotent, and stale-event resistant.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .accounts import STATUS_ACTIVE, STATUS_SUSPENDED, AccountStore
from .pricing import get_plan

STRIPE_API_BASE = "https://api.stripe.com"
DEFAULT_TOLERANCE_SECONDS = 300

LINK_LIVE = "LINKED_VERIFIED"
LINK_TEST = "TEST_MODE_VERIFIED"
LINK_CONFIGURED = "CONFIGURED_UNVERIFIED"
LINK_NOT_LINKED = "NOT_LINKED"

SUBSCRIPTION_PLAN_METADATA_KEY = "dsg_plan"

HANDLED_EVENTS = (
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
)

_OPERATIONAL_CACHE_TTL_SECONDS = 60.0
_operational_cache: dict[tuple, tuple[float, dict]] = {}
_operational_cache_lock = threading.Lock()


class SignatureError(ValueError):
    """Raised when a Stripe webhook signature cannot be verified."""


@dataclass(frozen=True)
class StripeConfig:
    secret_key: Optional[str]
    webhook_secret: Optional[str]
    meter_event_name: str
    product_id: Optional[str] = None
    price_id: Optional[str] = None
    payment_link_id: Optional[str] = None
    meter_id: Optional[str] = None
    webhook_endpoint_id: Optional[str] = None
    webhook_endpoint_url: Optional[str] = None

    @property
    def api_configured(self) -> bool:
        return bool(self.secret_key)

    @property
    def livemode(self) -> Optional[bool]:
        parts = (self.secret_key or "").split("_", 2)
        if len(parts) < 2 or parts[0] != "sk":
            return None
        if parts[1] == "live":
            return True
        if parts[1] == "test":
            return False
        return None

    @property
    def webhook_scope_configured(self) -> bool:
        return bool(self.product_id and self.price_id)

    @property
    def operational_scope_configured(self) -> bool:
        return bool(
            self.webhook_scope_configured
            and self.payment_link_id
            and self.meter_id
            and self.meter_event_name
            and self.webhook_endpoint_id
            and self.webhook_endpoint_url
            and self.webhook_secret
        )

    @property
    def meter_configured(self) -> bool:
        return bool(
            self.api_configured
            and self.operational_scope_configured
            and self.livemode is not None
        )

    @property
    def accepts_webhooks(self) -> bool:
        return bool(
            self.webhook_secret
            and self.webhook_scope_configured
            and self.livemode is not None
        )

    def status(self, operational: Optional[dict] = None) -> dict:
        verified = bool(operational and operational.get("verified") is True)
        live_verified = bool(verified and operational.get("livemode") is True)
        if live_verified:
            link_state = LINK_LIVE
        elif verified:
            link_state = LINK_TEST
        elif self.api_configured:
            link_state = LINK_CONFIGURED
        else:
            link_state = LINK_NOT_LINKED
        return {
            "link_state": link_state,
            "configured": self.api_configured,
            "catalog_scope_configured": self.webhook_scope_configured,
            "operational_scope_configured": self.operational_scope_configured,
            "charges_enabled": live_verified,
            "webhooks_configured": self.accepts_webhooks,
            "webhooks_enabled": bool(live_verified and self.accepts_webhooks),
            "meter_event_name": self.meter_event_name,
            "operational_checks": (operational or {}).get("checks", {}),
        }


def config_from_env(env: Optional[dict] = None) -> StripeConfig:
    source = env if env is not None else os.environ

    def optional(name: str) -> Optional[str]:
        return (source.get(name) or "").strip() or None

    return StripeConfig(
        secret_key=optional("STRIPE_SECRET_KEY"),
        webhook_secret=optional("STRIPE_WEBHOOK_SECRET"),
        meter_event_name=(
            source.get("STRIPE_METER_EVENT_NAME") or "dsg_verified_execution"
        ).strip(),
        product_id=optional("STRIPE_PRODUCT_ID"),
        price_id=optional("STRIPE_PRICE_ID"),
        payment_link_id=optional("STRIPE_PAYMENT_LINK_ID"),
        meter_id=optional("STRIPE_METER_ID"),
        webhook_endpoint_id=optional("STRIPE_WEBHOOK_ENDPOINT_ID"),
        webhook_endpoint_url=optional("STRIPE_WEBHOOK_ENDPOINT_URL"),
    )


async def verify_operational_link(
    config: StripeConfig,
    *,
    timeout_seconds: float = 8.0,
) -> dict:
    """Verify the configured Stripe commerce objects against Stripe itself."""
    if not config.api_configured:
        return {"verified": False, "checks": {"configuration": "NOT_CONFIGURED"}}
    if not config.operational_scope_configured:
        return {"verified": False, "checks": {"configuration": "INCOMPLETE"}}

    if config.livemode is None:
        return {"verified": False, "checks": {"configuration": "INVALID_KEY_MODE"}}
    expected_livemode = config.livemode
    cache_key = (
        hashlib.sha256((config.secret_key or "").encode("utf-8")).hexdigest(),
        config.product_id,
        config.price_id,
        config.payment_link_id,
        config.meter_id,
        config.meter_event_name,
        config.webhook_endpoint_id,
        config.webhook_endpoint_url,
    )
    now = time.monotonic()
    with _operational_cache_lock:
        cached = _operational_cache.get(cache_key)
        if cached and now - cached[0] < _OPERATIONAL_CACHE_TTL_SECONDS:
            return dict(cached[1])

    headers = {"Authorization": f"Bearer {config.secret_key}"}
    checks: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            product_response = await client.get(
                f"{STRIPE_API_BASE}/v1/products/{config.product_id}",
                headers=headers,
            )
            price_response = await client.get(
                f"{STRIPE_API_BASE}/v1/prices/{config.price_id}",
                headers=headers,
            )
            payment_link_response = await client.get(
                f"{STRIPE_API_BASE}/v1/payment_links/{config.payment_link_id}",
                headers=headers,
            )
            payment_link_items_response = await client.get(
                f"{STRIPE_API_BASE}/v1/payment_links/{config.payment_link_id}/line_items",
                headers=headers,
                params={"limit": 100},
            )
            meter_response = await client.get(
                f"{STRIPE_API_BASE}/v1/billing/meters/{config.meter_id}",
                headers=headers,
            )
            webhook_response = await client.get(
                f"{STRIPE_API_BASE}/v1/webhook_endpoints/{config.webhook_endpoint_id}",
                headers=headers,
            )
    except httpx.HTTPError as exc:
        result = {
            "verified": False,
            "livemode": expected_livemode,
            "checks": {"stripe_api": f"UNAVAILABLE_{type(exc).__name__}"},
        }
        with _operational_cache_lock:
            _operational_cache[cache_key] = (now, result)
        return dict(result)

    responses = {
        "product": product_response,
        "price": price_response,
        "payment_link": payment_link_response,
        "payment_link_items": payment_link_items_response,
        "meter": meter_response,
        "webhook": webhook_response,
    }
    bodies: dict[str, dict] = {}
    for name, response in responses.items():
        if response.status_code != 200:
            checks[name] = f"HTTP_{response.status_code}"
            continue
        try:
            body = response.json()
        except ValueError:
            checks[name] = "INVALID_JSON"
            continue
        if not isinstance(body, dict):
            checks[name] = "INVALID_BODY"
            continue
        bodies[name] = body

    product = bodies.get("product", {})
    checks["product"] = (
        "PASS"
        if product.get("id") == config.product_id
        and product.get("active") is True
        and product.get("livemode") is expected_livemode
        else checks.get("product", "MISMATCH")
    )

    price = bodies.get("price", {})
    price_product = price.get("product")
    if isinstance(price_product, dict):
        price_product = price_product.get("id")
    checks["price"] = (
        "PASS"
        if price.get("id") == config.price_id
        and price.get("active") is True
        and price_product == config.product_id
        and price.get("livemode") is expected_livemode
        else checks.get("price", "MISMATCH")
    )

    payment_link = bodies.get("payment_link", {})
    line_items = bodies.get("payment_link_items", {}).get("data") or []
    linked_prices = set()
    for item in line_items:
        item_price = item.get("price") if isinstance(item, dict) else None
        if isinstance(item_price, dict):
            linked_prices.add(item_price.get("id"))
        elif isinstance(item_price, str):
            linked_prices.add(item_price)
    payment_link_failure = checks.get("payment_link") or checks.get(
        "payment_link_items"
    )
    checks["payment_link"] = (
        "PASS"
        if payment_link.get("id") == config.payment_link_id
        and payment_link.get("active") is True
        and payment_link.get("livemode") is expected_livemode
        and config.price_id in linked_prices
        else payment_link_failure or "MISMATCH"
    )
    checks.pop("payment_link_items", None)

    meter = bodies.get("meter", {})
    checks["meter"] = (
        "PASS"
        if meter.get("id") == config.meter_id
        and meter.get("status") == "active"
        and meter.get("event_name") == config.meter_event_name
        and meter.get("livemode") is expected_livemode
        else checks.get("meter", "MISMATCH")
    )

    webhook = bodies.get("webhook", {})
    enabled_events = webhook.get("enabled_events") or []
    checks["webhook"] = (
        "PASS"
        if webhook.get("id") == config.webhook_endpoint_id
        and webhook.get("status") == "enabled"
        and webhook.get("url") == config.webhook_endpoint_url
        and webhook.get("livemode") is expected_livemode
        and all(event_type in enabled_events for event_type in HANDLED_EVENTS)
        else checks.get("webhook", "MISMATCH")
    )

    result = {
        "verified": all(
            checks.get(name) == "PASS"
            for name in ("product", "price", "payment_link", "meter", "webhook")
        ),
        "livemode": expected_livemode,
        "checks": checks,
    }
    with _operational_cache_lock:
        _operational_cache[cache_key] = (now, result)
    return dict(result)


# ------------------------------------------------------------------ inbound
def parse_signature_header(header: str) -> tuple[int, list[str]]:
    timestamp = -1
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise SignatureError("signature timestamp is not an integer") from exc
        elif key == "v1":
            signatures.append(value)
    if timestamp < 0 or not signatures:
        raise SignatureError("signature header is missing t or v1")
    return timestamp, signatures


def verify_webhook_signature(
    payload: bytes,
    signature_header: Optional[str],
    secret: Optional[str],
    *,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: Optional[int] = None,
) -> None:
    """Verify Stripe's ``t=...,v1=...`` scheme."""
    if not secret:
        raise SignatureError("webhook secret is not configured")
    if not signature_header:
        raise SignatureError("Stripe-Signature header is required")

    timestamp, signatures = parse_signature_header(signature_header)
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise SignatureError("signature timestamp is outside the tolerance window")

    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise SignatureError("no signature in the header matched")


def _ignored(event_type: Any, reason: str, **extra: Any) -> dict:
    return {"applied": False, "reason": reason, "type": event_type, **extra}


def _plan_from_subscription(subscription: dict) -> Optional[str]:
    metadata = subscription.get("metadata") or {}
    plan = metadata.get(SUBSCRIPTION_PLAN_METADATA_KEY)
    if not isinstance(plan, str) or not plan:
        return None
    try:
        get_plan(plan)
    except ValueError:
        return None
    return plan


def _subscription_id(event_type: str, obj: dict) -> Optional[str]:
    if event_type.startswith("customer.subscription."):
        value = obj.get("id")
    elif event_type == "checkout.session.completed":
        value = obj.get("subscription")
    else:
        value = obj.get("subscription")
        if not value:
            value = (
                ((obj.get("parent") or {}).get("subscription_details") or {}).get(
                    "subscription"
                )
            )
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, str) and value else None


def _subscription_matches_catalog(obj: dict, config: StripeConfig) -> bool:
    items = ((obj.get("items") or {}).get("data") or [])
    for item in items:
        price = item.get("price") if isinstance(item, dict) else None
        if not isinstance(price, dict):
            continue
        product = price.get("product")
        if isinstance(product, dict):
            product = product.get("id")
        if price.get("id") == config.price_id and product == config.product_id:
            return True
    return False


def _checkout_matches_catalog(obj: dict, config: StripeConfig) -> bool:
    metadata = obj.get("metadata") or {}
    return (
        metadata.get("dsg_product_id") == config.product_id
        and metadata.get("dsg_price_id") == config.price_id
    )


def _invoice_line_matches_catalog(line: Any, config: StripeConfig) -> bool:
    if not isinstance(line, dict):
        return False
    price = line.get("price")
    if not isinstance(price, dict):
        price = ((line.get("pricing") or {}).get("price_details") or {}).get(
            "price"
        )
    if not isinstance(price, dict):
        return False
    product = price.get("product")
    if isinstance(product, dict):
        product = product.get("id")
    return price.get("id") == config.price_id and product == config.product_id


def _invoice_matches_catalog(obj: dict, config: StripeConfig) -> bool:
    lines = ((obj.get("lines") or {}).get("data") or [])
    return any(_invoice_line_matches_catalog(line, config) for line in lines)


def _scoped_invoice_paid_cents(
    obj: dict,
    config: StripeConfig,
) -> Optional[int]:
    """Return only the paid amount attributable to exact DSG invoice lines.

    An invoice can contain products from more than one subscription. Recording
    the invoice-wide ``amount_paid`` would therefore overstate DSG receipts.
    Missing line amounts fail closed: entitlement may be linked, but no paid
    amount is recognized until the scoped value is present in webhook evidence.
    """
    amount_paid = obj.get("amount_paid")
    if (
        not isinstance(amount_paid, int)
        or amount_paid < 0
        or obj.get("currency") != "usd"
    ):
        return None

    matching_lines = [
        line
        for line in ((obj.get("lines") or {}).get("data") or [])
        if _invoice_line_matches_catalog(line, config)
    ]
    if not matching_lines:
        return None

    line_amounts = [line.get("amount") for line in matching_lines]
    if any(not isinstance(amount, int) for amount in line_amounts):
        return None

    scoped_total = max(sum(line_amounts), 0)
    return min(amount_paid, scoped_total)


def _paid_period(obj: dict, event_created: int) -> str:
    timestamp = obj.get("period_start")
    if not isinstance(timestamp, int):
        timestamp = event_created
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m")


def apply_webhook_event(
    event: dict,
    accounts: AccountStore,
    config: StripeConfig,
) -> dict:
    """Apply one verified Stripe event only to its exact DSG subscription."""
    event_type = event.get("type")
    if event_type not in HANDLED_EVENTS:
        return _ignored(event_type, "event type is not handled")
    if not config.webhook_scope_configured:
        return _ignored(event_type, "DSG Stripe catalog scope is not configured")
    if config.livemode is None or event.get("livemode") is not config.livemode:
        return _ignored(event_type, "event mode does not match the DSG Stripe key")

    event_id = event.get("id")
    event_created = event.get("created")
    if not isinstance(event_id, str) or not event_id:
        return _ignored(event_type, "event has no stable id")
    if not isinstance(event_created, int) or event_created < 0:
        return _ignored(event_type, "event has no valid creation time")

    obj: Any = (event.get("data") or {}).get("object") or {}
    if not isinstance(obj, dict):
        return _ignored(event_type, "event object is not an object")
    customer_id = obj.get("customer")
    if not isinstance(customer_id, str) or not customer_id:
        return _ignored(event_type, "event has no customer")

    account = accounts.find_by_stripe_customer(customer_id)
    if account is None:
        return _ignored(event_type, "no account is linked to this Stripe customer")

    subscription_id = _subscription_id(event_type, obj)
    if not subscription_id:
        return _ignored(event_type, "event has no subscription")

    allow_binding = event_type in {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
    }
    if event_type == "checkout.session.completed":
        if not _checkout_matches_catalog(obj, config):
            return _ignored(event_type, "checkout is outside the DSG catalog scope")
    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
    }:
        if not _subscription_matches_catalog(obj, config):
            return _ignored(event_type, "subscription is outside the DSG catalog scope")
    elif event_type in {"invoice.paid", "invoice.payment_failed"}:
        if account.stripe_subscription_id:
            if account.stripe_subscription_id != subscription_id:
                return _ignored(event_type, "event is for a different subscription")
        elif _invoice_matches_catalog(obj, config):
            allow_binding = True
        else:
            return _ignored(event_type, "invoice is outside the DSG catalog scope")
    elif account.stripe_subscription_id != subscription_id:
        return _ignored(event_type, "event is for a different subscription")

    changes: dict[str, Any] = {}
    paid_period: Optional[str] = None
    paid_amount_micros: Optional[int] = None
    paid_invoice_id: Optional[str] = None
    if event_type == "checkout.session.completed":
        changes["payment_linked"] = obj.get("payment_status") == "paid"
        changes["status"] = STATUS_ACTIVE
    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
    }:
        plan = _plan_from_subscription(obj)
        if plan:
            changes["plan"] = plan
        active = obj.get("status") in {"active", "trialing"}
        changes["payment_linked"] = active
        changes["status"] = STATUS_ACTIVE if active else STATUS_SUSPENDED
    elif event_type == "customer.subscription.deleted":
        changes["payment_linked"] = False
        changes["status"] = STATUS_SUSPENDED
        changes["stripe_subscription_id"] = None
    elif event_type == "invoice.paid":
        changes["payment_linked"] = True
        changes["status"] = STATUS_ACTIVE
        scoped_paid_cents = _scoped_invoice_paid_cents(obj, config)
        invoice_id = obj.get("id")
        if isinstance(invoice_id, str) and invoice_id:
            # Track the scoped invoice object even when its line amount is
            # missing, so a second event cannot recognize it twice. Missing
            # amount evidence remains zero rather than being guessed later.
            paid_invoice_id = invoice_id
        if (
            scoped_paid_cents is not None
            and paid_invoice_id is not None
        ):
            paid_period = _paid_period(obj, event_created)
            paid_amount_micros = scoped_paid_cents * 10_000
    elif event_type == "invoice.payment_failed":
        changes["payment_linked"] = False
        changes["status"] = STATUS_SUSPENDED

    updated, outcome = accounts.apply_stripe_event(
        customer_id=customer_id,
        subscription_id=subscription_id,
        event_id=event_id,
        event_created=event_created,
        allow_subscription_binding=allow_binding,
        changes=changes,
        paid_period=paid_period,
        paid_amount_micros=paid_amount_micros,
        paid_invoice_id=paid_invoice_id,
    )
    if outcome != "applied":
        return _ignored(event_type, outcome, event_id=event_id)
    assert updated is not None
    return {
        "applied": True,
        "type": event_type,
        "event_id": event_id,
        "account_id": updated.account_id,
        "plan": updated.plan,
        "status": updated.status,
        "payment_linked": updated.payment_linked,
        "stripe_subscription_id": updated.stripe_subscription_id,
    }


# ----------------------------------------------------------------- outbound
async def push_meter_event(
    config: StripeConfig,
    *,
    stripe_customer_id: Optional[str],
    quantity: int,
    identifier: str,
    timeout_seconds: float = 15.0,
) -> dict:
    """Report one metered usage event to Stripe without changing proof state."""
    if not config.meter_configured:
        return {
            "sync_state": "PENDING_UNLINKED",
            "detail": "complete Stripe commerce and meter configuration is required",
        }
    if not stripe_customer_id:
        return {"sync_state": "PENDING", "detail": "account has no Stripe customer id"}

    payload = {
        "event_name": config.meter_event_name,
        "identifier": identifier,
        "payload[stripe_customer_id]": stripe_customer_id,
        "payload[value]": str(quantity),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{STRIPE_API_BASE}/v1/billing/meter_events",
                data=payload,
                headers={
                    "Authorization": f"Bearer {config.secret_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
    except httpx.HTTPError as exc:
        return {
            "sync_state": "FAILED",
            "detail": f"Stripe request failed: {type(exc).__name__}",
        }

    if response.status_code in {200, 201}:
        return {"sync_state": "SYNCED", "identifier": identifier}
    if response.status_code == 409:
        return {
            "sync_state": "SYNCED",
            "identifier": identifier,
            "detail": "duplicate event",
        }
    return {
        "sync_state": "FAILED",
        "detail": f"Stripe returned HTTP {response.status_code}",
    }
