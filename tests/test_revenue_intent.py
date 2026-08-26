from __future__ import annotations

import pytest

from revenue.intent import (
    IntentBand,
    band_for_score,
    evaluate_intent,
    exclusive_intent_tag,
)


@pytest.mark.parametrize(
    ("score", "band", "tag"),
    [
        (0, IntentBand.LOW, "dsg-intent-low"),
        (19, IntentBand.LOW, "dsg-intent-low"),
        (20, IntentBand.MEDIUM, "dsg-intent-medium"),
        (49, IntentBand.MEDIUM, "dsg-intent-medium"),
        (50, IntentBand.HIGH, "dsg-intent-high"),
        (500, IntentBand.HIGH, "dsg-intent-high"),
    ],
)
def test_thresholds_are_fixed(score, band, tag):
    assert band_for_score(score) == band
    assert exclusive_intent_tag(score) == tag


def test_accumulation_is_deterministic_and_order_preserving():
    result = evaluate_intent(
        ["lead_created", "email_click", "pricing_visit", "demo_requested"]
    )
    assert result.score == 60
    assert result.band == IntentBand.HIGH
    assert result.selected_tag == "dsg-intent-high"
    assert result.scored_events == (
        "lead_created",
        "email_click",
        "pricing_visit",
        "demo_requested",
    )


def test_unknown_events_are_zero_score_and_reported():
    result = evaluate_intent(["lead_created", "mystery_signal", "unknown"])
    assert result.score == 5
    assert result.ignored_events == ("mystery_signal", "unknown")


def test_payment_events_never_change_intent_score():
    baseline = evaluate_intent(["lead_created"])
    with_payment = evaluate_intent(
        [
            "lead_created",
            "payment_confirmed",
            "payment_intent_succeeded",
            "invoice_paid",
        ]
    )
    assert with_payment.score == baseline.score == 5
    assert with_payment.payment_events_excluded == (
        "payment_confirmed",
        "payment_intent_succeeded",
        "invoice_paid",
    )


def test_evaluation_selects_exactly_one_intent_tag():
    for events in [[], ["email_click"], ["checkout_started"]]:
        result = evaluate_intent(events)
        assert result.selected_tag in {
            "dsg-intent-low",
            "dsg-intent-medium",
            "dsg-intent-high",
        }
        assert isinstance(result.selected_tag, str)


def test_public_view_is_stable():
    assert evaluate_intent(["pricing_visit", "unknown"]).public_view() == {
        "score": 15,
        "band": "LOW",
        "selected_tag": "dsg-intent-low",
        "scored_events": ["pricing_visit"],
        "ignored_events": ["unknown"],
        "payment_events_excluded": [],
    }


def test_negative_score_is_rejected():
    with pytest.raises(ValueError):
        band_for_score(-1)
