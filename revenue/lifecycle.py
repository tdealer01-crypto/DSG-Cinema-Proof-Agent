"""Deterministic revenue lifecycle state machine.

This module is deliberately side-effect free. It decides whether a requested
state transition is structurally valid and requires authoritative Stripe proof
before entering CUSTOMER. Network/API mutations are integration-layer work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class LifecycleError(RuntimeError):
    """Base lifecycle transition error."""


class IllegalTransitionError(LifecycleError):
    """Raised when the requested state edge is not part of the contract."""


class PaymentProofError(LifecycleError):
    """Raised when CUSTOMER is requested without authoritative payment proof."""


class RevenueState(str, Enum):
    LEAD = "LEAD"
    ENGAGED = "ENGAGED"
    QUALIFIED = "QUALIFIED"
    TRIAL_OR_DEMO = "TRIAL_OR_DEMO"
    CHECKOUT_STARTED = "CHECKOUT_STARTED"
    ABANDONED = "ABANDONED"
    CUSTOMER = "CUSTOMER"
    ONBOARDING = "ONBOARDING"
    ACTIVE_CUSTOMER = "ACTIVE_CUSTOMER"
    EXPANSION = "EXPANSION"


_ALLOWED: dict[RevenueState, frozenset[RevenueState]] = {
    RevenueState.LEAD: frozenset({RevenueState.ENGAGED}),
    RevenueState.ENGAGED: frozenset({RevenueState.QUALIFIED}),
    RevenueState.QUALIFIED: frozenset(
        {RevenueState.TRIAL_OR_DEMO, RevenueState.CHECKOUT_STARTED}
    ),
    RevenueState.TRIAL_OR_DEMO: frozenset({RevenueState.CHECKOUT_STARTED}),
    RevenueState.CHECKOUT_STARTED: frozenset(
        {RevenueState.CUSTOMER, RevenueState.ABANDONED}
    ),
    RevenueState.ABANDONED: frozenset({RevenueState.CHECKOUT_STARTED}),
    RevenueState.CUSTOMER: frozenset({RevenueState.ONBOARDING}),
    RevenueState.ONBOARDING: frozenset({RevenueState.ACTIVE_CUSTOMER}),
    RevenueState.ACTIVE_CUSTOMER: frozenset({RevenueState.EXPANSION}),
    RevenueState.EXPANSION: frozenset(),
}

_STRIPE_STATUS_BY_SOURCE: dict[str, str] = {
    "stripe_checkout_session": "paid",
    "stripe_payment_intent": "succeeded",
    "stripe_paid_invoice": "paid",
}


@dataclass(frozen=True)
class PaymentProof:
    account_id: str
    source: str
    source_id: str
    livemode: bool
    status: str
    verified: bool
    evidence_ref: str

    def is_authoritative_for(self, account_id: str) -> bool:
        expected_status = _STRIPE_STATUS_BY_SOURCE.get(self.source)
        return (
            self.account_id == account_id
            and expected_status is not None
            and bool(self.source_id.strip())
            and self.livemode is True
            and self.verified is True
            and self.status == expected_status
            and bool(self.evidence_ref.strip())
        )


@dataclass(frozen=True)
class LifecycleTransition:
    account_id: str
    from_state: RevenueState
    to_state: RevenueState
    reason: str
    evidence_ref: str
    payment_source: str | None = None
    payment_source_id: str | None = None

    def public_view(self) -> dict[str, Any]:
        data = asdict(self)
        data["from_state"] = self.from_state.value
        data["to_state"] = self.to_state.value
        return data


def allowed_next_states(state: RevenueState) -> tuple[RevenueState, ...]:
    return tuple(sorted(_ALLOWED[state], key=lambda item: item.value))


def transition(
    *,
    account_id: str,
    current: RevenueState,
    target: RevenueState,
    reason: str,
    evidence_ref: str,
    payment_proof: PaymentProof | None = None,
) -> LifecycleTransition:
    """Validate and return one immutable lifecycle transition.

    The caller must persist/apply the returned transition separately. This keeps
    the gate deterministic and prevents a model/client from mutating state just
    by asking for a transition.
    """

    account_id = account_id.strip()
    reason = reason.strip()
    evidence_ref = evidence_ref.strip()
    if not account_id:
        raise ValueError("account_id is required")
    if not reason:
        raise ValueError("reason is required")
    if not evidence_ref:
        raise ValueError("evidence_ref is required")

    if target not in _ALLOWED[current]:
        raise IllegalTransitionError(
            f"illegal revenue lifecycle transition: {current.value} -> {target.value}"
        )

    if target == RevenueState.CUSTOMER:
        if payment_proof is None or not payment_proof.is_authoritative_for(account_id):
            raise PaymentProofError(
                "CUSTOMER requires verified live Stripe payment evidence bound to the account"
            )
        return LifecycleTransition(
            account_id=account_id,
            from_state=current,
            to_state=target,
            reason=reason,
            evidence_ref=evidence_ref,
            payment_source=payment_proof.source,
            payment_source_id=payment_proof.source_id,
        )

    return LifecycleTransition(
        account_id=account_id,
        from_state=current,
        to_state=target,
        reason=reason,
        evidence_ref=evidence_ref,
    )
