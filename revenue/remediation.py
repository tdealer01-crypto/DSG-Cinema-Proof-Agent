"""Actionable remediation for every way a request can be refused.

A refusal that only says "HTTP 402" costs the user a support round trip. Every
denial in this system carries the same four things instead: what happened, why,
the one next action that fixes it, and whether the user can do it alone.

This module is the single source of that vocabulary, so the API, the GitHub
Action, the Stripe app, and the OpenAI skill all explain a problem the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DOCS_BASE = "https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/blob/main"
REVENUE_DOCS = f"{DOCS_BASE}/REVENUE_AUTOMATION.md"
CHANNEL_DOCS = f"{DOCS_BASE}/CHANNEL_DELIVERY.md"

# Denial codes. These match revenue.engine decisions plus the codes raised by
# activation and by delivery-side failures.
UNKNOWN_KEY = "UNKNOWN_KEY"
ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
PAYMENT_NOT_LINKED = "PAYMENT_NOT_LINKED"
ACTIVATION_EXISTS = "ACTIVATION_EXISTS"
ACTIVATION_RATE_LIMITED = "ACTIVATION_RATE_LIMITED"
ACTIVATION_DISABLED = "ACTIVATION_DISABLED"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
VERIFICATION_NOT_PROVED = "VERIFICATION_NOT_PROVED"
CONFIGURATION_INCOMPLETE = "CONFIGURATION_INCOMPLETE"

OK = "OK"


@dataclass(frozen=True)
class Remediation:
    code: str
    problem: str
    cause: str
    next_step: str
    self_service: bool
    endpoint: Optional[str] = None
    docs: str = REVENUE_DOCS

    def to_dict(self) -> dict:
        body = {
            "code": self.code,
            "problem": self.problem,
            "cause": self.cause,
            "next_step": self.next_step,
            "self_service": self.self_service,
            "docs": self.docs,
        }
        if self.endpoint:
            body["endpoint"] = self.endpoint
        return body


_CATALOG: dict[str, Remediation] = {
    UNKNOWN_KEY: Remediation(
        code=UNKNOWN_KEY,
        problem="No usable API key was presented.",
        cause="The X-DSG-API-Key header was missing, malformed, or does not match an account.",
        next_step=(
            "Activate a free key in one call: POST /billing/activate with your "
            "channel and a stable activation_id. The key is returned once."
        ),
        self_service=True,
        endpoint="POST /billing/activate",
        docs=CHANNEL_DOCS,
    ),
    ACCOUNT_SUSPENDED: Remediation(
        code=ACCOUNT_SUSPENDED,
        problem="The account is not active.",
        cause="The account was suspended, usually after a failed or cancelled payment.",
        next_step=(
            "Settle the outstanding Stripe invoice. The account reactivates "
            "automatically when the invoice.paid webhook arrives."
        ),
        self_service=True,
        endpoint="GET /support/diagnose",
    ),
    QUOTA_EXCEEDED: Remediation(
        code=QUOTA_EXCEEDED,
        problem="This billing period's proof quota is used up.",
        cause="The plan's hard cap was reached, so further proofs are refused rather than served free.",
        next_step=(
            "Move to the metered plan and link a payment method, or wait for the "
            "next UTC month when the free quota resets."
        ),
        self_service=True,
        endpoint="GET /billing/usage",
    ),
    PAYMENT_NOT_LINKED: Remediation(
        code=PAYMENT_NOT_LINKED,
        problem="The plan bills per proof but no payment method is linked.",
        cause="A metered plan cannot record billable usage until Stripe confirms a payment method.",
        next_step=(
            "Complete Stripe checkout for this account. The entitlement opens "
            "automatically when the checkout.session.completed webhook arrives."
        ),
        self_service=True,
        endpoint="GET /billing/status",
    ),
    ACTIVATION_EXISTS: Remediation(
        code=ACTIVATION_EXISTS,
        problem="This activation_id already has an account.",
        cause=(
            "Activation is idempotent so a retry cannot silently create a second "
            "account. An API key is shown only at first activation."
        ),
        next_step=(
            "Use the key issued the first time. If it was lost, ask an operator "
            "to issue a replacement with POST /billing/accounts."
        ),
        self_service=False,
        endpoint="GET /support/diagnose",
        docs=CHANNEL_DOCS,
    ),
    ACTIVATION_RATE_LIMITED: Remediation(
        code=ACTIVATION_RATE_LIMITED,
        problem="Too many activations were requested in a short window.",
        cause="Self-serve activation is rate limited so a single source cannot exhaust free capacity.",
        next_step="Wait for the window shown in retry_after_seconds and call activation again.",
        self_service=True,
        endpoint="POST /billing/activate",
        docs=CHANNEL_DOCS,
    ),
    ACTIVATION_DISABLED: Remediation(
        code=ACTIVATION_DISABLED,
        problem="Self-serve activation is turned off on this deployment.",
        cause="DSG_ACTIVATION_ENABLED is set to a false value.",
        next_step="Ask an operator to issue a key with POST /billing/accounts, or re-enable activation.",
        self_service=False,
        endpoint="POST /billing/accounts",
        docs=CHANNEL_DOCS,
    ),
    BACKEND_UNAVAILABLE: Remediation(
        code=BACKEND_UNAVAILABLE,
        problem="The verification backend could not be reached.",
        cause="Cinema could not complete a healthy round trip to the Z3 verifier.",
        next_step=(
            "Retry shortly. No decision is issued while the backend is "
            "unavailable, so nothing was approved and nothing was billed."
        ),
        self_service=True,
        endpoint="GET /health",
    ),
    VERIFICATION_NOT_PROVED: Remediation(
        code=VERIFICATION_NOT_PROVED,
        problem="Z3 did not return a proved global optimum.",
        cause="The solver timed out or produced a counterexample, so no receipt can be issued.",
        next_step=(
            "Retry the request. A proof that is not VERIFIED_GLOBAL_OPTIMUM is "
            "never billed, so a failed attempt costs nothing."
        ),
        self_service=True,
        endpoint="GET /support/diagnose",
    ),
    CONFIGURATION_INCOMPLETE: Remediation(
        code=CONFIGURATION_INCOMPLETE,
        problem="The deployment is missing required configuration.",
        cause="A required secret or backend URL is unset, so the service fails closed.",
        next_step="An operator must complete the deployment configuration; see the activation sequence.",
        self_service=False,
        endpoint="GET /health",
    ),
    OK: Remediation(
        code=OK,
        problem="No problem detected.",
        cause="The account is active and entitled for this billing period.",
        next_step="Send a verification request to /verify/evaluate with your API key.",
        self_service=True,
        endpoint="POST /verify/evaluate",
        docs=CHANNEL_DOCS,
    ),
}


def remediation_for(code: str) -> Remediation:
    """Return the remediation for a denial code, never raising on an unknown one."""
    known = _CATALOG.get(code)
    if known is not None:
        return known
    return Remediation(
        code=code,
        problem="The request was refused.",
        cause=f"The service reported {code}.",
        next_step="Call GET /support/diagnose with your API key for a specific next action.",
        self_service=True,
        endpoint="GET /support/diagnose",
    )


def all_codes() -> list[str]:
    return sorted(_CATALOG)
