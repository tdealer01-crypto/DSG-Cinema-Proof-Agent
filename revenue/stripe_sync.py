"""Stripe billing link: webhook verification and meter-event push.

The link is optional and fail-closed in both directions:

- With no `STRIPE_SECRET_KEY`, the connector reports NOT_LINKED. Usage is still
  metered into the ledger, but nothing is charged and no endpoint pretends a
  charge happened.
- With no `STRIPE_WEBHOOK_SECRET`, inbound webhooks are rejected rather than
  trusted, so plan state can never be changed by an unsigned caller.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .accounts import STATUS_ACTIVE, STATUS_SUSPENDED, Account, AccountStore

STRIPE_API_BASE = "https://api.stripe.com"
DEFAULT_TOLERANCE_SECONDS = 300

LINK_LIVE = "LINKED"
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


class SignatureError(ValueError):
    """Raised when a Stripe webhook signature cannot be verified."""


@dataclass(frozen=True)
class StripeConfig:
    secret_key: Optional[str]
    webhook_secret: Optional[str]
    meter_event_name: str

    @property
    def linked(self) -> bool:
        return bool(self.secret_key)

    @property
    def accepts_webhooks(self) -> bool:
        return bool(self.webhook_secret)

    def status(self) -> dict:
        return {
            "link_state": LINK_LIVE if self.linked else LINK_NOT_LINKED,
            "charges_enabled": self.linked,
            "webhooks_enabled": self.accepts_webhooks,
            "meter_event_name": self.meter_event_name,
        }


def config_from_env(env: Optional[dict] = None) -> StripeConfig:
    source = env if env is not None else os.environ
    return StripeConfig(
        secret_key=(source.get("STRIPE_SECRET_KEY") or "").strip() or None,
        webhook_secret=(source.get("STRIPE_WEBHOOK_SECRET") or "").strip() or None,
        meter_event_name=(
            source.get("STRIPE_METER_EVENT_NAME") or "dsg_verified_execution"
        ).strip(),
    )


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
    """Verify Stripe's `t=...,v1=...` scheme. Raises SignatureError on failure."""
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
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()

    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise SignatureError("no signature in the header matched")


def _plan_from_subscription(subscription: dict) -> Optional[str]:
    metadata = subscription.get("metadata") or {}
    plan = metadata.get(SUBSCRIPTION_PLAN_METADATA_KEY)
    return plan if isinstance(plan, str) and plan else None


def apply_webhook_event(event: dict, accounts: AccountStore) -> dict:
    """Apply one verified Stripe event to account entitlement state.

    Unknown events and events for unknown customers are reported as ignored;
    they never create an account or grant entitlement implicitly.
    """
    event_type = event.get("type")
    if event_type not in HANDLED_EVENTS:
        return {"applied": False, "reason": "event type is not handled", "type": event_type}

    obj: Any = (event.get("data") or {}).get("object") or {}
    if not isinstance(obj, dict):
        return {"applied": False, "reason": "event object is not an object", "type": event_type}

    customer_id = obj.get("customer")
    if not isinstance(customer_id, str) or not customer_id:
        return {"applied": False, "reason": "event has no customer", "type": event_type}

    account: Optional[Account] = accounts.find_by_stripe_customer(customer_id)
    if account is None:
        return {
            "applied": False,
            "reason": "no account is linked to this Stripe customer",
            "type": event_type,
        }

    changes: dict[str, Any] = {}
    if event_type == "checkout.session.completed":
        changes["payment_linked"] = True
        changes["status"] = STATUS_ACTIVE
        subscription_id = obj.get("subscription")
        if isinstance(subscription_id, str) and subscription_id:
            changes["stripe_subscription_id"] = subscription_id
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        subscription_id = obj.get("id")
        if isinstance(subscription_id, str) and subscription_id:
            changes["stripe_subscription_id"] = subscription_id
        plan = _plan_from_subscription(obj)
        if plan:
            changes["plan"] = plan
        stripe_status = obj.get("status")
        active = stripe_status in {"active", "trialing"}
        changes["payment_linked"] = active
        changes["status"] = STATUS_ACTIVE if active else STATUS_SUSPENDED
    elif event_type == "customer.subscription.deleted":
        changes["payment_linked"] = False
        changes["status"] = STATUS_SUSPENDED
        changes["stripe_subscription_id"] = None
    elif event_type == "invoice.paid":
        changes["payment_linked"] = True
        changes["status"] = STATUS_ACTIVE
    elif event_type == "invoice.payment_failed":
        changes["status"] = STATUS_SUSPENDED

    updated = accounts.update(account.account_id, **changes)
    return {
        "applied": True,
        "type": event_type,
        "account_id": updated.account_id,
        "plan": updated.plan,
        "status": updated.status,
        "payment_linked": updated.payment_linked,
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
    """Report one metered usage event to Stripe.

    Returns a sync state instead of raising, so a billing outage degrades to a
    retryable ledger state rather than failing a proof that already succeeded.
    """
    if not config.linked:
        return {"sync_state": "PENDING_UNLINKED", "detail": "Stripe secret key is not configured"}
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
        return {"sync_state": "FAILED", "detail": f"Stripe request failed: {type(exc).__name__}"}

    if response.status_code in {200, 201}:
        return {"sync_state": "SYNCED", "identifier": identifier}
    if response.status_code == 409:
        # Stripe rejects a duplicate identifier, which means it is already recorded.
        return {"sync_state": "SYNCED", "identifier": identifier, "detail": "duplicate event"}
    return {
        "sync_state": "FAILED",
        "detail": f"Stripe returned HTTP {response.status_code}",
    }
