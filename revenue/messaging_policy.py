"""Consent-aware, fail-closed messaging eligibility policy.

The policy only decides eligibility. It never sends network requests or enrolls
contacts by itself, which keeps messaging side effects behind an integration
layer and makes customer/sales suppression independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MessageSequence(str, Enum):
    SALES_NURTURE = "SALES_NURTURE"
    CHECKOUT_RECOVERY = "CHECKOUT_RECOVERY"
    ONBOARDING = "ONBOARDING"
    EXPANSION = "EXPANSION"


KNOWN_STATES = frozenset(
    {
        "LEAD",
        "ENGAGED",
        "QUALIFIED",
        "TRIAL_OR_DEMO",
        "CHECKOUT_STARTED",
        "ABANDONED",
        "CUSTOMER",
        "ONBOARDING",
        "ACTIVE_CUSTOMER",
        "EXPANSION",
    }
)

SALES_STATES = frozenset({"LEAD", "ENGAGED", "QUALIFIED", "TRIAL_OR_DEMO"})


@dataclass(frozen=True)
class MessagingDecision:
    allowed: bool
    sequence: MessageSequence | None
    reason: str

    def public_view(self) -> dict[str, str | bool | None]:
        return {
            "allowed": self.allowed,
            "sequence": self.sequence.value if self.sequence else None,
            "reason": self.reason,
        }


def decide_messaging(
    *,
    state: str,
    requested_sequence: MessageSequence | str,
    marketing_consent: bool,
    abandonment_confirmed: bool = False,
    expansion_signal: bool = False,
) -> MessagingDecision:
    state = str(state).strip().upper()
    try:
        sequence = (
            requested_sequence
            if isinstance(requested_sequence, MessageSequence)
            else MessageSequence(str(requested_sequence).strip().upper())
        )
    except ValueError:
        return MessagingDecision(False, None, "UNKNOWN_SEQUENCE_FAIL_CLOSED")

    if state not in KNOWN_STATES:
        return MessagingDecision(False, sequence, "UNKNOWN_STATE_FAIL_CLOSED")

    if not marketing_consent:
        return MessagingDecision(False, sequence, "NO_MARKETING_CONSENT")

    if sequence == MessageSequence.SALES_NURTURE:
        if state in SALES_STATES:
            return MessagingDecision(True, sequence, "SALES_NURTURE_ELIGIBLE")
        return MessagingDecision(False, sequence, "SALES_NURTURE_SUPPRESSED_FOR_STATE")

    if sequence == MessageSequence.CHECKOUT_RECOVERY:
        if state == "ABANDONED":
            return MessagingDecision(True, sequence, "ABANDONED_CHECKOUT_RECOVERY")
        if state == "CHECKOUT_STARTED" and abandonment_confirmed:
            return MessagingDecision(True, sequence, "CONFIRMED_CHECKOUT_ABANDONMENT")
        return MessagingDecision(False, sequence, "CHECKOUT_RECOVERY_REQUIRES_ABANDONMENT")

    if sequence == MessageSequence.ONBOARDING:
        if state in {"CUSTOMER", "ONBOARDING"}:
            return MessagingDecision(True, sequence, "CUSTOMER_ONBOARDING_ELIGIBLE")
        return MessagingDecision(False, sequence, "ONBOARDING_REQUIRES_CUSTOMER")

    if sequence == MessageSequence.EXPANSION:
        if state in {"ACTIVE_CUSTOMER", "EXPANSION"} and expansion_signal:
            return MessagingDecision(True, sequence, "EXPANSION_SIGNAL_VERIFIED")
        if state not in {"ACTIVE_CUSTOMER", "EXPANSION"}:
            return MessagingDecision(False, sequence, "EXPANSION_REQUIRES_ACTIVE_CUSTOMER")
        return MessagingDecision(False, sequence, "EXPANSION_SIGNAL_REQUIRED")

    return MessagingDecision(False, sequence, "UNREACHABLE_FAIL_CLOSED")
