from __future__ import annotations

import pytest

from revenue.lifecycle import (
    IllegalTransitionError,
    PaymentProof,
    PaymentProofError,
    RevenueState,
    allowed_next_states,
    transition,
)


def proof(**overrides):
    values = {
        "account_id": "acct_dsg_lifecycle",
        "source": "stripe_payment_intent",
        "source_id": "pi_live_001",
        "livemode": True,
        "status": "succeeded",
        "verified": True,
        "evidence_ref": "stripe:pi_live_001",
    }
    values.update(overrides)
    return PaymentProof(**values)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RevenueState.LEAD, RevenueState.ENGAGED),
        (RevenueState.ENGAGED, RevenueState.QUALIFIED),
        (RevenueState.QUALIFIED, RevenueState.TRIAL_OR_DEMO),
        (RevenueState.QUALIFIED, RevenueState.CHECKOUT_STARTED),
        (RevenueState.TRIAL_OR_DEMO, RevenueState.CHECKOUT_STARTED),
        (RevenueState.CHECKOUT_STARTED, RevenueState.ABANDONED),
        (RevenueState.ABANDONED, RevenueState.CHECKOUT_STARTED),
        (RevenueState.CUSTOMER, RevenueState.ONBOARDING),
        (RevenueState.ONBOARDING, RevenueState.ACTIVE_CUSTOMER),
        (RevenueState.ACTIVE_CUSTOMER, RevenueState.EXPANSION),
    ],
)
def test_structural_transitions_are_explicit(current, target):
    result = transition(
        account_id="acct_dsg_lifecycle",
        current=current,
        target=target,
        reason="verified event",
        evidence_ref="event:001",
    )
    assert result.from_state == current
    assert result.to_state == target


def test_customer_requires_authoritative_payment_proof():
    with pytest.raises(PaymentProofError):
        transition(
            account_id="acct_dsg_lifecycle",
            current=RevenueState.CHECKOUT_STARTED,
            target=RevenueState.CUSTOMER,
            reason="client says paid",
            evidence_ref="client:assertion",
        )

    with pytest.raises(PaymentProofError):
        transition(
            account_id="acct_dsg_lifecycle",
            current=RevenueState.CHECKOUT_STARTED,
            target=RevenueState.CUSTOMER,
            reason="test-mode payment",
            evidence_ref="stripe:test",
            payment_proof=proof(livemode=False),
        )

    with pytest.raises(PaymentProofError):
        transition(
            account_id="acct_dsg_lifecycle",
            current=RevenueState.CHECKOUT_STARTED,
            target=RevenueState.CUSTOMER,
            reason="wrong account",
            evidence_ref="stripe:wrong-account",
            payment_proof=proof(account_id="acct_other"),
        )


@pytest.mark.parametrize(
    "bad_proof",
    [
        proof(source="stripe_payment_intent", status="paid"),
        proof(source="stripe_checkout_session", source_id="cs_live_001", status="succeeded"),
        proof(source="stripe_paid_invoice", source_id="in_live_001", status="succeeded"),
        proof(source="client_assertion", source_id="browser", status="paid"),
    ],
)
def test_customer_rejects_noncanonical_source_status_pairs(bad_proof):
    with pytest.raises(PaymentProofError):
        transition(
            account_id="acct_dsg_lifecycle",
            current=RevenueState.CHECKOUT_STARTED,
            target=RevenueState.CUSTOMER,
            reason="invalid Stripe proof shape",
            evidence_ref="event:invalid-payment",
            payment_proof=bad_proof,
        )


@pytest.mark.parametrize(
    "valid_proof",
    [
        proof(),
        proof(
            source="stripe_checkout_session",
            source_id="cs_live_001",
            status="paid",
            evidence_ref="stripe:cs_live_001",
        ),
        proof(
            source="stripe_paid_invoice",
            source_id="in_live_001",
            status="paid",
            evidence_ref="stripe:in_live_001",
        ),
    ],
)
def test_canonical_verified_live_payment_allows_customer_transition(valid_proof):
    result = transition(
        account_id="acct_dsg_lifecycle",
        current=RevenueState.CHECKOUT_STARTED,
        target=RevenueState.CUSTOMER,
        reason="verified Stripe payment",
        evidence_ref="event:payment-confirmed",
        payment_proof=valid_proof,
    )
    assert result.to_state == RevenueState.CUSTOMER
    assert result.payment_source == valid_proof.source
    assert result.payment_source_id == valid_proof.source_id


def test_illegal_skip_and_backwards_transitions_fail_closed():
    for current, target in [
        (RevenueState.LEAD, RevenueState.CUSTOMER),
        (RevenueState.CHECKOUT_STARTED, RevenueState.QUALIFIED),
        (RevenueState.CUSTOMER, RevenueState.CHECKOUT_STARTED),
        (RevenueState.EXPANSION, RevenueState.LEAD),
    ]:
        with pytest.raises(IllegalTransitionError):
            transition(
                account_id="acct_dsg_lifecycle",
                current=current,
                target=target,
                reason="invalid request",
                evidence_ref="event:invalid",
            )


def test_allowed_next_states_are_deterministic():
    assert allowed_next_states(RevenueState.QUALIFIED) == (
        RevenueState.CHECKOUT_STARTED,
        RevenueState.TRIAL_OR_DEMO,
    )


def test_transition_public_view_is_stable_and_structural():
    result = transition(
        account_id="acct_dsg_lifecycle",
        current=RevenueState.LEAD,
        target=RevenueState.ENGAGED,
        reason="email click",
        evidence_ref="event:email-click-1",
    )
    assert result.public_view() == {
        "account_id": "acct_dsg_lifecycle",
        "from_state": "LEAD",
        "to_state": "ENGAGED",
        "reason": "email click",
        "evidence_ref": "event:email-click-1",
        "payment_source": None,
        "payment_source_id": None,
    }
