"""Deterministic price catalog for DSG Verified Execution.

All money is represented in micro-USD integers (1 USD = 1_000_000 micros) so
pricing never depends on floating point. The unit that is sold is a single
verified proof receipt; a receipt is only billable when Z3 proved
VERIFIED_GLOBAL_OPTIMUM.

GitHub Marketplace subscription plans are entitlement-only inside Cinema. GitHub
collects their subscription payment, so these plans deliberately carry a zero
Cinema unit price and never require a Stripe payment link. They are kept out of
the public direct-billing catalog to prevent a Marketplace entitlement from
being mistaken for a Stripe checkout plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MICROS_PER_USD = 1_000_000


@dataclass(frozen=True)
class Sku:
    sku: str
    title: str
    list_price_micros: int


@dataclass(frozen=True)
class Plan:
    plan: str
    title: str
    base_price_micros: int
    included_units: int
    unit_price_micros: Optional[int]
    hard_cap_units: Optional[int]
    requires_linked_payment: bool


SKU_CATALOG: dict[str, Sku] = {
    "verified_execution": Sku(
        sku="verified_execution",
        title="Verified Execution proof receipt",
        list_price_micros=50_000,
    ),
    "stripe_policy_decision": Sku(
        sku="stripe_policy_decision",
        title="Stripe policy decision proof",
        list_price_micros=100_000,
    ),
}

# Direct/Stripe-visible plans only. ``catalog_snapshot`` intentionally exposes
# this dictionary and not the Marketplace entitlement catalog below.
PLAN_CATALOG: dict[str, Plan] = {
    "free": Plan(
        plan="free",
        title="Free evaluation",
        base_price_micros=0,
        included_units=25,
        unit_price_micros=0,
        hard_cap_units=25,
        requires_linked_payment=False,
    ),
    "metered": Plan(
        plan="metered",
        title="Pay per verified proof",
        base_price_micros=0,
        included_units=0,
        unit_price_micros=None,
        hard_cap_units=None,
        requires_linked_payment=True,
    ),
    "team": Plan(
        plan="team",
        title="Team subscription",
        base_price_micros=490 * MICROS_PER_USD,
        included_units=5_000,
        unit_price_micros=80_000,
        hard_cap_units=None,
        requires_linked_payment=True,
    ),
    "enterprise": Plan(
        plan="enterprise",
        title="Enterprise contract",
        base_price_micros=0,
        included_units=0,
        unit_price_micros=None,
        hard_cap_units=None,
        requires_linked_payment=False,
    ),
}

# Migrated from the retired Control Plane Marketplace entitlement policy.
# Prices are deliberately absent here: GitHub is the merchant of record. Only
# bounded proof entitlement belongs inside Cinema.
GITHUB_MARKETPLACE_PLAN_CATALOG: dict[str, Plan] = {
    "github_free": Plan(
        plan="github_free",
        title="GitHub Marketplace Free",
        base_price_micros=0,
        included_units=1_000,
        unit_price_micros=0,
        hard_cap_units=1_000,
        requires_linked_payment=False,
    ),
    "github_pro": Plan(
        plan="github_pro",
        title="GitHub Marketplace Pro",
        base_price_micros=0,
        included_units=10_000,
        unit_price_micros=0,
        hard_cap_units=10_000,
        requires_linked_payment=False,
    ),
    "github_business": Plan(
        plan="github_business",
        title="GitHub Marketplace Business",
        base_price_micros=0,
        included_units=100_000,
        unit_price_micros=0,
        hard_cap_units=100_000,
        requires_linked_payment=False,
    ),
    "github_enterprise": Plan(
        plan="github_enterprise",
        title="GitHub Marketplace Enterprise",
        base_price_micros=0,
        included_units=1_000_000,
        unit_price_micros=0,
        hard_cap_units=1_000_000,
        requires_linked_payment=False,
    ),
}

DEFAULT_PLAN = "free"


def get_plan(plan: str) -> Plan:
    found = PLAN_CATALOG.get(plan) or GITHUB_MARKETPLACE_PLAN_CATALOG.get(plan)
    if found is None:
        raise ValueError(f"unknown plan: {plan}")
    return found


def get_sku(sku: str) -> Sku:
    try:
        return SKU_CATALOG[sku]
    except KeyError as exc:
        raise ValueError(f"unknown sku: {sku}") from exc


def resolve_unit_price_micros(
    plan: Plan,
    sku: Sku,
    account_unit_price_micros: Optional[int] = None,
) -> int:
    """Resolve the per-unit price with account override taking precedence."""
    if account_unit_price_micros is not None:
        if account_unit_price_micros < 0:
            raise ValueError("account unit price must not be negative")
        return account_unit_price_micros
    if plan.unit_price_micros is not None:
        return plan.unit_price_micros
    return sku.list_price_micros


def unit_amount_micros(
    plan: Plan,
    unit_price_micros: int,
    units_before: int,
    quantity: int,
) -> int:
    """Price `quantity` units when `units_before` are already used this period.

    Included units are consumed in ledger order, so the amount attached to a
    ledger entry never changes after it is appended.
    """
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    if units_before < 0:
        raise ValueError("units_before must not be negative")

    remaining_included = max(plan.included_units - units_before, 0)
    billable = max(quantity - remaining_included, 0)
    return billable * unit_price_micros


def micros_to_usd_string(micros: int) -> str:
    """Render micro-USD as an exact decimal string without float arithmetic."""
    sign = "-" if micros < 0 else ""
    value = abs(micros)
    whole, fraction = divmod(value, MICROS_PER_USD)
    return f"{sign}{whole}.{fraction:06d}"


def catalog_snapshot() -> dict:
    return {
        "currency": "USD",
        "micros_per_unit": MICROS_PER_USD,
        "skus": [
            {
                "sku": sku.sku,
                "title": sku.title,
                "list_price_micros": sku.list_price_micros,
                "list_price_usd": micros_to_usd_string(sku.list_price_micros),
            }
            for sku in SKU_CATALOG.values()
        ],
        "plans": [
            {
                "plan": plan.plan,
                "title": plan.title,
                "base_price_micros": plan.base_price_micros,
                "base_price_usd": micros_to_usd_string(plan.base_price_micros),
                "included_units": plan.included_units,
                "unit_price_micros": plan.unit_price_micros,
                "hard_cap_units": plan.hard_cap_units,
                "requires_linked_payment": plan.requires_linked_payment,
            }
            for plan in PLAN_CATALOG.values()
        ],
    }
