"""Deterministic revenue-intent scoring policy.

Intent scoring is advisory for sales/nurture routing only. Payment events are
explicitly excluded so score can never become a substitute for Stripe truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


EVENT_WEIGHTS: dict[str, int] = {
    "lead_created": 5,
    "email_click": 10,
    "pricing_visit": 15,
    "demo_requested": 30,
    "trial_started": 35,
    "checkout_started": 50,
}

PAYMENT_EVENTS = frozenset(
    {
        "payment_confirmed",
        "checkout_paid",
        "payment_intent_succeeded",
        "invoice_paid",
    }
)


class IntentBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


INTENT_TAGS: dict[IntentBand, str] = {
    IntentBand.LOW: "dsg-intent-low",
    IntentBand.MEDIUM: "dsg-intent-medium",
    IntentBand.HIGH: "dsg-intent-high",
}


@dataclass(frozen=True)
class IntentEvaluation:
    score: int
    band: IntentBand
    selected_tag: str
    scored_events: tuple[str, ...]
    ignored_events: tuple[str, ...]
    payment_events_excluded: tuple[str, ...]

    def public_view(self) -> dict[str, object]:
        return {
            "score": self.score,
            "band": self.band.value,
            "selected_tag": self.selected_tag,
            "scored_events": list(self.scored_events),
            "ignored_events": list(self.ignored_events),
            "payment_events_excluded": list(self.payment_events_excluded),
        }


def band_for_score(score: int) -> IntentBand:
    if score < 0:
        raise ValueError("intent score cannot be negative")
    if score <= 19:
        return IntentBand.LOW
    if score <= 49:
        return IntentBand.MEDIUM
    return IntentBand.HIGH


def evaluate_intent(events: Iterable[str]) -> IntentEvaluation:
    """Evaluate an ordered event stream using the fixed scoring contract.

    Unknown events contribute zero and are reported. Payment events also
    contribute zero, but are reported separately because they belong to the
    authoritative payment/lifecycle gate rather than intent scoring.
    """

    score = 0
    scored: list[str] = []
    ignored: list[str] = []
    payment_excluded: list[str] = []

    for raw_event in events:
        event = str(raw_event).strip()
        if event in PAYMENT_EVENTS:
            payment_excluded.append(event)
            continue
        weight = EVENT_WEIGHTS.get(event)
        if weight is None:
            ignored.append(event)
            continue
        score += weight
        scored.append(event)

    band = band_for_score(score)
    return IntentEvaluation(
        score=score,
        band=band,
        selected_tag=INTENT_TAGS[band],
        scored_events=tuple(scored),
        ignored_events=tuple(ignored),
        payment_events_excluded=tuple(payment_excluded),
    )


def exclusive_intent_tag(score: int) -> str:
    """Return exactly one canonical ActiveCampaign intent tag for ``score``."""

    return INTENT_TAGS[band_for_score(score)]
