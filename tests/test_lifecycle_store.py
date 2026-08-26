import json

import pytest

from revenue.lifecycle import LifecycleTransition, PaymentProof, RevenueState, transition
from revenue.lifecycle_store import (
    LifecycleConflictError,
    LifecycleNotFoundError,
    LifecycleStateStore,
    StaleLifecycleTransitionError,
)


def _transition(account_id, current, target, *, reason=None, evidence=None, payment_proof=None):
    return transition(
        account_id=account_id,
        current=current,
        target=target,
        reason=reason or f"{current.value}->{target.value}",
        evidence_ref=evidence or f"evidence/{current.value.lower()}-{target.value.lower()}.json",
        payment_proof=payment_proof,
    )


def _paid_proof(account_id="acct_1", source_id="in_123"):
    return PaymentProof(
        account_id=account_id,
        source="stripe_paid_invoice",
        source_id=source_id,
        livemode=True,
        status="paid",
        verified=True,
        evidence_ref=f"evidence/stripe/{source_id}.json",
    )


def test_initialize_only_at_lead_and_exact_replay_is_idempotent():
    store = LifecycleStateStore()
    record, created = store.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")
    assert created is True
    assert record.state == RevenueState.LEAD
    assert record.version == 0

    replay, created = store.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")
    assert created is False
    assert replay == record

    with pytest.raises(LifecycleConflictError, match="only at LEAD"):
        LifecycleStateStore().initialize(
            account_id="acct_2",
            evidence_ref="evidence/not-lead.json",
            state=RevenueState.ENGAGED,
        )


def test_apply_requires_initialized_account_and_exact_current_state():
    store = LifecycleStateStore()
    engaged = _transition("acct_1", RevenueState.LEAD, RevenueState.ENGAGED)
    with pytest.raises(LifecycleNotFoundError, match="not initialized"):
        store.apply(engaged)

    store.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")
    record, created = store.apply(engaged)
    assert created is True
    assert record.state == RevenueState.ENGAGED
    assert record.version == 1

    replay, created = store.apply(engaged)
    assert created is False
    assert replay == record

    stale = _transition(
        "acct_1",
        RevenueState.LEAD,
        RevenueState.ENGAGED,
        reason="different stale event",
        evidence="evidence/stale.json",
    )
    with pytest.raises(StaleLifecycleTransitionError, match="current=ENGAGED"):
        store.apply(stale)


def test_forged_illegal_edge_and_customer_without_authoritative_proof_fail_closed():
    store = LifecycleStateStore()
    store.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")

    forged = LifecycleTransition(
        account_id="acct_1",
        from_state=RevenueState.LEAD,
        to_state=RevenueState.CHECKOUT_STARTED,
        reason="skip qualification",
        evidence_ref="evidence/forged.json",
    )
    with pytest.raises(LifecycleConflictError, match="illegal persisted lifecycle edge"):
        store.apply(forged)

    for current, target in [
        (RevenueState.LEAD, RevenueState.ENGAGED),
        (RevenueState.ENGAGED, RevenueState.QUALIFIED),
        (RevenueState.QUALIFIED, RevenueState.CHECKOUT_STARTED),
    ]:
        store.apply(_transition("acct_1", current, target))

    # A caller can manually construct the dataclass and copy plausible payment
    # source fields. The persistence boundary must still demand the PaymentProof.
    forged_customer = LifecycleTransition(
        account_id="acct_1",
        from_state=RevenueState.CHECKOUT_STARTED,
        to_state=RevenueState.CUSTOMER,
        reason="client claimed paid",
        evidence_ref="evidence/not-payment-proof.json",
        payment_source="stripe_paid_invoice",
        payment_source_id="in_forged",
    )
    with pytest.raises(LifecycleConflictError, match="authoritative payment proof"):
        store.apply(forged_customer)

    wrong_account = _paid_proof(account_id="acct_other", source_id="in_forged")
    with pytest.raises(LifecycleConflictError, match="authoritative payment proof"):
        store.apply(forged_customer, payment_proof=wrong_account)


def test_customer_transition_requires_matching_authoritative_payment_proof():
    store = LifecycleStateStore()
    store.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")
    for current, target in [
        (RevenueState.LEAD, RevenueState.ENGAGED),
        (RevenueState.ENGAGED, RevenueState.QUALIFIED),
        (RevenueState.QUALIFIED, RevenueState.CHECKOUT_STARTED),
    ]:
        store.apply(_transition("acct_1", current, target))

    proof = _paid_proof()
    customer = _transition(
        "acct_1",
        RevenueState.CHECKOUT_STARTED,
        RevenueState.CUSTOMER,
        reason="verified live Stripe invoice paid",
        evidence="evidence/customer.json",
        payment_proof=proof,
    )

    mismatched = _paid_proof(source_id="in_other")
    with pytest.raises(LifecycleConflictError, match="do not match"):
        store.apply(customer, payment_proof=mismatched)

    record, created = store.apply(customer, payment_proof=proof)
    assert created is True
    assert record.state == RevenueState.CUSTOMER
    evidence = store.history("acct_1")[-1]
    assert evidence.payment_source == "stripe_paid_invoice"
    assert evidence.payment_source_id == "in_123"
    assert store.verify_chain("acct_1") is True


def test_non_customer_transition_rejects_payment_fields():
    store = LifecycleStateStore()
    store.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")
    forged = LifecycleTransition(
        account_id="acct_1",
        from_state=RevenueState.LEAD,
        to_state=RevenueState.ENGAGED,
        reason="smuggle payment metadata",
        evidence_ref="evidence/engaged.json",
        payment_source="stripe_paid_invoice",
        payment_source_id="in_123",
    )
    with pytest.raises(LifecycleConflictError, match="valid only for CUSTOMER"):
        store.apply(forged)


def test_two_stale_store_instances_reload_before_write(tmp_path):
    path = tmp_path / "lifecycle.json"
    first = LifecycleStateStore(path)
    second = LifecycleStateStore(path)

    first.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")
    first.apply(_transition("acct_1", RevenueState.LEAD, RevenueState.ENGAGED))

    # second was created before first wrote; authoritative reload must make this valid.
    record, created = second.apply(
        _transition("acct_1", RevenueState.ENGAGED, RevenueState.QUALIFIED)
    )
    assert created is True
    assert record.state == RevenueState.QUALIFIED
    assert record.version == 2

    final = LifecycleStateStore(path)
    assert final.get("acct_1").state == RevenueState.QUALIFIED
    assert len(final.history("acct_1")) == 3
    assert final.verify_chain("acct_1") is True


def test_raw_reason_is_not_persisted_and_chain_tampering_is_detected(tmp_path):
    path = tmp_path / "lifecycle.json"
    store = LifecycleStateStore(path)
    store.initialize(account_id="acct_1", evidence_ref="evidence/lead.json")
    private_reason = "qualified after contact person@example.com clicked pricing"
    store.apply(
        _transition(
            "acct_1",
            RevenueState.LEAD,
            RevenueState.ENGAGED,
            reason=private_reason,
            evidence="evidence/engaged.json",
        )
    )

    persisted = path.read_text(encoding="utf-8")
    assert private_reason not in persisted
    assert "person@example.com" not in persisted
    assert "reason_hash" in persisted
    assert store.verify_chain() is True

    payload = json.loads(persisted)
    payload["history"][1]["entry_hash"] = "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    tampered = LifecycleStateStore(path)
    assert tampered.verify_chain("acct_1") is False
