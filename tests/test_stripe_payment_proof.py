import copy

import pytest

from revenue.accounts import Account
from revenue.stripe_payment_proof import (
    StripePaymentProofError,
    payment_proof_from_verified_invoice,
)
from revenue.stripe_sync import StripeConfig


def _config(secret_key="sk_live_example"):
    return StripeConfig(
        secret_key=secret_key,
        webhook_secret="whsec_example",
        meter_event_name="dsg_verified_execution",
        product_id="prod_dsg",
        price_id="price_dsg",
    )


def _event():
    return {
        "id": "evt_paid_1",
        "type": "invoice.paid",
        "livemode": True,
        "data": {
            "object": {
                "id": "in_paid_1",
                "customer": "cus_dsg_1",
            }
        },
    }


def _account():
    return Account(
        account_id="acct_dsg_1",
        display_name="DSG Account",
        payment_linked=True,
        stripe_customer_id="cus_dsg_1",
        stripe_paid_invoice_ids=["in_paid_1"],
        stripe_processed_event_ids=["evt_paid_1"],
    )


def _application():
    return {
        "applied": True,
        "type": "invoice.paid",
        "event_id": "evt_paid_1",
        "account_id": "acct_dsg_1",
    }


def _proof(**overrides):
    kwargs = {
        "event": _event(),
        "application": _application(),
        "config": _config(),
        "account": _account(),
        "signature_verified": True,
        "evidence_ref": "evidence/stripe/evt_paid_1.json",
    }
    kwargs.update(overrides)
    return payment_proof_from_verified_invoice(**kwargs)


def test_verified_live_applied_invoice_becomes_authoritative_payment_proof():
    proof = _proof()
    assert proof.account_id == "acct_dsg_1"
    assert proof.source == "stripe_paid_invoice"
    assert proof.source_id == "in_paid_1"
    assert proof.livemode is True
    assert proof.status == "paid"
    assert proof.verified is True
    assert proof.is_authoritative_for("acct_dsg_1") is True


def test_signature_is_required():
    with pytest.raises(StripePaymentProofError, match="signature"):
        _proof(signature_verified=False)


def test_test_mode_key_and_event_fail_closed():
    with pytest.raises(StripePaymentProofError, match="live Stripe key"):
        _proof(config=_config("sk_test_example"))
    event = _event()
    event["livemode"] = False
    with pytest.raises(StripePaymentProofError, match="live Stripe event"):
        _proof(event=event)


def test_only_invoice_paid_can_create_payment_proof():
    event = _event()
    event["type"] = "checkout.session.completed"
    with pytest.raises(StripePaymentProofError, match="only invoice.paid"):
        _proof(event=event)


def test_application_must_be_applied_or_exact_authoritative_duplicate():
    app = _application()
    app["applied"] = False
    with pytest.raises(StripePaymentProofError, match="neither applied nor"):
        _proof(application=app)

    duplicate = {
        "applied": False,
        "reason": "duplicate",
        "type": "invoice.paid",
        "event_id": "evt_paid_1",
    }
    proof = _proof(application=duplicate)
    assert proof.source_id == "in_paid_1"

    duplicate_invoice = dict(duplicate, reason="duplicate_invoice")
    with pytest.raises(StripePaymentProofError, match="neither applied nor"):
        _proof(application=duplicate_invoice)


def test_application_must_be_bound_to_same_event_and_account():
    app = _application()
    app["event_id"] = "evt_other"
    with pytest.raises(StripePaymentProofError, match="different event"):
        _proof(application=app)

    app = _application()
    app["account_id"] = "acct_other"
    with pytest.raises(StripePaymentProofError, match="different account"):
        _proof(application=app)


def test_invoice_customer_must_match_account_binding():
    event = copy.deepcopy(_event())
    event["data"]["object"]["customer"] = "cus_other"
    with pytest.raises(StripePaymentProofError, match="customer"):
        _proof(event=event)


def test_payment_linked_alone_is_never_sufficient():
    account = _account()
    account.stripe_paid_invoice_ids = []
    with pytest.raises(StripePaymentProofError, match="paid invoice is not recorded"):
        _proof(account=account)


def test_event_must_already_be_recorded_by_stripe_application():
    account = _account()
    account.stripe_processed_event_ids = []
    with pytest.raises(StripePaymentProofError, match="event is not recorded"):
        _proof(account=account)

    duplicate = {
        "applied": False,
        "reason": "duplicate",
        "type": "invoice.paid",
        "event_id": "evt_paid_1",
    }
    with pytest.raises(StripePaymentProofError, match="event is not recorded"):
        _proof(account=account, application=duplicate)


def test_invoice_id_and_evidence_ref_are_required():
    event = copy.deepcopy(_event())
    event["data"]["object"]["id"] = ""
    with pytest.raises(StripePaymentProofError, match="invoice has no stable id"):
        _proof(event=event)
    with pytest.raises(StripePaymentProofError, match="evidence_ref"):
        _proof(evidence_ref="")
