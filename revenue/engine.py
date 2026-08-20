"""Revenue engine: entitlement authorization and proof-bound metering.

Two rules hold everywhere in this module:

1. Fail closed. An unknown key, a suspended account, or an exhausted quota
   never falls through to a free proof.
2. Bill only what was proved. `record_usage` refuses any receipt that is not
   VERIFIED_GLOBAL_OPTIMUM, so a failed verification can never create revenue.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional

from .accounts import (
    STATUS_ACTIVE,
    Account,
    AccountStore,
    accounts_from_env,
)
from .ledger import (
    LedgerEntry,
    LedgerStore,
    billing_period,
    verify_chain,
)
from .pricing import (
    Plan,
    get_plan,
    get_sku,
    micros_to_usd_string,
    resolve_unit_price_micros,
    unit_amount_micros,
)

VERIFIED_STATE = "VERIFIED_GLOBAL_OPTIMUM"

AUTHORIZED = "AUTHORIZED"
UNKNOWN_KEY = "UNKNOWN_KEY"
ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
PAYMENT_NOT_LINKED = "PAYMENT_NOT_LINKED"

_HTTP_STATUS = {
    UNKNOWN_KEY: 401,
    ACCOUNT_SUSPENDED: 403,
    QUOTA_EXCEEDED: 402,
    PAYMENT_NOT_LINKED: 402,
}

_DENIAL_DETAIL = {
    UNKNOWN_KEY: "a valid X-DSG-API-Key header is required",
    ACCOUNT_SUSPENDED: "account is not active",
    QUOTA_EXCEEDED: "plan quota for this billing period is exhausted",
    PAYMENT_NOT_LINKED: "plan requires a linked payment method before metered use",
}


@dataclass(frozen=True)
class Authorization:
    decision: str
    account: Optional[Account]
    plan: Optional[Plan]
    period: str
    units_used: int
    units_included: int
    units_remaining: Optional[int]
    unit_price_micros: Optional[int]
    detail: Optional[str] = None

    @property
    def authorized(self) -> bool:
        return self.decision == AUTHORIZED

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self.decision, 403)

    def summary(self) -> dict:
        body = {
            "decision": self.decision,
            "period": self.period,
            "units_used": self.units_used,
            "units_included": self.units_included,
            "units_remaining": self.units_remaining,
            "unit_price_micros": self.unit_price_micros,
        }
        if self.account is not None:
            body["account_id"] = self.account.account_id
            body["plan"] = self.account.plan
        if self.detail:
            body["detail"] = self.detail
        return body


def idempotency_key(account_id: str, sku: str, context_hash: str) -> str:
    """One billable unit per (account, sku, verification context)."""
    raw = f"{account_id}|{sku}|{context_hash}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class RevenueEngine:
    def __init__(
        self,
        accounts: Optional[AccountStore] = None,
        ledger: Optional[LedgerStore] = None,
        enforce: bool = False,
    ) -> None:
        self.accounts = accounts or AccountStore()
        self.ledger = ledger or LedgerStore()
        self.enforce = enforce

    # ----------------------------------------------------------- construction
    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "RevenueEngine":
        source = env if env is not None else os.environ
        accounts = AccountStore(source.get("DSG_REVENUE_ACCOUNT_STORE") or None)
        ledger = LedgerStore(source.get("DSG_REVENUE_LEDGER_STORE") or None)

        bootstrap = (source.get("DSG_REVENUE_ACCOUNTS") or "").strip()
        if bootstrap:
            for account in accounts_from_env(bootstrap):
                accounts.import_account(account)

        enforce = (source.get("DSG_REVENUE_ENFORCE") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(accounts=accounts, ledger=ledger, enforce=enforce)

    # ------------------------------------------------------------ entitlement
    def authorize(
        self,
        api_key: Optional[str],
        sku: str,
        *,
        period: Optional[str] = None,
    ) -> Authorization:
        sku_spec = get_sku(sku)
        current_period = period or billing_period()

        account = self.accounts.authenticate(api_key or "")
        if account is None:
            return Authorization(
                decision=UNKNOWN_KEY,
                account=None,
                plan=None,
                period=current_period,
                units_used=0,
                units_included=0,
                units_remaining=0,
                unit_price_micros=None,
                detail=_DENIAL_DETAIL[UNKNOWN_KEY],
            )

        plan = get_plan(account.plan)
        units_used = self.ledger.units_used(account.account_id, current_period)
        unit_price = resolve_unit_price_micros(plan, sku_spec, account.unit_price_micros)
        cap = account.hard_cap_units if account.hard_cap_units is not None else plan.hard_cap_units
        remaining = None if cap is None else max(cap - units_used, 0)

        def denial(decision: str) -> Authorization:
            return Authorization(
                decision=decision,
                account=account,
                plan=plan,
                period=current_period,
                units_used=units_used,
                units_included=plan.included_units,
                units_remaining=remaining,
                unit_price_micros=unit_price,
                detail=_DENIAL_DETAIL[decision],
            )

        if account.status != STATUS_ACTIVE:
            return denial(ACCOUNT_SUSPENDED)
        if cap is not None and units_used >= cap:
            return denial(QUOTA_EXCEEDED)
        if (
            plan.requires_linked_payment
            and not account.payment_linked
            and units_used >= plan.included_units
        ):
            return denial(PAYMENT_NOT_LINKED)

        return Authorization(
            decision=AUTHORIZED,
            account=account,
            plan=plan,
            period=current_period,
            units_used=units_used,
            units_included=plan.included_units,
            units_remaining=remaining,
            unit_price_micros=unit_price,
        )

    # --------------------------------------------------------------- metering
    def record_usage(
        self,
        authorization: Authorization,
        *,
        sku: str,
        receipt: dict,
        channel: str = "api",
        quantity: int = 1,
    ) -> tuple[LedgerEntry, bool]:
        """Append one proof-bound usage entry. Returns (entry, created)."""
        if not authorization.authorized or authorization.account is None:
            raise ValueError("cannot record usage for an unauthorized request")
        if quantity < 1:
            raise ValueError("quantity must be at least 1")

        if receipt.get("verified") is not True:
            raise ValueError("refusing to meter an unverified receipt")
        if receipt.get("verification") != VERIFIED_STATE:
            raise ValueError("refusing to meter a receipt without a global optimum proof")

        proof_hash = receipt.get("proof_hash")
        context_hash = receipt.get("context_hash")
        if not isinstance(proof_hash, str) or len(proof_hash) != 64:
            raise ValueError("receipt proof_hash is invalid")
        if not isinstance(context_hash, str) or len(context_hash) != 64:
            raise ValueError("receipt context_hash is invalid")

        account = authorization.account
        plan = authorization.plan or get_plan(account.plan)
        unit_price = authorization.unit_price_micros
        if unit_price is None:
            unit_price = resolve_unit_price_micros(plan, get_sku(sku), account.unit_price_micros)

        units_before = self.ledger.units_used(account.account_id, authorization.period)
        amount = unit_amount_micros(plan, unit_price, units_before, quantity)

        return self.ledger.append(
            account_id=account.account_id,
            channel=channel,
            sku=sku,
            quantity=quantity,
            unit_price_micros=unit_price,
            amount_micros=amount,
            proof_hash=proof_hash,
            context_hash=context_hash,
            idempotency_key=idempotency_key(account.account_id, sku, context_hash),
            units_before=units_before,
        )

    # -------------------------------------------------------------- reporting
    def usage_summary(self, account: Account, period: Optional[str] = None) -> dict:
        current_period = period or billing_period()
        plan = get_plan(account.plan)
        entries = self.ledger.period_entries(account.account_id, current_period)

        units = sum(entry.quantity for entry in entries)
        usage_micros = sum(entry.amount_micros for entry in entries)
        total_micros = plan.base_price_micros + usage_micros
        cap = account.hard_cap_units if account.hard_cap_units is not None else plan.hard_cap_units

        by_sku: dict[str, dict] = {}
        for entry in entries:
            bucket = by_sku.setdefault(
                entry.sku,
                {"sku": entry.sku, "units": 0, "amount_micros": 0},
            )
            bucket["units"] += entry.quantity
            bucket["amount_micros"] += entry.amount_micros

        return {
            "account": account.public_view(),
            "period": current_period,
            "units": units,
            "units_included": plan.included_units,
            "units_remaining": None if cap is None else max(cap - units, 0),
            "hard_cap_units": cap,
            "base_price_micros": plan.base_price_micros,
            "usage_amount_micros": usage_micros,
            "total_amount_micros": total_micros,
            "total_amount_usd": micros_to_usd_string(total_micros),
            "by_sku": sorted(by_sku.values(), key=lambda item: item["sku"]),
            "ledger_head_hash": self.ledger.head_hash(),
        }

    def period_report(self, period: Optional[str] = None) -> dict:
        """Aggregate every account for one billing period."""
        current_period = period or billing_period()
        accounts = sorted(self.accounts.all(), key=lambda item: item.account_id)

        summaries = []
        recognized_micros = 0
        billable_units = 0
        for account in accounts:
            summary = self.usage_summary(account, current_period)
            if summary["units"] == 0 and summary["base_price_micros"] == 0:
                continue
            summaries.append(summary)
            recognized_micros += summary["total_amount_micros"]
            billable_units += summary["units"]

        chain = verify_chain(self.ledger.entries())
        return {
            "period": current_period,
            "accounts_billed": len(summaries),
            "billable_units": billable_units,
            "recognized_amount_micros": recognized_micros,
            "recognized_amount_usd": micros_to_usd_string(recognized_micros),
            "ledger": chain,
            "accounts": summaries,
        }
