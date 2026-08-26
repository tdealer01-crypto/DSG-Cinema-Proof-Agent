from __future__ import annotations

from revenue.messaging_policy import MessageSequence, decide_messaging


def test_no_consent_suppresses_all_sequences():
    for sequence in MessageSequence:
        decision = decide_messaging(
            state="LEAD",
            requested_sequence=sequence,
            marketing_consent=False,
            abandonment_confirmed=True,
            expansion_signal=True,
        )
        assert decision.allowed is False
        assert decision.reason == "NO_MARKETING_CONSENT"


def test_sales_nurture_stops_after_customer_transition():
    for state in ["CUSTOMER", "ONBOARDING", "ACTIVE_CUSTOMER", "EXPANSION"]:
        decision = decide_messaging(
            state=state,
            requested_sequence=MessageSequence.SALES_NURTURE,
            marketing_consent=True,
        )
        assert decision.allowed is False
        assert decision.reason == "SALES_NURTURE_SUPPRESSED_FOR_STATE"


def test_sales_nurture_allowed_for_pre_customer_states():
    for state in ["LEAD", "ENGAGED", "QUALIFIED", "TRIAL_OR_DEMO"]:
        assert decide_messaging(
            state=state,
            requested_sequence="sales_nurture",
            marketing_consent=True,
        ).allowed is True


def test_checkout_recovery_requires_abandonment():
    pending = decide_messaging(
        state="CHECKOUT_STARTED",
        requested_sequence="checkout_recovery",
        marketing_consent=True,
    )
    assert pending.allowed is False
    assert pending.reason == "CHECKOUT_RECOVERY_REQUIRES_ABANDONMENT"

    confirmed = decide_messaging(
        state="CHECKOUT_STARTED",
        requested_sequence="checkout_recovery",
        marketing_consent=True,
        abandonment_confirmed=True,
    )
    assert confirmed.allowed is True

    abandoned = decide_messaging(
        state="ABANDONED",
        requested_sequence="checkout_recovery",
        marketing_consent=True,
    )
    assert abandoned.allowed is True


def test_onboarding_only_for_customer_states():
    assert decide_messaging(
        state="CUSTOMER",
        requested_sequence="onboarding",
        marketing_consent=True,
    ).allowed is True
    assert decide_messaging(
        state="ONBOARDING",
        requested_sequence="onboarding",
        marketing_consent=True,
    ).allowed is True
    assert decide_messaging(
        state="QUALIFIED",
        requested_sequence="onboarding",
        marketing_consent=True,
    ).allowed is False


def test_expansion_requires_active_customer_and_signal():
    no_signal = decide_messaging(
        state="ACTIVE_CUSTOMER",
        requested_sequence="expansion",
        marketing_consent=True,
        expansion_signal=False,
    )
    assert no_signal.allowed is False
    assert no_signal.reason == "EXPANSION_SIGNAL_REQUIRED"

    allowed = decide_messaging(
        state="ACTIVE_CUSTOMER",
        requested_sequence="expansion",
        marketing_consent=True,
        expansion_signal=True,
    )
    assert allowed.allowed is True


def test_unknown_state_and_sequence_fail_closed():
    assert decide_messaging(
        state="MYSTERY",
        requested_sequence="sales_nurture",
        marketing_consent=True,
    ).reason == "UNKNOWN_STATE_FAIL_CLOSED"

    unknown = decide_messaging(
        state="LEAD",
        requested_sequence="mystery-sequence",
        marketing_consent=True,
    )
    assert unknown.allowed is False
    assert unknown.sequence is None
    assert unknown.reason == "UNKNOWN_SEQUENCE_FAIL_CLOSED"


def test_public_view_is_stable():
    decision = decide_messaging(
        state="CUSTOMER",
        requested_sequence="onboarding",
        marketing_consent=True,
    )
    assert decision.public_view() == {
        "allowed": True,
        "sequence": "ONBOARDING",
        "reason": "CUSTOMER_ONBOARDING_ELIGIBLE",
    }
