import pytest

from revenue.lifecycle import RevenueState
from revenue.messaging_policy import MessageSequence
from revenue.signals import (
    RevenueSignal,
    SignalContractError,
    authorize_signal_source,
    route_signal,
)


def test_lead_initializes_only_lead_and_scores_as_lead():
    route = route_signal("lead_created")
    assert route.initialize_state == RevenueState.LEAD
    assert route.lifecycle_target is None
    assert route.intent_event == "lead_created"
    assert route.activecampaign_event == "lead"
    assert route.candidate_sequence == MessageSequence.SALES_NURTURE


@pytest.mark.parametrize(
    ("signal", "target", "intent_event"),
    [
        ("email_click", RevenueState.ENGAGED, "email_click"),
        ("pricing_visit", RevenueState.QUALIFIED, "pricing_visit"),
        ("demo_requested", RevenueState.TRIAL_OR_DEMO, "demo_requested"),
        ("trial_started", RevenueState.TRIAL_OR_DEMO, "trial_started"),
        ("checkout_started", RevenueState.CHECKOUT_STARTED, "checkout_started"),
    ],
)
def test_pre_customer_signal_path_is_explicit(signal, target, intent_event):
    route = route_signal(signal)
    assert route.lifecycle_target == target
    assert route.intent_event == intent_event
    assert route.requires_payment_proof is False
    assert route.trusted_source_only is False


def test_abandonment_routes_to_recovery_without_adding_intent_points():
    route = route_signal(RevenueSignal.CHECKOUT_ABANDONED)
    assert route.lifecycle_target == RevenueState.ABANDONED
    assert route.intent_event is None
    assert route.activecampaign_event == "checkout_abandoned"
    assert route.candidate_sequence == MessageSequence.CHECKOUT_RECOVERY


def test_payment_is_trusted_only_requires_proof_and_never_scores_intent():
    route = route_signal("payment_confirmed")
    assert route.lifecycle_target == RevenueState.CUSTOMER
    assert route.intent_event is None
    assert route.activecampaign_event == "payment_confirmed"
    assert route.requires_payment_proof is True
    assert route.trusted_source_only is True
    with pytest.raises(SignalContractError, match="trusted backend"):
        authorize_signal_source("payment_confirmed", trusted_source=False)
    assert authorize_signal_source("payment_confirmed", trusted_source=True) == route


def test_post_purchase_path_is_explicit():
    assert route_signal("onboarding_started").lifecycle_target == RevenueState.ONBOARDING
    assert route_signal("onboarding_completed").lifecycle_target == RevenueState.ACTIVE_CUSTOMER
    expansion = route_signal("expansion_signal")
    assert expansion.lifecycle_target == RevenueState.EXPANSION
    assert expansion.candidate_sequence == MessageSequence.EXPANSION


def test_unknown_signal_fails_closed():
    with pytest.raises(SignalContractError, match="unsupported revenue signal"):
        route_signal("make_me_customer")


def test_public_view_is_deterministic_and_structural():
    first = route_signal("checkout_started").public_view()
    second = route_signal("checkout_started").public_view()
    assert first == second
    assert first == {
        "signal": "checkout_started",
        "initialize_state": None,
        "lifecycle_target": "CHECKOUT_STARTED",
        "intent_event": "checkout_started",
        "activecampaign_event": "checkout_started",
        "candidate_sequence": None,
        "requires_payment_proof": False,
        "trusted_source_only": False,
    }
