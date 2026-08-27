"""Projection-based ActiveCampaign mutation downstream of DSG truth."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .accounts import Account
from .activecampaign_projection import ActiveCampaignProjection
from .activecampaign_sync import (
    ActiveCampaignConfig,
    ActiveCampaignSyncError,
    _current_tag_relations,
    _ensure_list_subscription,
    _request,
    _resolve_tag_ids,
    config_from_env,
)
from .marketing_profiles import MarketingProfile

_ACTION_LABELS = {
    "demo_requested": "Demo requested",
    "trial_started": "Trial started",
    "checkout_started": "Checkout started",
    "checkout_abandoned": "Checkout abandoned",
    "payment_confirmed": "Payment confirmed",
    "expansion_signal": "Expansion signal",
}


def _field_values(
    config: ActiveCampaignConfig,
    account: Account,
    *,
    source: str,
    signal: Optional[str],
) -> list[dict[str, str]]:
    values = [
        {"field": str(config.product_interest_field_id), "value": "DSG Verified Execution"},
        {"field": str(config.lead_source_field_id), "value": source},
        {"field": str(config.account_id_field_id), "value": account.account_id},
    ]
    action = _ACTION_LABELS.get((signal or "").strip())
    if action:
        values.append(
            {"field": str(config.last_high_intent_field_id), "value": action}
        )
    return values


async def _sync_projection(
    config: ActiveCampaignConfig,
    *,
    account: Account,
    profile: Optional[MarketingProfile],
    projection: ActiveCampaignProjection,
    source: str,
    signal: Optional[str],
) -> dict[str, Any]:
    if profile is None:
        return {
            "sync_state": "SKIPPED_NO_PROFILE",
            "detail": "the DSG account has no marketing profile",
        }
    if not config.configured:
        return {
            "sync_state": "PENDING_CONFIGURATION",
            "detail": "ACTIVECAMPAIGN_API_URL and ACTIVECAMPAIGN_API_TOKEN are required",
        }
    if not profile.marketing_consent:
        return {
            "sync_state": "SKIPPED_NO_CONSENT",
            "detail": "the marketing profile has not opted in to marketing email",
        }
    email = (profile.email or "").strip().lower()
    if not email:
        return {
            "sync_state": "SKIPPED_NO_EMAIL",
            "detail": "the marketing profile has no contact email",
        }

    desired = set(projection.desired_tags)
    remove = set(projection.remove_tags)
    required = desired | remove

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        contact_body = await _request(
            client,
            config,
            "POST",
            "/api/3/contact/sync",
            json={
                "contact": {
                    "email": email,
                    "fieldValues": _field_values(
                        config,
                        account,
                        source=source,
                        signal=signal,
                    ),
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

        tag_ids = (
            await _resolve_tag_ids(client, config, required)
            if required
            else {}
        )
        current = await _current_tag_relations(client, config, contact_id)

        removed: list[str] = []
        for name in sorted(remove):
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
        for name in sorted(desired):
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
            current[tag_id] = -1
            added.append(name)

    return {
        "sync_state": "SYNCED",
        "contact_id": contact_id,
        "list_id": config.list_id,
        "tags_added": added,
        "tags_removed": removed,
        "projection": projection.public_view(),
        "correlation": {"dsg_account_id": account.account_id},
    }


async def sync_account_projection(
    account: Account,
    profile: Optional[MarketingProfile],
    *,
    projection: ActiveCampaignProjection,
    source: Optional[str] = None,
    signal: Optional[str] = None,
    config: Optional[ActiveCampaignConfig] = None,
) -> dict[str, Any]:
    """Apply an already-computed DSG projection without re-deriving CRM truth."""

    selected = config or config_from_env()
    selected_source = (
        source
        or (profile.source if profile else None)
        or account.channel
        or "api"
    ).strip() or "api"
    try:
        return await _sync_projection(
            selected,
            account=account,
            profile=profile,
            projection=projection,
            source=selected_source,
            signal=signal,
        )
    except ActiveCampaignSyncError as exc:
        return {
            "sync_state": "FAILED",
            "detail": str(exc),
            "projection": projection.public_view(),
        }


__all__ = ["sync_account_projection"]
