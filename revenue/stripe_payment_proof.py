"""Fail-closed adapter from verified Stripe webhook evidence to PaymentProof.

The adapter intentionally sits *after* Stripe signature verification and
``apply_webhook_event``. It cannot make ``payment_linked`` authoritative by
itself: the exact live ``invoice.paid`` event and invoice id must already be
recorded on the DSG account before a lifecycle PaymentProof can be emitted.
"""

from __future__ import annotations

from typing import Any, Mapping

from .accounts import Account
from .lifecycle import PaymentProof
from .stripe_sync import StripeConfig


class StripePaymentProofError(RuntimeError):
    """Raised when payment evidence is incomplete or crosses a trust boundary."""


def payment_proof_from_verified_invoice(
    *,
    event: Mapping[str, Any],
    application: Mapping[str, Any],
    config: StripeConfig,
    account: Account,
    signature_verified: bool,
    evidence_ref: str,
) -> PaymentProof:
    """Build lifecycle proof from verified live paid-invoice evidence.

    ``signature_verified`` is explicit because this module does not re-implement
    Stripe signature verification. The first delivery must have been applied by
    ``apply_webhook_event``. A later idempotent Stripe retry may report
    ``reason=duplicate``; that replay is accepted only when the exact event and
    invoice are already present in the supplied account's authoritative Stripe
    evidence lists. Other ignored/stale outcomes never create proof.
    """

    evidence_ref = str(evidence_ref).strip()
    if not signature_verified:
        raise StripePaymentProofError("Stripe webhook signature is not verified")
    if not evidence_ref:
        raise StripePaymentProofError("evidence_ref is required")
    if config.livemode is not True:
        raise StripePaymentProofError("production payment proof requires a live Stripe key")
    if not config.webhook_scope_configured:
        raise StripePaymentProofError("DSG Stripe catalog scope is not configured")

    event_type = event.get("type")
    if event_type != "invoice.paid":
        raise StripePaymentProofError("only invoice.paid can create paid lifecycle proof")
    if event.get("livemode") is not True:
        raise StripePaymentProofError("payment proof requires a live Stripe event")

    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise StripePaymentProofError("Stripe event has no stable id")

    obj = ((event.get("data") or {}).get("object") or {})
    if not isinstance(obj, Mapping):
        raise StripePaymentProofError("Stripe invoice object is invalid")
    invoice_id = obj.get("id")
    if not isinstance(invoice_id, str) or not invoice_id.strip():
        raise StripePaymentProofError("Stripe invoice has no stable id")
    customer_id = obj.get("customer")
    if (
        not isinstance(customer_id, str)
        or not customer_id.strip()
        or customer_id != account.stripe_customer_id
    ):
        raise StripePaymentProofError("Stripe invoice customer is not bound to the DSG account")

    if application.get("type") != "invoice.paid":
        raise StripePaymentProofError("Stripe application type is not invoice.paid")
    if application.get("event_id") != event_id:
        raise StripePaymentProofError("Stripe application is for a different event")

    applied_now = application.get("applied") is True
    duplicate_replay = (
        application.get("applied") is False
        and application.get("reason") == "duplicate"
    )
    if not applied_now and not duplicate_replay:
        raise StripePaymentProofError(
            "Stripe webhook was neither applied nor an authoritative duplicate replay"
        )
    if applied_now and application.get("account_id") != account.account_id:
        raise StripePaymentProofError("Stripe application is bound to a different account")

    # These checks are the durable authority for both first delivery and retry.
    # In particular, a duplicate replay cannot pass merely because it names an
    # invoice: the original event id and invoice id must both already be stored.
    if event_id not in account.stripe_processed_event_ids:
        raise StripePaymentProofError("Stripe event is not recorded on the DSG account")
    if invoice_id not in account.stripe_paid_invoice_ids:
        raise StripePaymentProofError("paid invoice is not recorded on the DSG account")
    if account.payment_linked is not True:
        raise StripePaymentProofError("paid invoice account is no longer payment-linked")

    return PaymentProof(
        account_id=account.account_id,
        source="stripe_paid_invoice",
        source_id=invoice_id,
        livemode=True,
        status="paid",
        verified=True,
        evidence_ref=evidence_ref,
    )


__all__ = ["StripePaymentProofError", "payment_proof_from_verified_invoice"]
