"""Server-side capability resolver for plan-authorized execution.

Callers may declare which capability an approved step needs, but they cannot
assert whether it is available. Availability is derived from trusted server
configuration. Secret values are never returned.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import Field

from .decision_core import CapabilityNeed
from .models import Strict


class CapabilityRequirement(Strict):
    capability: str = Field(min_length=1, max_length=128)


# Each capability maps to the environment/configuration names required to use
# that capability. Only presence/readiness is exposed, never secret contents.
_CAPABILITY_ENV: dict[str, tuple[str, ...]] = {
    "dsg_verifier": ("DSG_BACKEND_BASE_URL", "DSG_BACKEND_API_KEY"),
    "cinema_bridge": ("CINEMA_API_SECRET",),
    "revenue_admin": ("DSG_REVENUE_ADMIN_SECRET",),
    "stripe_api": ("STRIPE_SECRET_KEY",),
    "stripe_webhook": ("STRIPE_WEBHOOK_SECRET",),
    "azure_oidc": ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"),
    "sentry": ("SENTRY_DSN",),
}


def known_capabilities() -> list[str]:
    return sorted(_CAPABILITY_ENV)


def resolve_capability(requirement: CapabilityRequirement) -> CapabilityNeed:
    names = _CAPABILITY_ENV.get(requirement.capability)
    if names is None:
        return CapabilityNeed(
            capability=requirement.capability,
            available=False,
            source="dsg-capability-registry",
            remediation=(
                "Register a trusted server-side resolver for this capability; do not let the client "
                "self-assert availability."
            ),
        )

    missing = [name for name in names if not (os.getenv(name) or "").strip()]
    available = not missing
    if available:
        remediation = None
    else:
        remediation = "Configure the required server-side capability inputs: " + ", ".join(missing)

    return CapabilityNeed(
        capability=requirement.capability,
        available=available,
        source="server-environment",
        remediation=remediation,
    )


def resolve_capabilities(requirements: list[CapabilityRequirement]) -> list[CapabilityNeed]:
    return [resolve_capability(item) for item in requirements]


def capability_status() -> dict[str, Any]:
    results = [resolve_capability(CapabilityRequirement(capability=name)) for name in known_capabilities()]
    return {
        "known": len(results),
        "available": [item.capability for item in results if item.available],
        "pending": [item.capability for item in results if not item.available],
        "details": [item.model_dump(mode="json") for item in results],
        "secrets_exposed": False,
    }


__all__ = [
    "CapabilityRequirement",
    "capability_status",
    "known_capabilities",
    "resolve_capabilities",
    "resolve_capability",
]
