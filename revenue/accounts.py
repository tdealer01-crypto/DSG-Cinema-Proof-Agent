"""Customer accounts, API keys, and entitlement state.

An API key is `dsg_<mode>_<key_id>_<secret>`. Only the SHA-256 of the secret is
stored, so a leaked store cannot be replayed against the API. The plaintext key
is returned exactly once, at issue time.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .pricing import DEFAULT_PLAN, get_plan

KEY_PATTERN = re.compile(r"^dsg_(live|test)_([0-9a-f]{16})_([0-9a-f]{48})$")

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_CLOSED = "closed"

_VALID_STATUSES = {STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_CLOSED}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass
class Account:
    account_id: str
    display_name: str
    plan: str = DEFAULT_PLAN
    status: str = STATUS_ACTIVE
    channel: str = "api"
    key_id: str = ""
    secret_hash: str = ""
    mode: str = "live"
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    payment_linked: bool = False
    stripe_paid_amounts_micros: dict[str, int] = field(default_factory=dict)
    stripe_paid_invoice_ids: list[str] = field(default_factory=list)
    stripe_processed_event_ids: list[str] = field(default_factory=list)
    stripe_field_event_created: dict[str, int] = field(default_factory=dict)
    activation_ref: Optional[str] = None
    unit_price_micros: Optional[int] = None
    hard_cap_units: Optional[int] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    def public_view(self) -> dict:
        """Account fields that are safe to return to the account holder."""
        return {
            "account_id": self.account_id,
            "display_name": self.display_name,
            "plan": self.plan,
            "status": self.status,
            "channel": self.channel,
            "mode": self.mode,
            "payment_linked": self.payment_linked,
            "self_activated": self.activation_ref is not None,
            "unit_price_micros": self.unit_price_micros,
            "hard_cap_units": self.hard_cap_units,
            "created_at": self.created_at,
        }


class AccountStore:
    """Account registry, optionally backed by a shared JSON file.

    Persistence rewrites the whole registry, so a process holding a stale view
    would erase another replica's changes. A Stripe webhook upgrading a paying
    customer on one replica would be reverted to the free plan by an unrelated
    write on another. Every read-modify-write therefore takes an advisory lock
    on a sidecar file and re-reads the registry first.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._accounts: dict[str, Account] = {}
        self._by_key_id: dict[str, str] = {}
        self._path = Path(path) if path else None
        self._loaded_signature: Optional[tuple[int, int]] = None
        if self._path and self._path.exists():
            self._load()

    def _file_signature(self) -> Optional[tuple[int, int]]:
        if self._path is None:
            return None
        try:
            info = self._path.stat()
        except FileNotFoundError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def _load(self) -> None:
        assert self._path is not None
        raw = json.loads(self._path.read_text(encoding="utf-8") or "[]")
        self._accounts = {}
        self._by_key_id = {}
        for item in raw:
            account = Account(**item)
            self._accounts[account.account_id] = account
            if account.key_id:
                self._by_key_id[account.key_id] = account.account_id
        self._loaded_signature = self._file_signature()

    def _reload_if_changed(self) -> None:
        """Reload authoritative account state after lock acquisition."""
        if self._path is None or not self._path.exists():
            return
        self._load()

    @contextmanager
    def _file_lock(self):
        """Advisory exclusive lock shared by every process using this registry.

        The lock lives on a sidecar file because the registry itself is replaced
        by rename on each write, which would drop a lock held on the old inode.
        """
        if self._path is None:
            yield
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        with open(lock_path, "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _critical_section(self):
        """Serialize against other threads and other processes, then refresh."""
        with self._lock:
            with self._file_lock():
                # Reload unconditionally while holding the inter-process lock. Cached
                # mtime/size metadata on shared filesystems cannot prevent stale
                # whole-file updates from overwriting another replica.
                self._reload_if_changed()
                # Metadata signatures are only an optimization for readers. The
                # unconditional load above is required before read-modify-write on
                # shared filesystems.
                yield

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([account.to_dict() for account in self._accounts.values()], indent=2)
        fd, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            directory_fd = os.open(self._path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except AttributeError:
            pass
        self._loaded_signature = self._file_signature()

    # ---------------------------------------------------------------- lookups
    def get(self, account_id: str) -> Optional[Account]:
        with self._critical_section():
            return self._accounts.get(account_id)

    def all(self) -> list[Account]:
        with self._critical_section():
            return list(self._accounts.values())

    def find_by_stripe_customer(self, customer_id: str) -> Optional[Account]:
        with self._critical_section():
            for account in self._accounts.values():
                if account.stripe_customer_id == customer_id:
                    return account
        return None

    def apply_stripe_event(
        self,
        *,
        customer_id: str,
        subscription_id: str,
        event_id: str,
        event_created: int,
        allow_subscription_binding: bool,
        changes: dict,
        paid_period: Optional[str] = None,
        paid_amount_micros: Optional[int] = None,
        paid_invoice_id: Optional[str] = None,
    ) -> tuple[Optional[Account], str]:
        """Atomically apply one already-verified, DSG-scoped Stripe event.

        Stripe retries and delivers webhooks out of order.  The account store
        therefore owns idempotency and ordering rather than leaving them to an
        HTTP handler.  A subscription can be bound only by an event whose
        catalog scope was validated by ``stripe_sync.apply_webhook_event``.
        """
        allowed = {
            "plan",
            "status",
            "stripe_subscription_id",
            "payment_linked",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot apply Stripe fields: {sorted(unknown)}")
        if "plan" in changes:
            get_plan(changes["plan"])
        if "status" in changes and changes["status"] not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {changes['status']}")

        with self._critical_section():
            account = next(
                (
                    candidate
                    for candidate in self._accounts.values()
                    if candidate.stripe_customer_id == customer_id
                ),
                None,
            )
            if account is None:
                return None, "unknown_customer"
            if event_id in account.stripe_processed_event_ids:
                return account, "duplicate"
            if paid_invoice_id and paid_invoice_id in account.stripe_paid_invoice_ids:
                return account, "duplicate_invoice"
            current_subscription = account.stripe_subscription_id
            if current_subscription and current_subscription != subscription_id:
                return account, "subscription_mismatch"
            if not current_subscription and not allow_subscription_binding:
                return account, "subscription_not_bound"

            applied_changes = dict(changes)
            if not current_subscription and allow_subscription_binding:
                applied_changes.setdefault("stripe_subscription_id", subscription_id)

            cursor_for = {
                "plan": "plan",
                "status": "entitlement",
                "payment_linked": "entitlement",
                "stripe_subscription_id": "subscription_binding",
            }
            cursors = dict(account.stripe_field_event_created)
            current_changes: dict = {}
            for field_name, value in applied_changes.items():
                cursor_name = cursor_for[field_name]
                if event_created < cursors.get(cursor_name, 0):
                    continue
                current_changes[field_name] = value
                cursors[cursor_name] = max(
                    cursors.get(cursor_name, 0),
                    event_created,
                )

            paid_amounts = dict(account.stripe_paid_amounts_micros)
            paid_recorded = False
            if paid_period and paid_amount_micros is not None:
                if paid_amount_micros < 0:
                    raise ValueError("paid Stripe amount must not be negative")
                paid_amounts[paid_period] = (
                    paid_amounts.get(paid_period, 0) + paid_amount_micros
                )
                paid_recorded = True

            if not current_changes and not paid_recorded:
                return account, "stale"

            processed = [*account.stripe_processed_event_ids, event_id]
            paid_invoices = list(account.stripe_paid_invoice_ids)
            if paid_invoice_id:
                paid_invoices.append(paid_invoice_id)
            updated = replace(
                account,
                **current_changes,
                stripe_paid_amounts_micros=paid_amounts,
                stripe_paid_invoice_ids=paid_invoices,
                stripe_processed_event_ids=processed,
                stripe_field_event_created=cursors,
                updated_at=utc_now(),
            )
            self._accounts[account.account_id] = updated
            if updated.key_id:
                self._by_key_id[updated.key_id] = account.account_id
            self._persist()
            return updated, "applied"

    def authenticate(self, api_key: str) -> Optional[Account]:
        """Return the account for a presented key, or None.

        The secret comparison is constant time and the key format is validated
        before any lookup, so malformed input cannot probe the registry.
        """
        if not api_key:
            return None
        match = KEY_PATTERN.match(api_key.strip())
        if not match:
            return None
        mode, key_id, secret = match.groups()

        with self._critical_section():
            account_id = self._by_key_id.get(key_id)
            account = self._accounts.get(account_id) if account_id else None

        if account is None or account.mode != mode:
            return None
        if not hmac.compare_digest(account.secret_hash, hash_secret(secret)):
            return None
        return account

    # ----------------------------------------------------------------- writes
    def issue(
        self,
        *,
        display_name: str,
        plan: str = DEFAULT_PLAN,
        channel: str = "api",
        mode: str = "live",
        stripe_customer_id: Optional[str] = None,
        unit_price_micros: Optional[int] = None,
        hard_cap_units: Optional[int] = None,
        activation_ref: Optional[str] = None,
    ) -> tuple[Account, str]:
        """Create an account and return it with its one-time plaintext key."""
        get_plan(plan)
        if mode not in {"live", "test"}:
            raise ValueError("mode must be live or test")

        key_id = secrets.token_hex(8)
        secret = secrets.token_hex(24)
        api_key = f"dsg_{mode}_{key_id}_{secret}"
        account = Account(
            account_id=f"acct_dsg_{secrets.token_hex(8)}",
            display_name=display_name,
            plan=plan,
            channel=channel,
            key_id=key_id,
            secret_hash=hash_secret(secret),
            mode=mode,
            stripe_customer_id=stripe_customer_id,
            unit_price_micros=unit_price_micros,
            hard_cap_units=hard_cap_units,
            activation_ref=activation_ref,
        )

        with self._critical_section():
            self._accounts[account.account_id] = account
            self._by_key_id[key_id] = account.account_id
            self._persist()
        return account, api_key

    def update(self, account_id: str, **changes) -> Account:
        allowed = {
            "plan",
            "status",
            "stripe_customer_id",
            "stripe_subscription_id",
            "payment_linked",
            "unit_price_micros",
            "hard_cap_units",
            "display_name",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot update fields: {sorted(unknown)}")
        if "plan" in changes:
            get_plan(changes["plan"])
        if "status" in changes and changes["status"] not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {changes['status']}")

        with self._critical_section():
            account = self._accounts.get(account_id)
            if account is None:
                raise KeyError(account_id)
            updated = replace(account, **changes, updated_at=utc_now())
            self._accounts[account_id] = updated
            if updated.key_id:
                self._by_key_id[updated.key_id] = account_id
            self._persist()
            return updated

    def import_account(self, account: Account) -> Account:
        """Register a pre-built account (bootstrap from configuration)."""
        get_plan(account.plan)
        if account.status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {account.status}")
        with self._critical_section():
            self._accounts[account.account_id] = account
            if account.key_id:
                self._by_key_id[account.key_id] = account.account_id
            self._persist()
            return account


def accounts_from_env(value: str) -> list[Account]:
    """Build bootstrap accounts from a JSON array in an environment variable.

    Each item must carry `account_id`, `display_name`, `key_id`, and
    `secret_hash`. Plaintext secrets are never accepted here.
    """
    items = json.loads(value)
    if not isinstance(items, list):
        raise ValueError("DSG_REVENUE_ACCOUNTS must be a JSON array")

    accounts: list[Account] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each bootstrap account must be a JSON object")
        if "api_key" in item or "secret" in item:
            raise ValueError("bootstrap accounts must carry secret_hash, not a secret")
        missing = {"account_id", "display_name", "key_id", "secret_hash"} - set(item)
        if missing:
            raise ValueError(f"bootstrap account is missing {sorted(missing)}")
        accounts.append(Account(**item))
    return accounts
