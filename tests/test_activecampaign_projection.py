from dataclasses import replace

import pytest

from revenue.activecampaign_projection import (
    ActiveCampaignProjectionError,
    project_activecampaign,
)
from revenue.intent import INTENT_TAGS, evaluate_intent
from revenue.lifecycle import RevenueState


def test_pre_customer_projection_has_exactly_one_deterministic_intent_tag():
    intent = evaluate_intent(["lead_created", "demo_requested"])
    projection = project_activecampaign(
        state=RevenueState.TRIAL_OR_DEMO,
        intent=intent,
        marketing_consent=True,
        lifecycle_facts=["demo_requested"],
    )
    intent_tags = {
        tag for tag in projection.desired_tags if tag.startswith("dsg-intent-")
    }
    assert intent_tags == {intent.selected_tag}
    assert "dsg-demo-requested" in projection.desired_tags
    assert set(INTENT_TAGS.values()) - {intent.selected_tag} <= set(projection.remove_tags)
    assert intent.selected_tag not in projection.remove_tags
    assert projection.messaging.allowed is True


def test_abandoned_checkout_projects_recovery_and_removes_started_tag():
    intent = evaluate_intent(["checkout_started"])
    projection = project_activecampaign(
        state="ABANDONED",
        intent=intent,
        marketing_consent=True,
        lifecycle_facts=["checkout_abandoned"],
    )
    assert "dsg-checkout-abandoned" in projection.desired_tags
    assert "dsg-checkout-started" in projection.remove_tags
    assert projection.messaging.allowed is True
    assert projection.messaging.sequence.value == "CHECKOUT_RECOVERY"


def test_checkout_started_is_not_misclassified_as_abandoned():
    intent = evaluate_intent(["checkout_started"])
    projection = project_activecampaign(
        state="CHECKOUT_STARTED",
        intent=intent,
        marketing_consent=True,
    )
    assert "dsg-checkout-started" in projection.desired_tags
    assert projection.messaging.allowed is False
    assert projection.messaging.reason == "CHECKOUT_RECOVERY_REQUIRES_ABANDONMENT"


def test_customer_state_removes_sales_tags_and_projects_customer_onboarding():
    intent = evaluate_intent(["checkout_started"])
    projection = project_activecampaign(
        state="CUSTOMER",
        intent=intent,
        marketing_consent=True,
        lifecycle_facts=["payment_confirmed"],
    )
    assert {
        "dsg-customer",
        "dsg-onboarding",
        "dsg-payment-confirmed",
    }.issubset(projection.desired_tags)
    assert {
        "dsg-intent-low",
        "dsg-intent-medium",
        "dsg-intent-high",
        "dsg-checkout-started",
        "dsg-checkout-abandoned",
    }.issubset(projection.remove_tags)
    assert projection.messaging.allowed is True
    assert projection.messaging.sequence.value == "ONBOARDING"


def test_no_consent_suppresses_messaging_without_rewriting_customer_truth():
    intent = evaluate_intent(["checkout_started"])
    projection = project_activecampaign(
        state="CUSTOMER",
        intent=intent,
        marketing_consent=False,
        lifecycle_facts=["payment_confirmed"],
    )
    assert "dsg-customer" in projection.desired_tags
    assert "dsg-payment-confirmed" in projection.desired_tags
    assert projection.messaging.allowed is False
    assert projection.messaging.reason == "NO_MARKETING_CONSENT"


def test_active_customer_expansion_requires_verified_signal():
    intent = evaluate_intent(["checkout_started"])
    without_signal = project_activecampaign(
        state="ACTIVE_CUSTOMER",
        intent=intent,
        marketing_consent=True,
    )
    assert without_signal.messaging.allowed is False
    assert "dsg-onboarding" in without_signal.remove_tags

    with_signal = project_activecampaign(
        state="ACTIVE_CUSTOMER",
        intent=intent,
        marketing_consent=True,
        lifecycle_facts=["expansion_signal"],
    )
    assert with_signal.messaging.allowed is True
    assert with_signal.messaging.sequence.value == "EXPANSION"


def test_inconsistent_intent_and_unknown_inputs_fail_closed():
    intent = evaluate_intent(["lead_created"])
    forged = replace(intent, selected_tag="dsg-intent-high")
    with pytest.raises(ActiveCampaignProjectionError, match="selected_tag"):
        project_activecampaign(
            state="LEAD",
            intent=forged,
            marketing_consent=True,
        )
    with pytest.raises(ActiveCampaignProjectionError, match="unknown revenue lifecycle"):
        project_activecampaign(
            state="WON_BECAUSE_CRM_SAID_SO",
            intent=intent,
            marketing_consent=True,
        )
    with pytest.raises(ActiveCampaignProjectionError, match="unknown lifecycle facts"):
        project_activecampaign(
            state="LEAD",
            intent=intent,
            marketing_consent=True,
            lifecycle_facts=["crm_marked_paid"],
        )


def test_public_output_is_sorted_and_deterministic():
    intent = evaluate_intent(["lead_created", "pricing_visit"])
    first = project_activecampaign(
        state="QUALIFIED",
        intent=intent,
        marketing_consent=True,
    ).public_view()
    second = project_activecampaign(
        state="QUALIFIED",
        intent=intent,
        marketing_consent=True,
    ).public_view()
    assert first == second
    assert first["desired_tags"] == sorted(first["desired_tags"])
    assert first["remove_tags"] == sorted(first["remove_tags"])
