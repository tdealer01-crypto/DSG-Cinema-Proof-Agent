"""Deterministic ActiveCampaign projection derived from DSG truth.

The projection is deliberately side-effect free. It computes desired/removal tag
sets and messaging eligibility from lifecycle + intent state; it never reads
ActiveCampaign to infer entitlement or payment and never performs network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .intent import INTENT_TAGS, IntentEvaluation, exclusive_intent_tag
from .lifecycle import RevenueState
from .messaging_policy import MessageSequence, MessagingDecision, decide_messaging


class ActiveCampaignProjectionError(ValueError):
    """Raised when projection inputs are structurally inconsistent."""


INTENT_TAG_NAMES = frozenset(INTENT_TAGS.values())
CHECKOUT_TAGS = frozenset({"dsg-checkout-started", "dsg-checkout-abandoned"})
CUSTOMER_TAGS = frozenset({"dsg-customer", "dsg-onboarding", "dsg-payment-confirmed"})
KNOWN_FACTS = frozenset(
    {
        "demo_requested",
        "trial_started",
        "checkout_started",
        "checkout_abandoned",
        "payment_confirmed",
        "expansion_signal",
    }
)
PRE_CUSTOMER_STATES = frozenset(
    {
        RevenueState.LEAD,
        RevenueState.ENGAGED,
        RevenueState.QUALIFIED,
        RevenueState.TRIAL_OR_DEMO,
        RevenueState.CHECKOUT_STARTED,
        RevenueState.ABANDONED,
    }
)


@dataclass(frozen=True)
class ActiveCampaignProjection:
    state: RevenueState
    desired_tags: frozenset[str]
    remove_tags: frozenset[str]
    messaging: MessagingDecision
    marketing_consent: bool

    def public_view(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "desired_tags": sorted(self.desired_tags),
            "remove_tags": sorted(self.remove_tags),
            "marketing_consent": self.marketing_consent,
            "messaging": self.messaging.public_view(),
        }


def _parse_state(state: RevenueState | str) -> RevenueState:
    if isinstance(state, RevenueState):
        return state
    try:
        return RevenueState(str(state).strip().upper())
    except ValueError as exc:
        raise ActiveCampaignProjectionError(f"unknown revenue lifecycle state: {state!r}") from exc


def _validated_facts(facts: Iterable[str]) -> frozenset[str]:
    normalized = frozenset(str(item).strip().lower() for item in facts if str(item).strip())
    unknown = normalized - KNOWN_FACTS
    if unknown:
        raise ActiveCampaignProjectionError(
            f"unknown lifecycle facts: {', '.join(sorted(unknown))}"
        )
    return normalized


def _messaging_decision(
    *,
    state: RevenueState,
    marketing_consent: bool,
    facts: frozenset[str],
) -> MessagingDecision:
    if state in {
        RevenueState.LEAD,
        RevenueState.ENGAGED,
        RevenueState.QUALIFIED,
        RevenueState.TRIAL_OR_DEMO,
    }:
        sequence = MessageSequence.SALES_NURTURE
    elif state == RevenueState.ABANDONED:
        sequence = MessageSequence.CHECKOUT_RECOVERY
    elif state in {RevenueState.CUSTOMER, RevenueState.ONBOARDING}:
        sequence = MessageSequence.ONBOARDING
    elif state in {RevenueState.ACTIVE_CUSTOMER, RevenueState.EXPANSION}:
        sequence = MessageSequence.EXPANSION
    else:
        # CHECKOUT_STARTED must not be treated as abandoned without evidence.
        sequence = MessageSequence.CHECKOUT_RECOVERY

    return decide_messaging(
        state=state.value,
        requested_sequence=sequence,
        marketing_consent=marketing_consent,
        abandonment_confirmed="checkout_abandoned" in facts,
        expansion_signal="expansion_signal" in facts,
    )


def project_activecampaign(
    *,
    state: RevenueState | str,
    intent: IntentEvaluation,
    marketing_consent: bool,
    lifecycle_facts: Iterable[str] = (),
) -> ActiveCampaignProjection:
    """Project exact CRM tag intent without performing any remote mutation."""

    selected_state = _parse_state(state)
    facts = _validated_facts(lifecycle_facts)
    expected_intent_tag = exclusive_intent_tag(intent.score)
    if intent.selected_tag != expected_intent_tag:
        raise ActiveCampaignProjectionError(
            "intent evaluation selected_tag does not match deterministic score"
        )

    desired: set[str] = set()
    remove: set[str] = set()

    if selected_state in PRE_CUSTOMER_STATES:
        desired.add(expected_intent_tag)
        remove.update(INTENT_TAG_NAMES - {expected_intent_tag})
    else:
        remove.update(INTENT_TAG_NAMES)

    if "demo_requested" in facts and selected_state in PRE_CUSTOMER_STATES:
        desired.add("dsg-demo-requested")
    if "trial_started" in facts and selected_state in PRE_CUSTOMER_STATES:
        desired.add("dsg-trial")

    if selected_state == RevenueState.CHECKOUT_STARTED:
        desired.add("dsg-checkout-started")
        remove.add("dsg-checkout-abandoned")
    elif selected_state == RevenueState.ABANDONED:
        desired.add("dsg-checkout-abandoned")
        remove.add("dsg-checkout-started")
    elif selected_state in {RevenueState.CUSTOMER, RevenueState.ONBOARDING}:
        # CUSTOMER itself is authoritative DSG lifecycle truth; AC does not
        # grant this state. Project customer/onboarding tags downstream only.
        desired.update({"dsg-customer", "dsg-onboarding"})
        remove.update(CHECKOUT_TAGS | INTENT_TAG_NAMES)
        if "payment_confirmed" in facts:
            desired.add("dsg-payment-confirmed")
    elif selected_state in {RevenueState.ACTIVE_CUSTOMER, RevenueState.EXPANSION}:
        desired.add("dsg-customer")
        remove.update(CHECKOUT_TAGS | INTENT_TAG_NAMES | {"dsg-onboarding"})
        if "payment_confirmed" in facts:
            desired.add("dsg-payment-confirmed")

    # Never request removal of a tag that is simultaneously desired.
    remove.difference_update(desired)

    messaging = _messaging_decision(
        state=selected_state,
        marketing_consent=bool(marketing_consent),
        facts=facts,
    )
    return ActiveCampaignProjection(
        state=selected_state,
        desired_tags=frozenset(desired),
        remove_tags=frozenset(remove),
        messaging=messaging,
        marketing_consent=bool(marketing_consent),
    )


__all__ = [
    "ActiveCampaignProjection",
    "ActiveCampaignProjectionError",
    "project_activecampaign",
]
