"""Consent-gated ActiveCampaign lifecycle synchronization.

This module is deliberately downstream of DSG/Stripe truth. It never grants
entitlement and it never treats a marketing event as payment evidence.

Production rules:
- a contact is subscribed only when the marketing profile has explicit consent;
- the DSG account id is copied into ActiveCampaign for deterministic correlation;
- intent tags are kept mutually exclusive for events that establish intent;
- payment/customer tags are emitted only by callers that already verified Stripe;
- ActiveCampaign outages never roll back account activation or Stripe webhook truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from .accounts import Account
from .marketing_profiles import MarketingProfile

EVENT_LEAD = "lead"
EVENT_DEMO_REQUESTED = "demo_requested"
EVENT_TRIAL_STARTED = "trial_started"
EVENT_CHECKOUT_STARTED = "checkout_started"
EVENT_CHECKOUT_ABANDONED = "checkout_abandoned"
EVENT_PAYMENT_CONFIRMED = "payment_confirmed"

SUPPORTED_EVENTS = {
    EVENT_LEAD,
    EVENT_DEMO_REQUESTED,
    EVENT_TRIAL_STARTED,
    EVENT_CHECKOUT_STARTED,
    EVENT_CHECKOUT_ABANDONED,
    EVENT_PAYMENT_CONFIRMED,
}

INTENT_LOW = "dsg-intent-low"
INTENT_MEDIUM = "dsg-intent-medium"
INTENT_HIGH = "dsg-intent-high"
INTENT_TAGS = {INTENT_LOW, INTENT_MEDIUM, INTENT_HIGH}

EVENT_TAGS: dict[str, set[str]] = {
    EVENT_LEAD: {INTENT_LOW},
    EVENT_DEMO_REQUESTED: {INTENT_HIGH, "dsg-demo-requested"},
    EVENT_TRIAL_STARTED: {INTENT_HIGH, "dsg-trial"},
    EVENT_CHECKOUT_STARTED: {INTENT_HIGH, "dsg-checkout-started"},
    EVENT_CHECKOUT_ABANDONED: {"dsg-checkout-abandoned"},
    EVENT_PAYMENT_CONFIRMED: {
        "dsg-payment-confirmed",
        "dsg-customer",
        "dsg-onboarding",
    },
}

EVENT_INTENT: dict[str, Optional[str]] = {
    EVENT_LEAD: INTENT_LOW,
    EVENT_DEMO_REQUESTED: INTENT_HIGH,
    EVENT_TRIAL_STARTED: INTENT_HIGH,
    EVENT_CHECKOUT_STARTED: INTENT_HIGH,
    EVENT_CHECKOUT_ABANDONED: None,
    EVENT_PAYMENT_CONFIRMED: None,
}

EVENT_REMOVE_TAGS: dict[str, set[str]] = {
    EVENT_LEAD: set(),
    EVENT_DEMO_REQUESTED: set(),
    EVENT_TRIAL_STARTED: set(),
    EVENT_CHECKOUT_STARTED: {"dsg-checkout-abandoned"},
    EVENT_CHECKOUT_ABANDONED: {"dsg-checkout-started"},
    EVENT_PAYMENT_CONFIRMED: {
        *INTENT_TAGS,
        "dsg-checkout-started",
        "dsg-checkout-abandoned",
    },
}

HIGH_INTENT_ACTION: dict[str, str] = {
    EVENT_DEMO_REQUESTED: "Demo requested",
    EVENT_TRIAL_STARTED: "Trial started",
    EVENT_CHECKOUT_STARTED: "Checkout started",
    EVENT_CHECKOUT_ABANDONED: "Checkout abandoned",
    EVENT_PAYMENT_CONFIRMED: "Payment confirmed",
}


@dataclass(frozen=True)
class ActiveCampaignConfig:
    api_url: Optional[str]
    api_token: Optional[str]
    list_id: int = 4
    product_interest_field_id: int = 2
    lead_source_field_id: int = 3
    last_high_intent_field_id: int = 4
    account_id_field_id: int = 5
    timeout_seconds: float = 10.0

    @property
    def configured(self) -> bool:
        if not self.api_url or not self.api_token:
            return False
        parts = urlsplit(self.api_url)
        return (
            parts.scheme == "https"
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
        )


def _positive_int(source: dict[str, str], name: str, default: int) -> int:
    raw = (source.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def config_from_env(env: Optional[dict[str, str]] = None) -> ActiveCampaignConfig:
    source = env if env is not None else os.environ
    api_url = (source.get("ACTIVECAMPAIGN_API_URL") or "").strip().rstrip("/") or None
    api_token = (source.get("ACTIVECAMPAIGN_API_TOKEN") or "").strip() or None
    return ActiveCampaignConfig(
        api_url=api_url,
        api_token=api_token,
        list_id=_positive_int(source, "ACTIVECAMPAIGN_LIST_ID", 4),
        product_interest_field_id=_positive_int(
            source, "ACTIVECAMPAIGN_PRODUCT_INTEREST_FIELD_ID", 2
        ),
        lead_source_field_id=_positive_int(
            source, "ACTIVECAMPAIGN_LEAD_SOURCE_FIELD_ID", 3
        ),
        last_high_intent_field_id=_positive_int(
            source, "ACTIVECAMPAIGN_LAST_HIGH_INTENT_FIELD_ID", 4
        ),
        account_id_field_id=_positive_int(
            source, "ACTIVECAMPAIGN_ACCOUNT_ID_FIELD_ID", 5
        ),
    )


class ActiveCampaignSyncError(RuntimeError):
    pass


async def _request(
    client: httpx.AsyncClient,
    config: ActiveCampaignConfig,
    method: str,
    path: str,
    *,
    json: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
    allowed_statuses: frozenset[int] = frozenset({200, 201}),
) -> dict[str, Any]:
    assert config.api_url is not None
    assert config.api_token is not None
    try:
        response = await client.request(
            method,
            f"{config.api_url}{path}",
            json=json,
            params=params,
            headers={
                "Api-Token": config.api_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    except httpx.HTTPError as exc:
        raise ActiveCampaignSyncError(
            f"ActiveCampaign request failed: {type(exc).__name__}"
        ) from exc
    if response.status_code not in allowed_statuses:
        raise ActiveCampaignSyncError(
            f"ActiveCampaign {method} {path} returned HTTP {response.status_code}"
        )
    if response.status_code == 204 or not response.content:
        return {}
    try:
        body = response.json()
    except ValueError as exc:
        raise ActiveCampaignSyncError(
            f"ActiveCampaign {method} {path} returned non-JSON data"
        ) from exc
    if not isinstance(body, dict):
        raise ActiveCampaignSyncError(
            f"ActiveCampaign {method} {path} returned an invalid object"
        )
    return body


async def _resolve_tag_ids(
    client: httpx.AsyncClient,
    config: ActiveCampaignConfig,
    names: set[str],
) -> dict[str, int]:
    resolved: dict[str, int] = {}
    for name in sorted(names):
        body = await _request(
            client,
            config,
            "GET",
            "/api/3/tags",
            params={"search": name, "limit": 100},
        )
        exact = next(
            (
                tag
                for tag in body.get("tags", [])
                if isinstance(tag, dict) and tag.get("tag") == name
            ),
            None,
        )
        if not isinstance(exact, dict):
            raise ActiveCampaignSyncError(f"required ActiveCampaign tag is missing: {name}")
        try:
            resolved[name] = int(exact["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ActiveCampaignSyncError(
                f"required ActiveCampaign tag has no valid id: {name}"
            ) from exc
    return resolved


async def _current_tag_relations(
    client: httpx.AsyncClient,
    config: ActiveCampaignConfig,
    contact_id: int,
) -> dict[int, int]:
    body = await _request(
        client,
        config,
        "GET",
        f"/api/3/contacts/{contact_id}/contactTags",
        params={"limit": 100},
    )
    relations: dict[int, int] = {}
    for relation in body.get("contactTags", []):
        if not isinstance(relation, dict):
            continue
        try:
            relation_id = int(relation["id"])
            tag_id = int(relation["tag"])
        except (KeyError, TypeError, ValueError):
            continue
        relations[tag_id] = relation_id
    return relations


async def _ensure_list_subscription(
    client: httpx.AsyncClient,
    config: ActiveCampaignConfig,
    contact_id: int,
) -> None:
    """Subscribe once; repeated lifecycle events must not fail on duplicates."""
    body = await _request(
        client,
        config,
        "GET",
        "/api/3/contactLists",
        params={
            "filters[contact]": contact_id,
            "filters[list]": config.list_id,
            "limit": 100,
        },
    )
    exact = next(
        (
            item
            for item in body.get("contactLists", [])
            if isinstance(item, dict)
            and str(item.get("contact")) == str(contact_id)
            and str(item.get("list")) == str(config.list_id)
        ),
        None,
    )
    payload = {
        "contactList": {
            "list": str(config.list_id),
            "contact": str(contact_id),
            "status": 1,
        }
    }
    if exact is None:
        await _request(
            client,
            config,
            "POST",
            "/api/3/contactLists",
            json=payload,
        )
        return
    if str(exact.get("status")) == "1":
        return
    relation_id = exact.get("id")
    if relation_id is None:
        raise ActiveCampaignSyncError(
            "existing ActiveCampaign list membership has no id"
        )
    await _request(
        client,
        config,
        "PUT",
        f"/api/3/contactLists/{relation_id}",
        json=payload,
    )


def _field_values(
    config: ActiveCampaignConfig,
    account: Account,
    event: str,
    source: str,
) -> list[dict[str, str]]:
    values = [
        {"field": str(config.product_interest_field_id), "value": "DSG Verified Execution"},
        {"field": str(config.lead_source_field_id), "value": source},
        {"field": str(config.account_id_field_id), "value": account.account_id},
    ]
    action = HIGH_INTENT_ACTION.get(event)
    if action:
        values.append(
            {"field": str(config.last_high_intent_field_id), "value": action}
        )
    return values


async def _sync(
    config: ActiveCampaignConfig,
    *,
    account: Account,
    profile: Optional[MarketingProfile],
    event: str,
    source: str,
) -> dict[str, Any]:
    if event not in SUPPORTED_EVENTS:
        raise ActiveCampaignSyncError(f"unsupported marketing event: {event}")
    if profile is None:
        return {
            "sync_state": "SKIPPED_NO_PROFILE",
            "event": event,
            "detail": "the DSG account has no marketing profile",
        }
    if not config.configured:
        return {
            "sync_state": "PENDING_CONFIGURATION",
            "event": event,
            "detail": "ACTIVECAMPAIGN_API_URL and ACTIVECAMPAIGN_API_TOKEN are required",
        }
    if not profile.marketing_consent:
        return {
            "sync_state": "SKIPPED_NO_CONSENT",
            "event": event,
            "detail": "the marketing profile has not opted in to marketing email",
        }
    email = (profile.email or "").strip().lower()
    if not email:
        return {
            "sync_state": "SKIPPED_NO_EMAIL",
            "event": event,
            "detail": "the marketing profile has no contact email",
        }

    required_tag_names = set(EVENT_TAGS[event]) | set(EVENT_REMOVE_TAGS[event])
    desired_intent = EVENT_INTENT[event]
    if desired_intent:
        required_tag_names |= INTENT_TAGS

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        contact_body = await _request(
            client,
            config,
            "POST",
            "/api/3/contact/sync",
            json={
                "contact": {
                    "email": email,
                    "fieldValues": _field_values(config, account, event, source),
                }
            },
        )
        contact = contact_body.get("contact") or {}
        try:
            contact_id = int(contact["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ActiveCampaignSyncError(
                "ActiveCampaign contact sync returned no valid contact id"
            ) from exc

        await _ensure_list_subscription(client, config, contact_id)

        tag_ids = await _resolve_tag_ids(client, config, required_tag_names)
        current = await _current_tag_relations(client, config, contact_id)

        remove_names = set(EVENT_REMOVE_TAGS[event])
        if desired_intent:
            remove_names |= INTENT_TAGS - {desired_intent}

        removed: list[str] = []
        for name in sorted(remove_names):
            tag_id = tag_ids.get(name)
            relation_id = current.get(tag_id) if tag_id is not None else None
            if relation_id is None:
                continue
            await _request(
                client,
                config,
                "DELETE",
                f"/api/3/contactTags/{relation_id}",
                allowed_statuses=frozenset({200, 204}),
            )
            current.pop(tag_id, None)
            removed.append(name)

        added: list[str] = []
        for name in sorted(EVENT_TAGS[event]):
            tag_id = tag_ids[name]
            if tag_id in current:
                continue
            await _request(
                client,
                config,
                "POST",
                "/api/3/contactTags",
                json={
                    "contactTag": {
                        "contact": str(contact_id),
                        "tag": str(tag_id),
                    }
                },
            )
            added.append(name)

    return {
        "sync_state": "SYNCED",
        "event": event,
        "contact_id": contact_id,
        "list_id": config.list_id,
        "tags_added": added,
        "tags_removed": removed,
        "correlation": {"dsg_account_id": account.account_id},
    }


async def sync_account_event(
    account: Account,
    profile: Optional[MarketingProfile],
    *,
    event: str,
    source: Optional[str] = None,
    config: Optional[ActiveCampaignConfig] = None,
) -> dict[str, Any]:
    """Best-effort marketing sync that never changes DSG entitlement truth."""
    selected = config or config_from_env()
    try:
        return await _sync(
            selected,
            account=account,
            profile=profile,
            event=event,
            source=(source or (profile.source if profile else None) or account.channel or "api").strip()
            or "api",
        )
    except ActiveCampaignSyncError as exc:
        return {
            "sync_state": "FAILED",
            "event": event,
            "detail": str(exc),
        }


__all__ = [
    "ActiveCampaignConfig",
    "ActiveCampaignSyncError",
    "EVENT_LEAD",
    "EVENT_DEMO_REQUESTED",
    "EVENT_TRIAL_STARTED",
    "EVENT_CHECKOUT_STARTED",
    "EVENT_CHECKOUT_ABANDONED",
    "EVENT_PAYMENT_CONFIRMED",
    "SUPPORTED_EVENTS",
    "config_from_env",
    "sync_account_event",
]
