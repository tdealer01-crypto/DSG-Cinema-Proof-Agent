"""Canonical, side-effect-free routing for revenue signals.

This module is the contract between inbound event capture and downstream DSG
policy. It does not persist state, call Stripe/ActiveCampaign, or send messages.
Trusted payment signals are explicitly marked so a client request cannot become
payment truth merely by naming a signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .lifecycle import RevenueState
from .messaging_policy import MessageSequence


class RevenueSignal(str, Enum):
    LEAD_CREATED = "lead_created"
    EMAIL_CLICK = "email_click"
    PRICING_VISIT = "pricing_visit"
    DEMO_REQUESTED = "demo_requested"
    TRIAL_STARTED = "trial_started"
    CHECKOUT_STARTED = "checkout_started"
    CHECKOUT_ABANDONED = "checkout_abandoned"
    PAYMENT_CONFIRMED = "payment_confirmed"
    ONBOARDING_STARTED = "onboarding_started"
    ONBOARDING_COMPLETED = "onboarding_completed"
    EXPANSION_SIGNAL = "expansion_signal"


class SignalContractError(ValueError):
    """Raised when an unknown or unauthorized signal is requested."""


@dataclass(frozen=True)
class SignalRoute:
    signal: RevenueSignal
    initialize_state: RevenueState | None
    lifecycle_target: RevenueState | None
    intent_event: str | None
    activecampaign_event: str | None
    candidate_sequence: MessageSequence | None
    requires_payment_proof: bool = False
    trusted_source_only: bool = False

    def public_view(self) -> dict[str, object]:
        return {
            "signal": self.signal.value,
            "initialize_state": self.initialize_state.value if self.initialize_state else None,
            "lifecycle_target": self.lifecycle_target.value if self.lifecycle_target else None,
            "intent_event": self.intent_event,
            "activecampaign_event": self.activecampaign_event,
            "candidate_sequence": self.candidate_sequence.value if self.candidate_sequence else None,
            "requires_payment_proof": self.requires_payment_proof,
            "trusted_source_only": self.trusted_source_only,
        }


_ROUTES: dict[RevenueSignal, SignalRoute] = {
    RevenueSignal.LEAD_CREATED: SignalRoute(
        signal=RevenueSignal.LEAD_CREATED,
        initialize_state=RevenueState.LEAD,
        lifecycle_target=None,
        intent_event="lead_created",
        activecampaign_event="lead",
        candidate_sequence=MessageSequence.SALES_NURTURE,
    ),
    RevenueSignal.EMAIL_CLICK: SignalRoute(
        signal=RevenueSignal.EMAIL_CLICK,
        initialize_state=None,
        lifecycle_target=RevenueState.ENGAGED,
        intent_event="email_click",
        activecampaign_event=None,
        candidate_sequence=MessageSequence.SALES_NURTURE,
    ),
    RevenueSignal.PRICING_VISIT: SignalRoute(
        signal=RevenueSignal.PRICING_VISIT,
        initialize_state=None,
        lifecycle_target=RevenueState.QUALIFIED,
        intent_event="pricing_visit",
        activecampaign_event=None,
        candidate_sequence=MessageSequence.SALES_NURTURE,
    ),
    RevenueSignal.DEMO_REQUESTED: SignalRoute(
        signal=RevenueSignal.DEMO_REQUESTED,
        initialize_state=None,
        lifecycle_target=RevenueState.TRIAL_OR_DEMO,
        intent_event="demo_requested",
        activecampaign_event="demo_requested",
        candidate_sequence=MessageSequence.SALES_NURTURE,
    ),
    RevenueSignal.TRIAL_STARTED: SignalRoute(
        signal=RevenueSignal.TRIAL_STARTED,
        initialize_state=None,
        lifecycle_target=RevenueState.TRIAL_OR_DEMO,
        intent_event="trial_started",
        activecampaign_event="trial_started",
        candidate_sequence=MessageSequence.SALES_NURTURE,
    ),
    RevenueSignal.CHECKOUT_STARTED: SignalRoute(
        signal=RevenueSignal.CHECKOUT_STARTED,
        initialize_state=None,
        lifecycle_target=RevenueState.CHECKOUT_STARTED,
        intent_event="checkout_started",
        activecampaign_event="checkout_started",
        candidate_sequence=None,
    ),
    RevenueSignal.CHECKOUT_ABANDONED: SignalRoute(
        signal=RevenueSignal.CHECKOUT_ABANDONED,
        initialize_state=None,
        lifecycle_target=RevenueState.ABANDONED,
        intent_event=None,
        activecampaign_event="checkout_abandoned",
        candidate_sequence=MessageSequence.CHECKOUT_RECOVERY,
    ),
    RevenueSignal.PAYMENT_CONFIRMED: SignalRoute(
        signal=RevenueSignal.PAYMENT_CONFIRMED,
        initialize_state=None,
        lifecycle_target=RevenueState.CUSTOMER,
        intent_event=None,
        activecampaign_event="payment_confirmed",
        candidate_sequence=MessageSequence.ONBOARDING,
        requires_payment_proof=True,
        trusted_source_only=True,
    ),
    RevenueSignal.ONBOARDING_STARTED: SignalRoute(
        signal=RevenueSignal.ONBOARDING_STARTED,
        initialize_state=None,
        lifecycle_target=RevenueState.ONBOARDING,
        intent_event=None,
        activecampaign_event=None,
        candidate_sequence=MessageSequence.ONBOARDING,
    ),
    RevenueSignal.ONBOARDING_COMPLETED: SignalRoute(
        signal=RevenueSignal.ONBOARDING_COMPLETED,
        initialize_state=None,
        lifecycle_target=RevenueState.ACTIVE_CUSTOMER,
        intent_event=None,
        activecampaign_event=None,
        candidate_sequence=None,
    ),
    RevenueSignal.EXPANSION_SIGNAL: SignalRoute(
        signal=RevenueSignal.EXPANSION_SIGNAL,
        initialize_state=None,
        lifecycle_target=RevenueState.EXPANSION,
        intent_event=None,
        activecampaign_event=None,
        candidate_sequence=MessageSequence.EXPANSION,
    ),
}


def route_signal(signal: RevenueSignal | str) -> SignalRoute:
    """Resolve a canonical signal or fail closed for unknown input."""
    try:
        parsed = signal if isinstance(signal, RevenueSignal) else RevenueSignal(str(signal).strip())
    except ValueError as exc:
        raise SignalContractError(f"unsupported revenue signal: {signal!r}") from exc
    return _ROUTES[parsed]


def authorize_signal_source(
    signal: RevenueSignal | str,
    *,
    trusted_source: bool,
) -> SignalRoute:
    """Resolve a signal and enforce its source-trust boundary."""
    route = route_signal(signal)
    if route.trusted_source_only and not trusted_source:
        raise SignalContractError(
            f"{route.signal.value} requires a trusted backend source"
        )
    return route


__all__ = [
    "RevenueSignal",
    "SignalContractError",
    "SignalRoute",
    "route_signal",
    "authorize_signal_source",
]
