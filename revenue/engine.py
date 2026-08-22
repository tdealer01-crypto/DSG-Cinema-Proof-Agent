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
)
from .remediation import Remediation, remediation_for

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
    PAYMENT_NOT_LINKED: "plan requires a current paid entitlement before any use",
}


class EntitlementChangedError(ValueError):
    """Raised when entitlement changes after authorization but before metering."""

    def __init__(self, decision: str, detail: Optional[str] = None) -> None:
        self.decision = decision
        self.http_status = _HTTP_STATUS.get(decision, 403)
        super().__init__(detail or _DENIAL_DETAIL.get(decision, decision))


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

    @property
    def remediation(self) -> Remediation:
        """The one action that resolves this decision."""
        return remediation_for("OK" if self.authorized else self.decision)

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
            body["channel"] = self.account.channel
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
        *,
        enforcement_ready: bool = True,
        enforcement_blockers: tuple[str, ...] = (),
    ) -> None:
        self.accounts = accounts or AccountStore()
        self.ledger = ledger or LedgerStore()
        self.enforcement_requested = enforce
        self.enforcement_ready = enforcement_ready
        self.enforcement_blockers = enforcement_blockers
        self.enforce = enforce and enforcement_ready

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
        durable_attested = (
            source.get("DSG_REVENUE_STORAGE_DURABLE") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        single_writer = (
            source.get("DSG_REVENUE_SINGLE_WRITER") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        blockers: list[str] = []
        if not source.get("DSG_REVENUE_ACCOUNT_STORE"):
            blockers.append("DSG_REVENUE_ACCOUNT_STORE is not configured")
        if not source.get("DSG_REVENUE_LEDGER_STORE"):
            blockers.append("DSG_REVENUE_LEDGER_STORE is not configured")
        if not durable_attested:
            blockers.append("durable revenue storage is not attested")
        if not single_writer:
            blockers.append("single-writer revenue execution is not attested")

        return cls(
            accounts=accounts,
            ledger=ledger,
            enforce=enforce,
            enforcement_ready=not blockers,
            enforcement_blockers=tuple(blockers),
        )

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
        if plan.requires_linked_payment and not account.payment_linked:
            return denial(PAYMENT_NOT_LINKED)
        if (
            plan.requires_linked_payment
            and plan.base_price_micros > 0
            and account.stripe_paid_amounts_micros.get(current_period, 0)
            < plan.base_price_micros
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

        account = self.accounts.get(authorization.account.account_id)
        if account is None:
            raise EntitlementChangedError(UNKNOWN_KEY, "account no longer exists")
        plan = get_plan(account.plan)
        if account.status != STATUS_ACTIVE:
            raise EntitlementChangedError(
                ACCOUNT_SUSPENDED,
                "account became inactive before metering",
            )
        if plan.requires_linked_payment and not account.payment_linked:
            raise EntitlementChangedError(
                PAYMENT_NOT_LINKED,
                "payment became unlinked before metering",
            )
        if (
            plan.requires_linked_payment
            and plan.base_price_micros > 0
            and account.stripe_paid_amounts_micros.get(authorization.period, 0)
            < plan.base_price_micros
        ):
            raise EntitlementChangedError(
                PAYMENT_NOT_LINKED,
                "paid subscription period is not current",
            )

        unit_price = resolve_unit_price_micros(
            plan,
            get_sku(sku),
            account.unit_price_micros,
        )

        cap = account.hard_cap_units if account.hard_cap_units is not None else plan.hard_cap_units
        return self.ledger.append_metered(
            account_id=account.account_id,
            channel=channel,
            sku=sku,
            quantity=quantity,
            unit_price_micros=unit_price,
            included_units=plan.included_units,
            hard_cap_units=cap,
            proof_hash=proof_hash,
            context_hash=context_hash,
            idempotency_key=idempotency_key(account.account_id, sku, context_hash),
            period=authorization.period,
        )

    # -------------------------------------------------------------- reporting
    def usage_summary(self, account: Account, period: Optional[str] = None) -> dict:
        current_period = period or billing_period()
        plan = get_plan(account.plan)
        entries = self.ledger.period_entries(account.account_id, current_period)

        units = sum(entry.quantity for entry in entries)
        usage_micros = sum(entry.amount_micros for entry in entries)
        paid_invoice_micros = account.stripe_paid_amounts_micros.get(
            current_period,
            0,
        )
        base_recognized = min(
            plan.base_price_micros,
            paid_invoice_micros,
        )
        total_micros = base_recognized + usage_micros
        cap = account.hard_cap_units if account.hard_cap_units is not None else plan.hard_cap_units
        usage_percent = None if cap is None or cap == 0 else round((units / cap) * 100, 2)
        upgrade_threshold_reached = (
            cap is not None and cap > 0 and units * 100 >= cap * 80
        )
        if account.plan == "free" and upgrade_threshold_reached:
            upgrade = {
                "recommended": True,
                "reason": "QUOTA_EXHAUSTED" if cap is not None and units >= cap else "QUOTA_80_PERCENT",
                "target_plan": "metered",
                "checkout_endpoint": "/billing/checkout/session",
            }
        else:
            upgrade = {
                "recommended": False,
                "reason": None,
                "target_plan": None,
                "checkout_endpoint": None,
            }

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
            "usage_percent": usage_percent,
            "upgrade": upgrade,
            "hard_cap_units": cap,
            "catalog_base_price_micros": plan.base_price_micros,
            "paid_invoice_amount_micros": paid_invoice_micros,
            "base_price_micros": base_recognized,
            "base_recognition": (
                "PAID_INVOICE" if base_recognized else "NOT_RECOGNIZED"
            ),
            "usage_amount_micros": usage_micros,
            "total_amount_micros": total_micros,
            "total_amount_usd": micros_to_usd_string(total_micros),
            "recognized_amount_micros": paid_invoice_micros,
            "recognized_amount_usd": micros_to_usd_string(paid_invoice_micros),
            "by_sku": sorted(by_sku.values(), key=lambda item: item["sku"]),
            "ledger_head_hash": self.ledger.head_hash(),
        }

    def channel_report(self, period: Optional[str] = None) -> list[dict]:
        """Attribute units and amount to the sales channel that delivered them.

        Ledger entries carry the channel the request arrived on, and accounts
        carry the channel that acquired them. Both are reported: a customer
        acquired through GitHub may verify through the direct API.
        """
        current_period = period or billing_period()
        entries = [
            entry for entry in self.ledger.entries() if entry.period == current_period
        ]

        buckets: dict[str, dict] = {}
        for entry in entries:
            bucket = buckets.setdefault(
                entry.channel,
                {
                    "channel": entry.channel,
                    "units": 0,
                    "amount_micros": 0,
                    "accounts": set(),
                },
            )
            bucket["units"] += entry.quantity
            bucket["amount_micros"] += entry.amount_micros
            bucket["accounts"].add(entry.account_id)

        acquired: dict[str, int] = {}
        for account in self.accounts.all():
            acquired[account.channel] = acquired.get(account.channel, 0) + 1

        for channel, count in acquired.items():
            buckets.setdefault(
                channel,
                {"channel": channel, "units": 0, "amount_micros": 0, "accounts": set()},
            )

        report = []
        for channel, bucket in buckets.items():
            report.append(
                {
                    "channel": channel,
                    "units": bucket["units"],
                    "amount_micros": bucket["amount_micros"],
                    "amount_usd": micros_to_usd_string(bucket["amount_micros"]),
                    "active_accounts": len(bucket["accounts"]),
                    "accounts_acquired": acquired.get(channel, 0),
                }
            )
        return sorted(report, key=lambda item: item["channel"])

    def period_report(self, period: Optional[str] = None) -> dict:
        """Aggregate every account for one billing period."""
        current_period = period or billing_period()
        accounts = sorted(self.accounts.all(), key=lambda item: item.account_id)

        summaries = []
        recognized_micros = 0
        recorded_usage_micros = 0
        billable_units = 0
        for account in accounts:
            summary = self.usage_summary(account, current_period)
            if summary["units"] == 0 and summary["recognized_amount_micros"] == 0:
                continue
            summaries.append(summary)
            recognized_micros += summary["recognized_amount_micros"]
            recorded_usage_micros += summary["usage_amount_micros"]
            billable_units += summary["units"]

        chain = verify_chain(self.ledger.entries())
        return {
            "period": current_period,
            "accounts_with_activity": len(summaries),
            "accounts_billed": sum(
                1
                for summary in summaries
                if summary["recognized_amount_micros"] > 0
            ),
            "billable_units": billable_units,
            "recorded_usage_amount_micros": recorded_usage_micros,
            "recorded_usage_amount_usd": micros_to_usd_string(recorded_usage_micros),
            "recognized_amount_micros": recognized_micros,
            "recognized_amount_usd": micros_to_usd_string(recognized_micros),
            "ledger": chain,
            "by_channel": self.channel_report(current_period),
            "accounts": summaries,
        }
